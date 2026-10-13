"""Execute Soniox Async V5 transcription on Episode 74 held-out audio."""
import json
import logging
import os
import sys
from pathlib import Path

from .feed import fetch_episodes, download_audio
from .providers.soniox import SonioxProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("soniox_held_out")

GUID = "0e404ceb-d04b-4818-907d-a74aafa7c155"


def main():
    repo_root = Path(__file__).resolve().parent.parent
    eval_dir = repo_root / "langtalks" / "evaluations" / GUID
    glossary_file = eval_dir / "engine_glossary.original.json"
    if not glossary_file.exists():
        logger.error("Dataset A missing at %s", glossary_file)
        sys.exit(1)

    glossary_data = json.loads(glossary_file.read_text(encoding="utf-8"))
    terms = glossary_data["ordered_terms"]
    soniox_prompt = glossary_data["inputs_by_provider"]["soniox"]

    episodes = fetch_episodes()
    ep = next((e for e in episodes if e.guid == GUID or e.number == 74), None)
    if not ep:
        logger.error("Episode %s not found in feed", GUID)
        sys.exit(1)

    audio_dir = repo_root / "langtalks" / "out" / "audio"
    audio_path = download_audio(ep, audio_dir)
    logger.info("Audio ready at %s (%d bytes)", audio_path, audio_path.stat().st_size)

    provider = SonioxProvider()
    if not provider.is_configured():
        logger.error("SONIOX_API_KEY not configured in environment")
        sys.exit(1)

    logger.info("Submitting %s to Soniox Async V5 API...", ep.title)
    result = provider.transcribe(audio_path, terms, soniox_prompt)
    logger.info("Soniox transcription completed! Tokens count: %d", len(result.tokens))

    out_file = eval_dir / "provider_soniox.original.json"
    payload = {
        "provider": "soniox",
        "model": "stt-async-v5",
        "source": "full",
        "episode_guid": GUID,
        "episode_title": ep.title,
        "time_offset": 0.0,
        "text": result.text,
        "tokens": result.tokens,
        "raw": result.raw,
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved Soniox transcript to %s", out_file)


if __name__ == "__main__":
    main()
