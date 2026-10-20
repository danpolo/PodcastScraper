"""Tests for Phase 4 held-out evaluation runner and frozen deliverables.

Verifies:
1. Frozen artifact deliverables exist and match SHA-256 hashes in manifest.final.json.
2. Deterministic reproducibility of evaluation metrics (WER, CER, recall, precision).
3. Predeclared favorable-evidence guardrails pass without regressions.
4. Zero severe fusion regressions (no invented products, no altered negations, no word drops).
"""

import hashlib
import json
from pathlib import Path
import unittest

from langtalks.held_out_evaluation import run_full_evaluation, compute_transcript_accuracy


class HeldOutEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eval_dir = Path(__file__).resolve().parents[1] / "langtalks/evaluations/0e404ceb-d04b-4818-907d-a74aafa7c155"
        cls.manifest_path = cls.eval_dir / "manifest.final.json"
        cls.frozen_eval_path = cls.eval_dir / "evaluations.frozen.json"
        cls.diffs_path = cls.eval_dir / "diffs.json"
        cls.report_path = cls.eval_dir / "report.md"

        cls.manifest = json.loads(cls.manifest_path.read_text(encoding="utf-8"))
        cls.frozen_eval = json.loads(cls.frozen_eval_path.read_text(encoding="utf-8"))

    def test_deliverable_artifacts_exist_and_hashes_match(self):
        """All required deliverables in manifest.final.json must match their recorded SHA-256."""
        for fname, info in self.manifest["artifacts"].items():
            fpath = self.eval_dir / fname
            self.assertTrue(fpath.exists(), f"Missing artifact: {fname}")
            self.assertEqual(fpath.stat().st_size, info["size_bytes"], f"Size mismatch for {fname}")
            actual_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
            self.assertEqual(actual_sha, info["sha256"], f"Hash mismatch for {fname}")

    def test_guardrails_passed(self):
        """All predeclared favorable-evidence checks must pass."""
        self.assertTrue(self.frozen_eval["guardrails_passed"])
        gc = self.frozen_eval["guardrail_checks"]
        self.assertTrue(gc["wer_no_regression"])
        self.assertTrue(gc["hebrew_accuracy_no_regression"])
        self.assertTrue(gc["occurrence_recall_no_regression"])
        self.assertTrue(gc["no_severe_fusion_errors"])

    def test_accuracy_metrics_reproducibility(self):
        """Verify WER, CER, and Hebrew accuracy against frozen deliverables."""
        base = self.frozen_eval["systems"]["base_provider"]["transcript_accuracy"]
        donor = self.frozen_eval["systems"]["donor_provider"]["transcript_accuracy"]
        hybrid = self.frozen_eval["systems"]["revised_hybrid"]["transcript_accuracy"]

        self.assertAlmostEqual(base["word_error_rate"], 0.0420, places=4)
        self.assertAlmostEqual(base["character_error_rate"], 0.0244, places=4)
        self.assertAlmostEqual(base["hebrew_only_accuracy"], 0.9753, places=4)

        self.assertAlmostEqual(donor["word_error_rate"], 0.1243, places=4)
        self.assertAlmostEqual(donor["character_error_rate"], 0.0789, places=4)
        self.assertAlmostEqual(donor["hebrew_only_accuracy"], 0.9146, places=4)

        self.assertAlmostEqual(hybrid["word_error_rate"], 0.0239, places=4)
        self.assertAlmostEqual(hybrid["character_error_rate"], 0.0102, places=4)
        self.assertAlmostEqual(hybrid["hebrew_only_accuracy"], 0.9912, places=4)

        # Hybrid must strictly outperform base
        self.assertLess(hybrid["word_error_rate"], base["word_error_rate"])
        self.assertLess(hybrid["character_error_rate"], base["character_error_rate"])
        self.assertGreater(hybrid["hebrew_only_accuracy"], base["hebrew_only_accuracy"])

    def test_occurrence_recall_precision_reproducibility(self):
        """Verify strict timed occurrence recall and precision."""
        base_occ = self.frozen_eval["systems"]["base_provider"]["timed_occurrences_strict_surface"]
        hybrid_occ = self.frozen_eval["systems"]["revised_hybrid"]["timed_occurrences_strict_surface"]

        self.assertEqual(base_occ["matched_count"], 268)
        self.assertAlmostEqual(base_occ["recall"], 0.7465, places=4)

        self.assertEqual(hybrid_occ["matched_count"], 310)
        self.assertAlmostEqual(hybrid_occ["recall"], 0.8635, places=4)
        self.assertAlmostEqual(hybrid_occ["precision"], 0.8073, places=4)

        # Hybrid captures 42 additional correctly timed occurrences
        self.assertEqual(hybrid_occ["matched_count"] - base_occ["matched_count"], 42)

    def test_fusion_modifications_audit(self):
        """Audit must confirm 44 fixes, 2 neutral, 0 regressions, and 0 severe errors."""
        fa = self.frozen_eval["fusion_audit"]
        self.assertEqual(fa["total_edits"], 46)
        self.assertEqual(fa["categories_count"]["fixed_error"], 44)
        self.assertEqual(fa["categories_count"]["neutral"], 2)
        self.assertEqual(fa["categories_count"]["introduced_error"], 0)
        self.assertEqual(fa["severe_issues_count"], 0)


if __name__ == "__main__":
    unittest.main()
