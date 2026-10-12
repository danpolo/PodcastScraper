"""Groq Whisper candidates for mixed Hebrew and English technical speech.

Provider names remain distinct so the benchmark caches each model separately.
No model is assumed accurate until scored against human-annotated audio.
"""
import re
from pathlib import Path
import requests
from .base import Provider, TranscriptResult

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# Slightly below Groq's 25 MB upload limit.
MAX_UPLOAD_BYTES = 24_000_000
# Whisper prompt limit is 224 tokens. Keeping characters conservatively bounded
# (~350 chars) maximizes vocabulary density while avoiding truncation.
MAX_PROMPT_CHARS = 350
# Clean vocabulary prefix; avoids instructional sentences that induce Whisper
# hallucination loops during silent audio passages.
PROMPT_PREFIX = "LangTalks terminology: "


def glossary_prompt(terms: list, prefix: str = PROMPT_PREFIX, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """Short context hint, not an instruction to rewrite the model's output."""
    included, seen = [], set()
    for raw in terms:
        term = str(raw).strip()
        key = term.casefold()
        if not term or key in seen or not re.search(r"[A-Za-z]", term):
            continue
        if len(term) > 60:
            continue
        proposed = prefix + ", ".join(included + [term])
        if len(proposed) > max_chars:
            break
        included.append(term)
        seen.add(key)
    return prefix + ", ".join(included) if included else ""


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
            "temperature": "0.0",
            "timestamp_granularities[]": ["word", "segment"],
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
        words = payload.get("words")
        if words and isinstance(words, list):
            for word_info in words:
                if not isinstance(word_info, dict) or not word_info.get("word"):
                    continue
                start, end = word_info.get("start"), word_info.get("end")
                if start is None or end is None:
                    continue
                tokens.append({
                    "text": word_info["word"],
                    "start": float(start),
                    "end": float(end),
                    "speaker": None,
                    "confidence": word_info.get("probability"),
                })
        else:
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
