"""LangTalks ASR benchmark CLI.

    python -m langtalks.bench episodes                 # list recent episodes
    python -m langtalks.bench fetch 71 70 69           # download audio
    python -m langtalks.bench glossary 71              # inspect the keyterms
    python -m langtalks.bench transcribe 71 --provider soniox
    python -m langtalks.bench score 71                 # score every transcript
    python -m langtalks.bench report                   # comparison table

Transcripts land in ``langtalks/out/transcripts/<guid>.<provider>.json`` and are
never overwritten, so re-running score/report costs nothing.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import glossary as glossary_mod
from . import mp3
from . import providers as providers_mod
from . import score as score_mod
from .feed import audio_sha256, download_audio, fetch_episodes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("langtalks.bench")

ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / "out" / "audio"
EXCERPT_DIR = ROOT / "out" / "excerpts"
TRANSCRIPT_DIR = ROOT / "out" / "transcripts"
REFERENCE_DIR = ROOT / "reference"


def _resolve(selectors, episodes):
    """Map CLI selectors (episode numbers or guid prefixes) to episodes."""
    resolved = []
    for selector in selectors:
        match = None
        if selector.isdigit():
            match = next((e for e in episodes if e.number == int(selector)), None)
        if match is None:
            match = next((e for e in episodes if e.guid.startswith(selector)), None)
        if match is None:
            raise SystemExit(f"No episode matches '{selector}'")
        resolved.append(match)
    return resolved


def cmd_episodes(args):
    episodes = fetch_episodes()
    for episode in episodes[: args.limit]:
        minutes = episode.duration_seconds / 60
        print(f"{str(episode.number or '-'):>4}  {episode.published[:16]}  "
              f"{minutes:5.1f}m  {episode.guid[:8]}  {episode.title}")
    print(f"\n{len(episodes)} episodes in feed, "
          f"{sum(e.duration_seconds for e in episodes) / 3600:.1f} hours total")


def cmd_fetch(args):
    episodes = fetch_episodes()
    for episode in _resolve(args.episodes, episodes):
        path = download_audio(episode, AUDIO_DIR)
        print(f"{episode.title}\n  {path} ({path.stat().st_size / 1e6:.1f} MB)"
              f"\n  sha256 {audio_sha256(path)[:16]}")


def cmd_glossary(args):
    episodes = fetch_episodes()
    for episode in _resolve(args.episodes, episodes):
        terms = glossary_mod.build(episode)
        print(f"\n=== {episode.title} — {len(terms)} terms")
        print(", ".join(terms))


def cmd_transcribe(args):
    episodes = fetch_episodes()
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    names = [args.provider] if args.provider else providers_mod.available()
    if not names:
        raise SystemExit(
            "No providers configured. Set SONIOX_API_KEY, ELEVENLABS_API_KEY, "
            "OPENAI_API_KEY, GROQ_API_KEY, or RUNPOD_API_KEY + RUNPOD_ENDPOINT_ID for ivrit.ai "
            "(see langtalks/README.md)."
        )
    logger.info("Providers: %s", ", ".join(names))

    for episode in _resolve(args.episodes, episodes):
        audio_path, is_excerpt = _audio_for(episode, prefer_excerpt=not args.full)
        # An excerpt's timestamps start at zero, but references are annotated in
        # absolute episode time. Shift once here so everything downstream can
        # assume a single timebase.
        offset = 0.0
        if is_excerpt:
            reference_path = REFERENCE_DIR / f"{episode.guid}.json"
            if reference_path.exists():
                offset = (score_mod.load_reference(reference_path)
                          .get("window", {}).get("start", 0.0))
            logger.info("Using excerpt (offset %.0fs): %s", offset, audio_path.name)

        terms = glossary_mod.build(episode)
        prompt = glossary_mod.context_prompt(episode, terms)

        for name in names:
            out_path = TRANSCRIPT_DIR / f"{episode.guid}.{name}.json"
            if out_path.exists() and not args.force:
                logger.info("Have %s already; pass --force to redo", out_path.name)
                continue
            provider = providers_mod.get_provider(name)
            try:
                result = provider.transcribe(audio_path, terms, prompt)
            except Exception as exc:
                logger.error("%s failed on '%s': %s", name, episode.title, exc)
                continue
            payload = result.to_dict()
            if offset:
                for token in payload["tokens"]:
                    for key in ("start", "end"):
                        if token.get(key) is not None:
                            token[key] += offset
            payload["episode_guid"] = episode.guid
            payload["episode_title"] = episode.title
            payload["glossary_size"] = len(terms)
            payload["source"] = "excerpt" if is_excerpt else "full"
            payload["time_offset"] = offset
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("Wrote %s (%d chars)", out_path.name, len(result.text))


def cmd_excerpt(args):
    """Cut the benchmark window out of an episode.

    Providers cap uploads well below a full episode (RunPod ~7 MB of audio,
    OpenAI 25 MB against ~32 MB episodes), and there is no reason to pay to
    transcribe 27 minutes when only the annotated window gets scored.
    """
    episodes = fetch_episodes()
    EXCERPT_DIR.mkdir(parents=True, exist_ok=True)
    for episode in _resolve(args.episodes, episodes):
        source = download_audio(episode, AUDIO_DIR)
        dest = EXCERPT_DIR / f"{episode.guid}.mp3"
        start, end = mp3.slice_mp3(source, dest, args.start, args.end)
        print(f"{episode.title}\n  {dest}\n  {start:.1f}s-{end:.1f}s "
              f"({end - start:.0f}s, {dest.stat().st_size / 1e6:.1f} MB)")


def _audio_for(episode, prefer_excerpt: bool = True):
    """The excerpt if one was cut, otherwise the full episode."""
    excerpt = EXCERPT_DIR / f"{episode.guid}.mp3"
    if prefer_excerpt and excerpt.exists():
        return excerpt, True
    return download_audio(episode, AUDIO_DIR), False


def cmd_reference(args):
    """Scaffold the one annotation the benchmark cannot generate for itself."""
    episodes = fetch_episodes()
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    for episode in _resolve(args.episodes, episodes):
        path = REFERENCE_DIR / f"{episode.guid}.json"
        if path.exists() and not args.force:
            print(f"{path} exists; pass --force to overwrite")
            continue
        stub = {
            "episode_guid": episode.guid,
            "episode_title": episode.title,
            "window": {"start": args.start, "end": args.end},
            "_howto": (
                "Listen to the window and fill in technical_terms with every English "
                "term you hear, in its canonical Latin spelling. That list alone is "
                "enough to score term recall and glossary hallucination. "
                "reference_text and speaker_turns are optional; supply reference_text "
                "to also score Hebrew accuracy and script fidelity."
            ),
            "technical_terms": [],
            "reference_text": "",
            "speaker_turns": [],
        }
        path.write_text(json.dumps(stub, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {path}  (window {args.start:.0f}-{args.end:.0f}s of "
              f"{episode.duration_seconds}s)")


def _score_one(episode_guid: str, episode=None):
    reference_path = REFERENCE_DIR / f"{episode_guid}.json"
    if not reference_path.exists():
        return None, []
    reference = score_mod.load_reference(reference_path)
    # Hallucination is judged against what the model was actually prompted
    # with, so the episode's own glossary is the right comparison set.
    episode_glossary = glossary_mod.build(episode) if episode else None
    window = reference.get("window") or {}
    start = window.get("start", 0.0)
    end = window.get("end", float("inf"))

    rows = []
    for path in sorted(TRANSCRIPT_DIR.glob(f"{episode_guid}.*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        tokens = payload.get("tokens", [])
        if not tokens and payload.get("source") != "excerpt":
            # Without timings we cannot isolate the window, and scoring a whole
            # episode against a window's term list would flatter it badly.
            logger.warning(
                "%s has no token timings and covers the full episode; skipping. "
                "Re-run it against an excerpt.", path.name
            )
            continue
        text = providers_mod.window_text(payload, start, end)
        in_window = [
            t for t in tokens
            if t.get("start") is not None and start <= t["start"] < end
        ]
        result = score_mod.score(text, in_window, reference, episode_glossary)
        result["provider"] = payload.get("provider", path.stem.split(".")[-1])
        rows.append(result)
    return reference, rows


def cmd_score(args):
    episodes = fetch_episodes()
    for episode in _resolve(args.episodes, episodes):
        reference, rows = _score_one(episode.guid, episode)
        if reference is None:
            print(f"\n=== {episode.title}")
            print(f"  No reference yet. Create {REFERENCE_DIR / (episode.guid + '.json')}"
                  f" — see langtalks/README.md for the format.")
            continue
        print(f"\n=== {episode.title}")
        if not rows:
            print(f"  No transcripts yet — run: "
                  f"python -m langtalks.bench transcribe {episode.number or episode.guid[:8]}")
            continue
        if not reference.get("technical_terms"):
            print(f"  Reference has no technical_terms yet; term recall will be n/a.")
        for row in rows:
            overall = row["overall"]
            print(f"\n  {row['provider']}: overall "
                  f"{'n/a' if overall is None else f'{overall:.3f}'}"
                  f"  (latin ratio {row['latin_ratio']})")
            for key, value in row["components"].items():
                shown = "n/a" if value is None else f"{value:.3f}"
                print(f"     {key:<18} {shown}")
            if row["terms_missed"]:
                print(f"     missed terms: {', '.join(row['terms_missed'][:15])}")
            if row["hallucinated_terms"]:
                print(f"     hallucinated: {', '.join(row['hallucinated_terms'][:15])}")


def cmd_report(args):
    episodes = {e.guid: e for e in fetch_episodes()}
    totals = {}
    for reference_path in sorted(REFERENCE_DIR.glob("*.json")):
        guid = reference_path.stem
        _, rows = _score_one(guid, episodes.get(guid))
        for row in rows:
            entry = totals.setdefault(row["provider"], {"overall": [], "recall": []})
            if row["overall"] is not None:
                entry["overall"].append(row["overall"])
            if row["components"]["term_recall"] is not None:
                entry["recall"].append(row["components"]["term_recall"])

    if not totals:
        raise SystemExit(
            f"Nothing scored yet. Add references to {REFERENCE_DIR} and run transcribe."
        )

    mean = lambda values: sum(values) / len(values) if values else None
    print(f"{'provider':<14}{'windows':>9}{'term recall':>14}{'overall':>10}")
    ranked = sorted(
        totals.items(), key=lambda kv: mean(kv[1]["recall"]) or 0, reverse=True
    )
    for name, entry in ranked:
        recall, overall = mean(entry["recall"]), mean(entry["overall"])
        print(f"{name:<14}{len(entry['overall']):>9}"
              f"{'n/a' if recall is None else f'{recall:>13.3f}'}"
              f"{'n/a' if overall is None else f'{overall:>10.3f}'}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="langtalks.bench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("episodes", help="list episodes in the feed")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_episodes)

    p = sub.add_parser("fetch", help="download episode audio")
    p.add_argument("episodes", nargs="+")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("glossary", help="show the generated keyterms")
    p.add_argument("episodes", nargs="+")
    p.set_defaults(func=cmd_glossary)

    p = sub.add_parser("excerpt", help="cut the benchmark window out of an episode")
    p.add_argument("episodes", nargs="+")
    p.add_argument("--start", type=float, default=480.0)
    p.add_argument("--end", type=float, default=780.0)
    p.set_defaults(func=cmd_excerpt)

    p = sub.add_parser("transcribe", help="run ASR providers over episodes")
    p.add_argument("episodes", nargs="+")
    p.add_argument("--provider", choices=list(providers_mod.PROVIDER_NAMES))
    p.add_argument("--full", action="store_true",
                   help="transcribe the whole episode instead of the excerpt")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("reference", help="scaffold a reference annotation file")
    p.add_argument("episodes", nargs="+")
    p.add_argument("--start", type=float, default=480.0)
    p.add_argument("--end", type=float, default=780.0)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_reference)

    p = sub.add_parser("score", help="score transcripts against references")
    p.add_argument("episodes", nargs="+")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("report", help="comparison table across all references")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
