import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from langtalks.feed import fetch_episodes
from langtalks.modal_ivrit import app, run_optimized_ivrit_l4
from langtalks import glossary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("transcribe_ep74_modal")

GUID = "0e404ceb-d04b-4818-907d-a74aafa7c155"


def main():
    eps = fetch_episodes()
    ep = next(e for e in eps if e.guid == GUID or e.number == 74)
    prompt = glossary.initial_prompt_for_ivrit(ep)

    audio_path = repo_root / "langtalks" / "out" / "audio" / f"{GUID}.mp3"
    audio_bytes = audio_path.read_bytes()
    logger.info("Transcribing %s (%.2f MB) via Modal L4 GPU...", ep.title, len(audio_bytes) / 1e6)

    with app.run():
        res = run_optimized_ivrit_l4.remote(audio_bytes, prompt, time_offset=0.0)

    logger.info("Modal L4 finished! Tokens count: %d", len(res.get("words", [])))
    logger.info("Total compute time: %.2f s, cost: $%.5f", res.get("total_compute_s", 0), res.get("cost_usd", 0))

    eval_dir = repo_root / "langtalks" / "evaluations" / GUID
    eval_dir.mkdir(parents=True, exist_ok=True)
    out_file = eval_dir / "provider_ivrit.original.json"

    payload = {
        "provider": "modal_ivrit_l4",
        "source": "full",
        "episode_guid": ep.guid,
        "episode_number": ep.number,
        "episode_title": ep.title,
        "time_offset": 0.0,
        "model": "ivrit-ai/whisper-large-v3-turbo-ct2",
        "initial_prompt": prompt,
        "text": res["full_text"],
        "tokens": res["words"],
        "benchmark_metadata": {k: v for k, v in res.items() if k not in ("words", "full_text")},
    }

    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved immutable base transcript to %s", out_file)


if __name__ == "__main__":
    main()
