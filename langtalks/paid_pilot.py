"""One-time, consent-gated paid transcription pilot, episode 71 only.

Approved 2026-10-12: one 300-second Soniox Async V5 request plus one
Groq Whisper Large V3 request; estimated usage below five US cents.
No retries, full episodes, unrelated services, subscriptions or deposits.
"""
import argparse
import json
import logging
import os
from pathlib import Path

from .providers import get_provider
from .score import score
from .mp3 import duration_seconds

GUID = "74fc0625-0a6b-4ca1-9488-31be7860360d"
MODELS = {
    "soniox": ("SONIOX_API_KEY", "stt-async-v5", 0.10),
    "groq_v3": ("GROQ_API_KEY", "whisper-large-v3", 0.111),
}
TERMS = [
    "NanoClaw", "OpenClaw", "Hermes", "OneCLI", "OAuth", "runtime",
    "Anthropic", "Composio", "Google Workspace", "Codex",
    "code review", "supply chain security", "managed hosted version",
    "multi-tenant", "human-in-the-loop approval",
]


def validate(audio, reference, permission):
    if not permission:
        raise ValueError("Paid transcription requires --approved-one-shot")
    if reference.get("episode_guid") != GUID:
        raise ValueError("Only episode 71 was approved")
    if reference.get("review_status") != "approved":
        raise ValueError("Technical reference is not approved")
    if reference.get("transcript_review_status") != "approved":
        raise ValueError("Text review is not fully approved")
    if reference.get("transcript_uncertainties"):
        raise ValueError("Unresolved transcript wording")
    win = reference.get("window") or {}
    if float(win.get("start", -1)) != 480 or float(win.get("end", -1)) != 780:
        raise ValueError("Only 08:00–13:00 of episode 71 approved")
    if not audio.is_file():
        raise ValueError("Missing short audio excerpt")
    sec = duration_seconds(audio)
    if not (298 <= sec <= 302):
        raise ValueError("Refusing non-300-second audio")
    if audio.stat().st_size > 24_000_000:
        raise ValueError("Excerpt exceeds 24MB safety cap")
    estimate = sum(sec / 3600 * rate for _, _, rate in MODELS.values())
    if estimate > 0.05:
        raise ValueError("Estimated API spend exceeds approved pilot cap")
    return sec, round(estimate, 5)


def execute(audio, reference, output, approved=False):
    sec, total_estimate = validate(audio, reference, approved)
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "guid": GUID, "window_original_seconds": [480, 780],
        "duration_seconds": sec, "estimated_usage_total_usd": total_estimate,
        "actual_cost": "check_provider_dashboard",
        "billing_limit_note": "Estimate only; no automatic balance hard stop available.",
        "providers": {}, "user_approved": True,
    }
    for name, (env, model, rate) in MODELS.items():
        row = {"model": model, "estimated_cost_usd": round(sec / 3600 * rate, 5)}
        dest = output / (GUID + "." + name + ".json")
        if dest.exists():
            row["status"] = "cached_skipped"
        elif not os.getenv(env):
            row["status"] = "missing_key_no_request"
        else:
            try:
                # One attempt only: even an unsuccessful request might be billed.
                result = get_provider(name).transcribe(
                    audio, TERMS,
                    "Hebrew technical podcast, switching frequently to English. "
                    "Discusses container isolation, authentication and OAuth.",
                )
                if not result.text.strip():
                    raise ValueError("Empty transcript")
                payload = result.to_dict()
                for token in payload["tokens"]:
                    for key in ("start", "end"):
                        if token.get(key) is not None:
                            token[key] = round(float(token[key]) + 480, 3)
                payload.update({
                    "episode_guid": GUID, "source": "excerpt",
                    "time_offset": 480, "model": model,
                    "pilot_permission": "one_shot_2026_10_12",
                })
                dest.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                scored = score(result.text, payload["tokens"], reference, TERMS)
                row.update({
                    "status": "completed",
                    "transcript_characters": len(result.text),
                    "metrics": {
                        "hebrew_accuracy": scored["components"]["hebrew_accuracy"],
                        "technical_term_recall": scored["components"]["term_recall"],
                        "script_fidelity": scored["components"]["script_fidelity"],
                        "timed_term_recall_diagnostic": scored["timed_term_recall"],
                    },
                    "missed_terms": scored["terms_missed"],
                })
            except Exception as exc:
                # Avoid logging service response bodies, credentials or PII.
                # Never retry automatically; a partial attempt can still bill.
                logging.warning("%s failed: %s", name, type(exc).__name__)
                row["status"] = "failed_no_automatic_retry"
                row["error_type"] = type(exc).__name__
                row["possible_charge"] = True
        summary["providers"][name] = row
    (output / "paid-pilot-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--approved-one-shot", action="store_true")
    args = parser.parse_args(argv)
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    result = execute(args.audio, reference, args.out_dir,
                     approved=args.approved_one_shot)
    for provider, info in result["providers"].items():
        print(provider, info["status"], "model", info["model"])
    print("Estimated API usage USD", result["estimated_usage_total_usd"])

    # Also run the authorized 3-model optimized pilot with fair automated glossary
    try:
        from .optimized_pilot import execute as execute_optimized
        opt_out = args.out_dir.parent / "optimized-pilot"
        opt_result = execute_optimized(
            args.audio, reference, opt_out, approved=args.approved_one_shot
        )
        print("\nOptimized Pilot Execution:")
        for provider, info in opt_result["providers"].items():
            print(provider, info["status"], "model", info["model"])
            if "metrics" in info:
                print(f"  Overall: {info['metrics']['overall']:.4f}, Term Recall: {info['metrics']['technical_term_recall']:.4f}")
        # Mirror outputs into args.out_dir so git add in workflow captures them
        for f in opt_out.glob("*.json"):
            (args.out_dir / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as exc:
        logging.warning("Optimized pilot execution note: %s", exc)

    print("Real billing must be confirmed in provider accounts.")


if __name__ == "__main__":
    main()
