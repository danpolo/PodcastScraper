"""Soniox async transcription.

Soniox is the primary candidate because it advertises mid-sentence language
switching rather than one language per file, which is the whole problem with
this podcast. The ``context`` field carries the episode glossary.

API shape (docs.soniox.com):
    POST /v1/files                         -> {"id": ...}
    POST /v1/transcriptions                -> {"id": ...}
    GET  /v1/transcriptions/{id}           -> {"status": queued|processing|completed|error}
    GET  /v1/transcriptions/{id}/transcript-> {"text": ..., "tokens": [...]}
"""

import logging
import time
from pathlib import Path

import requests

from .base import Provider, TranscriptResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.soniox.com"
MODEL = "stt-async-v5"
POLL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 3600


class SonioxProvider(Provider):
    name = "soniox"
    env_key = "SONIOX_API_KEY"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key()}"}

    def transcribe(self, audio_path: Path, terms: list, prompt: str) -> TranscriptResult:
        logger.info("Soniox: uploading %s", audio_path.name)
        with audio_path.open("rb") as handle:
            response = requests.post(
                f"{BASE_URL}/v1/files",
                headers=self._headers(),
                files={"file": (audio_path.name, handle, "audio/mpeg")},
                timeout=600,
            )
        response.raise_for_status()
        file_id = response.json()["id"]

        if isinstance(prompt, dict):
            context_data = prompt
        else:
            context_data = {
                "general": [
                    {"key": "domain", "value": "AI software engineering"},
                    {"key": "podcast", "value": "LangTalks"},
                ],
                "text": str(prompt),
                "terms": terms,
            }

        payload = {
            "file_id": file_id,
            "model": MODEL,
            # Constraining to exactly the two languages present stops the model
            # from reaching for a third when a term is unclear.
            "language_hints": ["he", "en"],
            "enable_speaker_diarization": True,
            "enable_language_identification": True,
            "context": context_data,
        }
        response = requests.post(
            f"{BASE_URL}/v1/transcriptions",
            headers=self._headers(),
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        transcription_id = response.json()["id"]
        logger.info("Soniox: transcription %s queued", transcription_id)

        deadline = time.time() + POLL_TIMEOUT_SECONDS
        while True:
            if time.time() > deadline:
                raise TimeoutError(f"Soniox transcription {transcription_id} timed out")
            status_response = requests.get(
                f"{BASE_URL}/v1/transcriptions/{transcription_id}",
                headers=self._headers(),
                timeout=60,
            )
            status_response.raise_for_status()
            status = status_response.json()
            if status.get("status") == "completed":
                break
            if status.get("status") == "error":
                raise RuntimeError(
                    f"Soniox failed: {status.get('error_type')}: {status.get('error_message')}"
                )
            time.sleep(POLL_SECONDS)

        transcript_response = requests.get(
            f"{BASE_URL}/v1/transcriptions/{transcription_id}/transcript",
            headers=self._headers(),
            timeout=120,
        )
        transcript_response.raise_for_status()
        data = transcript_response.json()

        tokens = [
            {
                "text": token.get("text", ""),
                "start": (token.get("start_ms") or 0) / 1000.0,
                "end": (token.get("end_ms") or 0) / 1000.0,
                "speaker": token.get("speaker"),
                "confidence": token.get("confidence"),
            }
            for token in data.get("tokens", [])
        ]
        return TranscriptResult(
            provider=self.name,
            text=data.get("text", ""),
            tokens=tokens,
            raw={"transcription_id": transcription_id},
        )
