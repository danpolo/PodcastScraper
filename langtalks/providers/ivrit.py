"""ivrit.ai Hebrew Whisper, via a RunPod serverless endpoint.

This is the cheapest contender (~$0.03 per transcribed hour) and the only one
with direct public evidence on the actual LangTalks archive: a developer
transcribed the first 65 episodes with it and reported that it handled the
podcast's dense technical Hebrew and its switches into English tool names
cleanly. That is the strongest kind of evidence available — the right audio,
not a generic Hebrew benchmark — and it is why this model is a contender rather
than a footnote.

The countervailing evidence is mechanistic, and it is a hypothesis this
benchmark exists to test rather than a conclusion. The large-v3 fine-tune's
model card states that language detection "has been degraded during training"
and that the model is "intended for mostly-hebrew audio transcription", and its
~5,050 training hours are roughly 93% Knesset parliamentary proceedings —
a domain with almost no English AI-engineering vocabulary. A Hebrew specialist
trained mostly on Hebrew political speech is a plausible candidate to
transliterate exactly the terms this project cares about.

Both claims cannot be settled by argument, so: measure it.

Fairness note: faster-whisper accepts ``initial_prompt`` for vocabulary
biasing, and the worker forwards unknown ``transcribe_args`` straight into it.
The episode glossary is therefore supplied here too, so this provider is not
handicapped relative to the ones with explicit keyterm parameters.

Setup: deploy https://github.com/ivrit-ai/runpod-serverless from the RunPod hub,
then set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID.
"""

import base64
import logging
import os
import time
from pathlib import Path

import requests

from .base import Provider, TranscriptResult

logger = logging.getLogger(__name__)

MODEL = "ivrit-ai/whisper-large-v3-ct2"
# stable-whisper is the core engine that supports diarization; faster-whisper
# is quicker but returns no speaker labels.
CORE_ENGINE = "stable-whisper"

# RunPod rejects request bodies over 10 MB, and base64 inflates by 4/3, so the
# raw audio has to stay under ~7 MB. Benchmark windows are excerpts anyway.
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 7 * 1024 * 1024

POLL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 3600
# Whisper truncates initial_prompt to the last 224 tokens; keep it short enough
# that the episode-specific terms at the front are not the part discarded.
MAX_PROMPT_CHARS = 800


class IvritProvider(Provider):
    name = "ivrit"
    env_key = "RUNPOD_API_KEY"

    def is_configured(self) -> bool:
        return bool(os.getenv(self.env_key) and os.getenv("RUNPOD_ENDPOINT_ID"))

    def _base_url(self) -> str:
        endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID")
        if not endpoint_id:
            raise RuntimeError(
                "ivrit needs RUNPOD_ENDPOINT_ID as well as RUNPOD_API_KEY "
                "(see langtalks/README.md)"
            )
        return f"https://api.runpod.ai/v2/{endpoint_id}"

    def transcribe(self, audio_path: Path, terms: list, prompt: str) -> TranscriptResult:
        size = audio_path.stat().st_size
        if size > MAX_AUDIO_BYTES:
            raise RuntimeError(
                f"{audio_path.name} is {size / 1e6:.1f} MB; RunPod caps the request "
                f"body at 10 MB and base64 inflates by 4/3. Cut a shorter window: "
                f"python -m langtalks.bench excerpt <episode> --start S --end E"
            )

        blob = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        # The glossary goes in as a vocabulary bias, mirroring what the other
        # providers get from their keyterm parameters.
        initial_prompt = ", ".join(terms)[:MAX_PROMPT_CHARS]

        payload = {
            "input": {
                "type": "blob",
                "model": MODEL,
                "engine": CORE_ENGINE,
                "streaming": False,
                "transcribe_args": {
                    # The model card is explicit that the language token must be
                    # set rather than detected, since detection was degraded by
                    # the Hebrew fine-tune.
                    "language": "he",
                    "diarize": True,
                    "output_options": {"word_timestamps": True, "extra_data": False},
                    "initial_prompt": initial_prompt,
                    "blob": blob,
                },
            }
        }

        headers = {"Authorization": f"Bearer {self.api_key()}"}
        logger.info("ivrit: submitting %s (%.1f MB)", audio_path.name, size / 1e6)
        response = requests.post(
            f"{self._base_url()}/run", headers=headers, json=payload, timeout=300
        )
        response.raise_for_status()
        job_id = response.json()["id"]
        logger.info("ivrit: job %s queued", job_id)

        deadline = time.time() + POLL_TIMEOUT_SECONDS
        while True:
            if time.time() > deadline:
                raise TimeoutError(f"ivrit job {job_id} timed out")
            status_response = requests.get(
                f"{self._base_url()}/status/{job_id}", headers=headers, timeout=60
            )
            status_response.raise_for_status()
            body = status_response.json()
            status = body.get("status")
            if status == "COMPLETED":
                break
            if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                raise RuntimeError(f"ivrit job {job_id} {status}: {body.get('error')}")
            time.sleep(POLL_SECONDS)

        segments = _flatten_segments(body.get("output"))
        tokens = []
        for segment in segments:
            speakers = segment.get("speakers") or []
            speaker = speakers[0] if speakers else None
            words = segment.get("words") or []
            if words:
                for word in words:
                    tokens.append(
                        {
                            "text": word.get("word", ""),
                            "start": word.get("start"),
                            "end": word.get("end"),
                            "speaker": word.get("speaker") or speaker,
                            "confidence": word.get("probability"),
                        }
                    )
            else:
                tokens.append(
                    {
                        "text": segment.get("text", ""),
                        "start": segment.get("start"),
                        "end": segment.get("end"),
                        "speaker": speaker,
                        "confidence": None,
                    }
                )

        text = "".join(segment.get("text", "") for segment in segments).strip()
        return TranscriptResult(
            provider=self.name,
            text=text,
            tokens=tokens,
            raw={"job_id": job_id, "model": MODEL, "engine": CORE_ENGINE},
        )


def _flatten_segments(output) -> list:
    """Dig the segment dicts out of RunPod's aggregated generator output.

    The worker is a generator handler with ``return_aggregate_stream``, so the
    shape is a list of yielded items; the non-streaming path yields a single
    ``{"result": [batch, ...]}`` where each batch is a list of
    ``{"type": "segments"|"progress", "data": [segment, ...]}``.
    """
    if not output:
        return []
    if isinstance(output, dict):
        output = [output]

    segments = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if "error" in item:
            raise RuntimeError(f"ivrit worker error: {item['error']}")
        for batch in item.get("result") or []:
            entries = batch if isinstance(batch, list) else [batch]
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("type") != "segments":
                    continue
                segments.extend(entry.get("data") or [])
    return segments
