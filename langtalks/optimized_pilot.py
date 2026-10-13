"""Consent-gated optimized paid transcription pilot on Episode 71 five-minute benchmark.

Evaluates three cloud configurations under the fair automated glossary:
1. Soniox Async V5 (stt-async-v5) with structured context dictionary & terms
2. Groq Whisper Large V3 (whisper-large-v3) with word timestamps & fair prompt
3. Groq Whisper Large V3 Turbo (whisper-large-v3-turbo) with word timestamps & fair prompt

Strict Safeguards:
- Explicit approval gate flag (--approved-one-shot required)
- Strict audio duration validation (300s +/- 2s)
- Conservative spend ceiling (< $0.05 total)
- Exactly one attempt per provider (zero automatic retries)
- Separate destination directory: langtalks/reviewed/episode71/optimized-pilot/
- Safe error handling without logging credentials
"""

import argparse
import json
import logging
import os
from pathlib import Path

from .feed import fetch_episodes
from .glossary import build, for_soniox
from .mp3 import duration_seconds
from .providers import get_provider
from .score import score, load_reference

logger = logging.getLogger(__name__)

GUID = "74fc0625-0a6b-4ca1-9488-31be7860360d"

# Rate card in USD per audio hour
MODELS = {
    "soniox": ("SONIOX_API_KEY", "stt-async-v5", 0.10),
    "groq_v3": ("GROQ_API_KEY", "whisper-large-v3", 0.111),
    "groq_turbo": ("GROQ_API_KEY", "whisper-large-v3-turbo", 0.04),
}


def validate(audio: Path, reference: dict, approved: bool = False):
    if not approved:
        raise ValueError("Paid transcription requires explicit approval flag: --approved-one-shot")
    if reference.get("episode_guid") != GUID:
        raise ValueError(f"Only episode 71 ({GUID}) was approved")
    if reference.get("review_status") != "approved":
        raise ValueError("Technical reference is not approved")
    if reference.get("transcript_review_status") != "approved":
        raise ValueError("Text review is not fully approved")
    if reference.get("transcript_uncertainties"):
        raise ValueError("Unresolved transcript wording in reference")

    win = reference.get("window") or {}
    if float(win.get("start", -1)) != 480 or float(win.get("end", -1)) != 780:
        raise ValueError("Only 08:00–13:00 (480s-780s) of episode 71 is approved")

    if not audio.is_file():
        raise ValueError(f"Missing audio excerpt at {audio}")

    sec = duration_seconds(audio)
    if not (298 <= sec <= 302):
        raise ValueError(f"Refusing non-300-second audio: {sec}s")
    if audio.stat().st_size > 24_000_000:
        raise ValueError(f"Excerpt exceeds 24MB safety cap: {audio.stat().st_size} bytes")

    estimate = sum(sec / 3600.0 * rate for _, _, rate in MODELS.values())
    if estimate > 0.05:
        raise ValueError(f"Estimated API spend (${estimate:.4f}) exceeds approved pilot cap ($0.05)")

    return sec, round(estimate, 5)


def execute(audio: Path, reference: dict, output_dir: Path, approved: bool = False) -> dict:
    sec, total_estimate = validate(audio, reference, approved)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Fetch episode metadata for fair glossary
    episodes = fetch_episodes()
    episode = next((e for e in episodes if e.guid == GUID or e.number == 71), None)
    if not episode:
        raise RuntimeError(f"Episode {GUID} not found in RSS feed")

    terms = build(episode)
    soniox_context = for_soniox(episode)

    summary = {
        "guid": GUID,
        "episode_number": 71,
        "episode_title": episode.title,
        "window_original_seconds": [480, 780],
        "duration_seconds": sec,
        "estimated_usage_total_usd": total_estimate,
        "actual_cost_note": "Groq usage is $0.00 within free tier; Soniox is metered at $0.10/hr.",
        "billing_safeguard": "Hard-capped to 300s single-attempt evaluation. Zero automatic retries.",
        "providers": {},
        "user_approved": approved,
    }

    for name, (env_var, model_name, rate) in MODELS.items():
        row = {
            "model": model_name,
            "estimated_cost_usd": round(sec / 3600.0 * rate, 5),
            "env_key": env_var,
        }
        dest = output_dir / f"{GUID}.optimized_{name}.json"

        if dest.exists():
            row["status"] = "cached_skipped"
            row["output_file"] = str(dest)
            summary["providers"][name] = row
            continue

        if not os.getenv(env_var):
            row["status"] = "missing_key_no_request"
            summary["providers"][name] = row
            continue

        try:
            provider = get_provider(name)
            # Pass provider-specific fair context
            prompt_arg = soniox_context if name == "soniox" else ""

            logger.info("Executing paid request: %s (%s)", name, model_name)
            result = provider.transcribe(audio, terms, prompt_arg)

            if not result.text.strip():
                raise ValueError("Empty transcript returned by provider")

            payload = result.to_dict()
            # Offset tokens to absolute episode timestamp (starts at 480.0s)
            for token in payload.get("tokens", []):
                for key in ("start", "end"):
                    if token.get(key) is not None:
                        token[key] = round(float(token[key]) + 480.0, 3)

            payload.update({
                "episode_guid": GUID,
                "episode_title": episode.title,
                "source": "excerpt",
                "time_offset": 480.0,
                "model": model_name,
                "glossary_type": "automated_reference_independent",
            })

            dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            # Score against ground truth
            scored = score(result.text, payload["tokens"], reference, terms)
            row.update({
                "status": "completed",
                "output_file": str(dest),
                "transcript_characters": len(result.text),
                "words_count": len(payload["tokens"]),
                "metrics": {
                    "overall": scored["overall"],
                    "hebrew_accuracy": scored["components"]["hebrew_accuracy"],
                    "technical_term_recall": scored["components"]["term_recall"],
                    "script_fidelity": scored["components"]["script_fidelity"],
                    "timed_term_recall": scored["timed_term_recall"].get("recall") if isinstance(scored.get("timed_term_recall"), dict) else scored.get("timed_term_recall"),
                },
                "terms_found": scored.get("terms_found", []),
                "terms_missed": scored.get("terms_missed", []),
            })

        except Exception as exc:
            logger.warning("%s failed: %s", name, type(exc).__name__)
            row["status"] = "failed_no_automatic_retry"
            row["error_type"] = type(exc).__name__
            row["error_message"] = str(exc)
            row["possible_charge"] = True

        summary["providers"][name] = row

    summary_file = output_dir / "optimized-pilot-summary.json"
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--approved-one-shot", action="store_true")
    args = parser.parse_args(argv)

    reference = load_reference(args.reference)
    result = execute(
        audio=args.audio,
        reference=reference,
        output_dir=args.out_dir,
        approved=args.approved_one_shot,
    )

    print("\n=== Optimized Pilot Execution Summary ===")
    for provider, info in result["providers"].items():
        print(f"  {provider} ({info['model']}): status={info['status']}, est_cost=${info.get('estimated_cost_usd', 0.0)}")
        if "metrics" in info:
            print(f"    Overall: {info['metrics']['overall']:.4f}, Term Recall: {info['metrics']['technical_term_recall']:.4f}")
    print(f"\nTotal Estimated Usage: ${result['estimated_usage_total_usd']:.5f} USD")


if __name__ == "__main__":
    main()
