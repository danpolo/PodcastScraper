"""ElevenLabs Scribe v2 batch transcription.

Scribe v2 takes up to 1,000 keyterms, which is the largest glossary budget of
the three candidates. ElevenLabs rates Hebrew as "good" rather than best-tier,
so this is here as a benchmark contender, not a presumed winner.

API shape: POST https://api.elevenlabs.io/v1/speech-to-text (multipart).
"""

import json
import logging
from pathlib import Path

import requests

from .base import Provider, TranscriptResult

logger = logging.getLogger(__name__)

URL = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "scribe_v2"


class ElevenLabsProvider(Provider):
    name = "elevenlabs"
    env_key = "ELEVENLABS_API_KEY"

    def transcribe(self, audio_path: Path, terms: list, prompt: str) -> TranscriptResult:
        logger.info("ElevenLabs: uploading %s", audio_path.name)
        # Scribe accepts up to 1000 keyterms; the glossary is already capped
        # well below that, so send it whole.
        data = {
            "model_id": MODEL,
            "language_code": "heb",
            "diarize": "true",
            "timestamps_granularity": "word",
            "keyterms": json.dumps(terms),
        }
        with audio_path.open("rb") as handle:
            response = requests.post(
                URL,
                headers={"xi-api-key": self.api_key()},
                data=data,
                files={"file": (audio_path.name, handle, "audio/mpeg")},
                timeout=3600,
            )
        response.raise_for_status()
        payload = response.json()

        tokens = [
            {
                "text": word.get("text", ""),
                "start": word.get("start"),
                "end": word.get("end"),
                "speaker": word.get("speaker_id"),
                "confidence": word.get("logprob"),
            }
            for word in payload.get("words", [])
        ]
        return TranscriptResult(
            provider=self.name,
            text=payload.get("text", ""),
            tokens=tokens,
            raw={"language_code": payload.get("language_code")},
        )
