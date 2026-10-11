"""ASR provider adapters.

Every adapter takes an audio file plus a keyterm glossary and returns the same
shape, so the scorer does not care which service produced a transcript:

    {
        "provider": "soniox",
        "text": "<full transcript>",
        "tokens": [{"text": ..., "start": <sec>, "end": <sec>,
                    "speaker": <str|None>, "confidence": <float|None>}, ...],
    }

Tokens carry seconds (not ms) because the benchmark scores a time window and
mixing units across providers is an easy way to silently mis-score.
"""

from .base import Provider, TranscriptResult, window_text

__all__ = ["Provider", "TranscriptResult", "window_text", "get_provider", "available"]


def get_provider(name: str) -> Provider:
    if name == "soniox":
        from .soniox import SonioxProvider

        return SonioxProvider()
    if name == "elevenlabs":
        from .elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider()
    if name == "openai":
        from .openai_asr import OpenAIProvider

        return OpenAIProvider()
    if name == "ivrit":
        from .ivrit import IvritProvider

        return IvritProvider()
    raise ValueError(f"Unknown provider: {name}")


PROVIDER_NAMES = ("soniox", "elevenlabs", "openai", "ivrit")


def available() -> list:
    """Providers whose API key is present in the environment."""
    names = []
    for name in PROVIDER_NAMES:
        try:
            if get_provider(name).is_configured():
                names.append(name)
        except Exception:
            pass
    return names
