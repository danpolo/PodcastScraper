"""Groq Whisper candidates for mixed Hebrew and English technical speech.

Provider names remain distinct so the benchmark caches each model separately.
No model is assumed accurate until scored against human-annotated audio.
"""
import re
from pathlib import Path
import requests
from .base import Provider, TranscriptResult

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# Slightly below Groq's 25 MB free-tier upload limit.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
# Whisper prompt limit is 224 tokens. No tokenizer dependency is introduced;
# constrain character count conservatively and prioritize episode-specific
# glossary terms, which are supplied first by glossary.build.
MAX_PROMPT_CHARS = 240
PROMPT_PREFIX = "פודקאסט בעברית על AI ותוכנה. מונחים באנגלית: "


def glossary_prompt(terms: list) -> str:
    """Short context hint, not an instruction to rewrite the model's output."""
    included, seen = [], set()
    for raw in terms:
        term = str(raw).strip()
        key = term.casefold()
        if not term or key in seen or not re.search(r"[A-Za-z]", term):
            continue
        if len(term) > 60:
            continue
        proposed = PROMPT_PREFIX + ", ".join(included + [term])
        if len(proposed) > MAX_PROMPT_CHARS:
            break
        included.append(term)
        seen.add(key)
    return PROMPT_PREFIX + ", ".join(included) if included else ""


class GroqProvider(Provider):
    name = "groq_v3"
    env_key = "GROQ_API_KEY"
    model = "whisper-large-v3"

    def transcribe(self, audio_path: Path, terms: list, prompt: str) -> TranscriptResult:
        size = audio_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            raise RuntimeError(
                f"{audio_path.name} is {size / 1e6:.1f} MB, above the conservative "
                "Groq free-tier limit. Use a benchmark excerpt or chunk the audio."
            )
        data = {
            "model": self.model,
            "language": "he",
            "response_format": "verbose_json",
        }
        hint = glossary_prompt(terms)
        if hint:
            data["prompt"] = hint
        with audio_path.open("rb") as handle:
            response = requests.post(
                URL,
                headers={"Authorization": f"Bearer {self.api_key()}"},
                data=data,
                files={"file": (audio_path.name, handle, "audio/mpeg")},
                timeout=3600,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Groq transcription returned a non-object response")
        transcript = payload.get("text")
        if not isinstance(transcript, str) or not transcript.strip():
            raise RuntimeError("Groq transcription response has no usable text")
        tokens = []
        for segment in payload.get("segments") or []:
            if not isinstance(segment, dict) or not segment.get("text"):
                continue
            start, end = segment.get("start"), segment.get("end")
            if start is None or end is None:
                continue
            tokens.append({
                "text": segment["text"],
                "start": float(start),
                "end": float(end),
                "speaker": None,
                "confidence": None,
            })
        return TranscriptResult(
            provider=self.name,
            text=transcript,
            tokens=tokens,
            raw={"model": self.model, "language": payload.get("language")},
        )


class GroqTurboProvider(GroqProvider):
    name = "groq_turbo"
    model = "whisper-large-v3-turbo"
