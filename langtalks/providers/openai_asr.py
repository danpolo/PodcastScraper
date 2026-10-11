"""OpenAI gpt-4o-transcribe.

Included as the third contender mainly because its free-text ``prompt`` is the
most direct way to say "keep English terms in Latin script". It has no
diarization on this endpoint, so it scores zero on speaker attribution by
construction — that is expected, not a bug.

The endpoint caps uploads at 25 MB, so full LangTalks episodes (~30 MB) are
rejected. Use this provider on an excerpt, or skip it.
"""

import logging
from pathlib import Path

import requests

from .base import Provider, TranscriptResult

logger = logging.getLogger(__name__)

URL = "https://api.openai.com/v1/audio/transcriptions"
MODEL = "gpt-4o-transcribe"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class OpenAIProvider(Provider):
    name = "openai"
    env_key = "OPENAI_API_KEY"

    def transcribe(self, audio_path: Path, terms: list, prompt: str) -> TranscriptResult:
        size = audio_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            raise RuntimeError(
                f"{audio_path.name} is {size / 1e6:.1f} MB; the OpenAI transcription "
                f"endpoint caps uploads at 25 MB. Benchmark this provider on an excerpt."
            )

        logger.info("OpenAI: uploading %s", audio_path.name)
        with audio_path.open("rb") as handle:
            response = requests.post(
                URL,
                headers={"Authorization": f"Bearer {self.api_key()}"},
                data={
                    "model": MODEL,
                    "language": "he",
                    "prompt": prompt[:2000],
                    "response_format": "json",
                },
                files={"file": (audio_path.name, handle, "audio/mpeg")},
                timeout=3600,
            )
        response.raise_for_status()
        payload = response.json()
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise RuntimeError("OpenAI transcription response is missing text")

        # This endpoint returns text only — no token timings and no speakers.
        return TranscriptResult(
            provider=self.name,
            text=text,
            tokens=[],
            raw={"model": MODEL},
        )
