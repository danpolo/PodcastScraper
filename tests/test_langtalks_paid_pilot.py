"""Guard the one-time paid pilot: no hidden retries or unapproved audio."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langtalks.paid_pilot import execute, validate
from langtalks.providers.base import TranscriptResult


GUID = "74fc0625-0a6b-4ca1-9488-31be7860360d"


class PaidPilotSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = Path(self.tmp.name) / "300sec.mp3"
        self.audio.write_bytes(b"stub-audio-for-mocked-duration")
        self.reference = {
            "episode_guid": GUID, "review_status": "approved",
            "transcript_review_status": "approved",
            "technical_terms": ["OneCLI", "Hermes"],
            "transcript_uncertainties": [],
            "window": {"start": 480, "end": 780},
            "reference_text": "OneCLI Hermes בruntime",
        }
        self.out = Path(self.tmp.name) / "results"

    @patch("langtalks.paid_pilot.duration_seconds", return_value=300.0)
    def test_no_keys_makes_no_provider_calls(self, duration):
        with patch.dict("os.environ", {
            "SONIOX_API_KEY": "", "GROQ_API_KEY": ""
        }), patch("langtalks.paid_pilot.get_provider") as get:
            report = execute(self.audio, self.reference, self.out, approved=True)
        get.assert_not_called()
        self.assertLess(report["estimated_usage_total_usd"], 0.05)
        self.assertEqual(
            [r["status"] for r in report["providers"].values()],
            ["missing_key_no_request", "missing_key_no_request"],
        )

    @patch("langtalks.paid_pilot.duration_seconds", return_value=300.0)
    def test_reject_full_episode_and_unapproved_requests_before_api(self, duration):
        with self.assertRaisesRegex(ValueError, "approved"):
            validate(self.audio, self.reference, False)
        with self.assertRaisesRegex(ValueError, "episode 71"):
            validate(self.audio, {**self.reference, "episode_guid": "wrong"}, True)
        with patch("langtalks.paid_pilot.duration_seconds", return_value=610.0):
            with self.assertRaisesRegex(ValueError, "non-300"):
                validate(self.audio, self.reference, True)

    @patch("langtalks.paid_pilot.duration_seconds", return_value=300.0)
    def test_one_provider_one_request_and_second_run_is_cached(self, duration):
        fake = TranscriptResult(
            provider="groq_v3", text="OneCLI עובד",
            tokens=[{"text": "OneCLI", "start": 6.0, "end": 7.0}],
        )
        class Provider:
            calls = 0
            def transcribe(self, *args):
                self.calls += 1
                return fake
        provider = Provider()
        with patch.dict("os.environ", {
            "GROQ_API_KEY": "test-only-not-real", "SONIOX_API_KEY": ""
        }), patch("langtalks.paid_pilot.get_provider", return_value=provider):
            first = execute(self.audio, self.reference, self.out, approved=True)
            second = execute(self.audio, self.reference, self.out, approved=True)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(first["providers"]["groq_v3"]["status"], "completed")
        self.assertEqual(second["providers"]["groq_v3"]["status"], "cached_skipped")
        dest = next(self.out.glob("*.groq_v3.json"))
        contents = json.loads(dest.read_text())
        self.assertEqual(contents["tokens"][0]["start"], 486)
        self.assertNotIn("test-only-not-real", dest.read_text())

    @patch("langtalks.paid_pilot.duration_seconds", return_value=300.0)
    def test_provider_error_does_not_retry(self, duration):
        class Fail:
            calls = 0
            def transcribe(self, *args):
                self.calls += 1
                raise RuntimeError("pretend denied")
        provider = Fail()
        with patch.dict("os.environ", {
            "GROQ_API_KEY": "test-not-real", "SONIOX_API_KEY": ""
        }), patch("langtalks.paid_pilot.get_provider", return_value=provider):
            report = execute(self.audio, self.reference, self.out, approved=True)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            report["providers"]["groq_v3"]["status"], "failed_no_automatic_retry"
        )
        self.assertTrue(report["providers"]["groq_v3"]["possible_charge"])


if __name__ == "__main__":
    unittest.main()
