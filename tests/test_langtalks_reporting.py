"""Provisional model metrics must not be promoted to a verified leaderboard."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from langtalks import bench


class ReportTests(unittest.TestCase):
    def _report(self, review_status):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "guid.json").write_text(
                json.dumps({"review_status": review_status}), encoding="utf-8")
            row = {
                "provider": "groq_v3", "overall": 0.95,
                "components": {"term_recall": 1.0},
            }
            out = io.StringIO()
            with patch.object(bench, "REFERENCE_DIR", root), patch.object(
                bench, "fetch_episodes", return_value=[]
            ), patch.object(
                bench, "_score_one", return_value=({}, [row])
            ), redirect_stdout(out):
                bench.cmd_report(None)
            return out.getvalue()

    def test_unapproved_model_has_no_verified_rank(self):
        report = self._report("pending")
        self.assertIn("No human-approved references", report)
        self.assertIn("n/a", report)
        self.assertNotIn("0.950", report)

    def test_approved_model_can_receive_metrics(self):
        report = self._report("approved")
        self.assertNotIn("No human-approved references", report)
        self.assertIn("1.000", report)
        self.assertIn("0.950", report)


if __name__ == "__main__":
    unittest.main()
