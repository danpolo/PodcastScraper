"""Shared provider contract."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptResult:
    provider: str
    text: str
    tokens: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "text": self.text,
            "tokens": self.tokens,
        }


class Provider:
    """Base class. Subclasses set ``name`` and ``env_key`` and implement transcribe()."""

    name = ""
    env_key = ""

    def is_configured(self) -> bool:
        return bool(os.getenv(self.env_key))

    def api_key(self) -> str:
        key = os.getenv(self.env_key)
        if not key:
            raise RuntimeError(
                f"{self.name} needs {self.env_key} in the environment "
                f"(see langtalks/README.md)"
            )
        return key

    def transcribe(self, audio_path: Path, terms: list, prompt: str) -> TranscriptResult:
        raise NotImplementedError


def window_text(result, start_seconds: float, end_seconds: float) -> str:
    """Transcript text for a time window, used to score one annotated stretch.

    Falls back to the full text when a provider returned no token timings —
    better to score something than to silently report an empty window.
    """
    tokens = result.tokens if hasattr(result, "tokens") else result.get("tokens", [])
    if not tokens:
        return result.text if hasattr(result, "text") else result.get("text", "")
    kept = [
        token["text"]
        for token in tokens
        if token.get("start") is not None and start_seconds <= token["start"] < end_seconds
    ]
    return "".join(kept).strip()
