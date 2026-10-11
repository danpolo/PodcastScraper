"""Offline Groq adapter tests; no real API requests or API keys required."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from langtalks.providers import available, get_provider
from langtalks.providers.groq import (
    GroqProvider, GroqTurboProvider, MAX_PROMPT_CHARS, MAX_UPLOAD_BYTES,
    glossary_prompt,
)


class GroqProviderTests(unittest.TestCase):
    def test_glossary_prioritizes_terms_deduplicates_and_bounds_prompt(self):
        hint = glossary_prompt(
            ["NanoClaw", "MCP", "nanoclaw", "כלי", "LangGraph"] +
            [f"Term{x:04d}" for x in range(200)]
        )
        self.assertIn("NanoClaw", hint)
        self.assertIn("MCP", hint)
        self.assertNotIn("nanoclaw", hint)
        self.assertNotIn("כלי", hint)
        self.assertLessEqual(len(hint), MAX_PROMPT_CHARS)

    def test_provider_discovery_uses_groq_key(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test"}, clear=True):
            self.assertIn("groq_v3", available())
            self.assertIn("groq_turbo", available())
            self.assertIsInstance(get_provider("groq_turbo"), GroqTurboProvider)
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotIn("groq_v3", available())
            self.assertNotIn("groq_turbo", available())

    def test_v3_sends_glossary_and_preserves_segment_times(self):
        reply = Mock()
        reply.json.return_value = {
            "text": "אנחנו משתמשים ב NanoClaw ו MCP.",
            "language": "he",
            "segments": [
                {"start": 1.5, "end": 3, "text": "אנחנו משתמשים ב "},
                {"start": 3, "end": 6.5, "text": "NanoClaw ו MCP."},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "excerpt.mp3"
            audio.write_bytes(b"fake audio")
            with patch.dict(os.environ, {"GROQ_API_KEY": "secret"}), patch(
                "langtalks.providers.groq.requests.post", return_value=reply
            ) as post:
                result = GroqProvider().transcribe(
                    audio, ["NanoClaw", "MCP"], "A longer context prompt")
        self.assertEqual(result.provider, "groq_v3")
        self.assertEqual(result.tokens[0]["start"], 1.5)
        self.assertEqual(result.tokens[1]["end"], 6.5)
        self.assertIsNone(result.tokens[0]["speaker"])
        self.assertEqual(result.to_dict()["text"], result.text)
        self.assertEqual(post.call_args.kwargs["data"]["language"], "he")
        self.assertEqual(
            post.call_args.kwargs["data"]["model"], "whisper-large-v3")
        self.assertIn("NanoClaw", post.call_args.kwargs["data"]["prompt"])
        self.assertNotIn("A longer context prompt",
                         post.call_args.kwargs["data"]["prompt"])
        reply.raise_for_status.assert_called_once()

    def test_turbo_has_distinct_identity_and_model(self):
        reply = Mock()
        reply.json.return_value = {"text": "MCP", "segments": []}
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "excerpt.mp3"
            audio.write_bytes(b"sound")
            with patch.dict(os.environ, {"GROQ_API_KEY": "secret"}), patch(
                "langtalks.providers.groq.requests.post", return_value=reply
            ) as post:
                result = GroqTurboProvider().transcribe(audio, [], "")
        self.assertEqual(result.provider, "groq_turbo")
        self.assertEqual(result.tokens, [])
        self.assertEqual(
            post.call_args.kwargs["data"]["model"], "whisper-large-v3-turbo")
        self.assertNotIn("prompt", post.call_args.kwargs["data"])

    def test_oversized_upload_fails_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "huge.mp3"
            with audio.open("wb") as handle:
                handle.truncate(MAX_UPLOAD_BYTES + 1)
            with patch("langtalks.providers.groq.requests.post") as post:
                with self.assertRaisesRegex(RuntimeError, "Groq free-tier"):
                    GroqProvider().transcribe(audio, ["MCP"], "")
                post.assert_not_called()

    def test_empty_response_is_error(self):
        reply = Mock()
        reply.json.return_value = {"text": " "}
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "excerpt.mp3"
            audio.write_bytes(b"audio")
            with patch.dict(os.environ, {"GROQ_API_KEY": "secret"}), patch(
                "langtalks.providers.groq.requests.post", return_value=reply
            ):
                with self.assertRaisesRegex(RuntimeError, "no usable text"):
                    GroqProvider().transcribe(audio, [], "")


if __name__ == "__main__":
    unittest.main()
