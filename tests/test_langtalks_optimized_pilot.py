"""Safety and behavior tests for optimized_pilot.py."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langtalks.optimized_pilot import execute, validate, GUID
from langtalks.providers.base import TranscriptResult


class OptimizedPilotSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = Path(self.tmp.name) / "300sec.mp3"
        self.audio.write_bytes(b"stub-audio-data")
        self.reference = {
            "episode_guid": GUID,
            "review_status": "approved",
            "transcript_review_status": "approved",
            "technical_terms": ["NanoClaw", "OpenClaw"],
            "transcript_uncertainties": [],
            "window": {"start": 480, "end": 780},
            "reference_text": "NanoClaw מולטי-טננט",
        }
        self.out = Path(self.tmp.name) / "results"

    @patch("langtalks.optimized_pilot.duration_seconds", return_value=300.0)
    def test_validation_rejects_unapproved_or_wrong_guid(self, _dur):
        with self.assertRaisesRegex(ValueError, "approved-one-shot"):
            validate(self.audio, self.reference, approved=False)

        bad_ref = {**self.reference, "episode_guid": "wrong-guid"}
        with self.assertRaisesRegex(ValueError, "Only episode 71"):
            validate(self.audio, bad_ref, approved=True)

    @patch("langtalks.optimized_pilot.duration_seconds", return_value=500.0)
    def test_validation_rejects_non_300s_duration(self, _dur):
        with self.assertRaisesRegex(ValueError, "non-300-second"):
            validate(self.audio, self.reference, approved=True)

    @patch("langtalks.optimized_pilot.duration_seconds", return_value=300.0)
    def test_no_keys_skips_without_calls(self, _dur):
        with patch.dict("os.environ", {
            "SONIOX_API_KEY": "",
            "GROQ_API_KEY": "",
        }), patch("langtalks.optimized_pilot.get_provider") as mock_get:
            report = execute(self.audio, self.reference, self.out, approved=True)

        mock_get.assert_not_called()
        self.assertLess(report["estimated_usage_total_usd"], 0.05)
        for name in ("soniox", "groq_v3", "groq_turbo"):
            self.assertEqual(report["providers"][name]["status"], "missing_key_no_request")

    @patch("langtalks.optimized_pilot.duration_seconds", return_value=300.0)
    def test_mock_provider_execution_and_caching(self, _dur):
        fake_result = TranscriptResult(
            provider="groq_v3",
            text="NanoClaw עובד",
            tokens=[{"text": "NanoClaw", "start": 5.0, "end": 6.0}],
        )

        class FakeProvider:
            def transcribe(self, audio, terms, prompt):
                return fake_result

        with patch.dict("os.environ", {"GROQ_API_KEY": "fake_key"}), \
             patch("langtalks.optimized_pilot.get_provider", return_value=FakeProvider()):
            report1 = execute(self.audio, self.reference, self.out, approved=True)
            self.assertEqual(report1["providers"]["groq_v3"]["status"], "completed")

            # Second execution should skip cached file
            report2 = execute(self.audio, self.reference, self.out, approved=True)
            self.assertEqual(report2["providers"]["groq_v3"]["status"], "cached_skipped")


if __name__ == "__main__":
    unittest.main()
