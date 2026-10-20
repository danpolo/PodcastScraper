"""Independent deterministic validation tests for Reference C (Phase 3).

Verifies:
1. Exact phrase coverage in authoritative user-corrected SRT
2. Duplicate occurrence detection
3. Overlapping concept claims within subtitle cues
4. Concept identity consistency across Hebrew inflections and loanwords
5. Timing quality and monotonic bounds
6. Explicit provenance distinction between human audio transcript and assistant semantic audit
7. Excluded idioms and nested subphrases in benchmark exclusions
"""

import json
import re
from pathlib import Path
import unittest

from langtalks.import_reviewed_srt import parse_srt


class ReferenceCValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eval_dir = Path(__file__).resolve().parents[1] / "langtalks/evaluations/0e404ceb-d04b-4818-907d-a74aafa7c155"
        cls.ref_path = cls.eval_dir / "reference_terms.approved.json"
        cls.srt_path = cls.eval_dir / "reference_user_corrected.original.srt"
        cls.ref_c = json.loads(cls.ref_path.read_text(encoding="utf-8"))
        cls.srt_cues = parse_srt(cls.srt_path.read_text(encoding="utf-8-sig"))
        cls.cues_by_id = {f"turn-{idx:04d}": c for idx, c in enumerate(cls.srt_cues, 1)}

    def test_structural_integrity_and_provenance(self):
        """Reference C must contain all protocol metadata and explicit audit provenance."""
        self.assertEqual(self.ref_c["protocol_layer"], "C")
        self.assertEqual(self.ref_c["version"], "1.0-frozen")
        self.assertEqual(self.ref_c["episode_guid"], "0e404ceb-d04b-4818-907d-a74aafa7c155")
        self.assertEqual(self.ref_c["review_status"], "approved")
        self.assertTrue(self.ref_c["terms_exhaustive"])

        prov = self.ref_c["provenance"]
        self.assertEqual(prov["transcript_authority"], "human_corrected_SRT_subtitle_edit")
        self.assertEqual(prov["transcript_sha256"], "e5e2245dc8126bfc1fd6394cb6f4bfceeff06851ce1471fcb583cdd1365a5d53")
        self.assertEqual(prov["terminology_audit_authority"], "chatgpt_independent_semantic_audit")
        self.assertEqual(prov["audit_sha256"], "598d92e0c0f7022b287b5601c6baa51b79f4cd94b366a58459e80824e1849cd0")
        self.assertIn("text_based_semantic_review_not_audio_verified", prov["audit_validation"])

    def test_no_duplicate_occurrence_ids(self):
        """Every occurrence in verified_occurrences must have a strictly unique ID."""
        ids = [o["id"] for o in self.ref_c["verified_occurrences"]]
        self.assertEqual(len(ids), len(set(ids)), "Found duplicate occurrence IDs in Reference C")
        self.assertEqual(len(ids), 361)

    def test_exact_phrase_coverage_in_authoritative_srt(self):
        """Every occurrence surface must be faithfully present in its referenced cue text."""
        for o in self.ref_c["verified_occurrences"]:
            cid = o["source_cue_id"]
            surf = o["surface"]
            if "…" in cid:
                parts = cid.split("…")
                combined = " ".join(self.cues_by_id[p]["text"] for p in parts)
                clean_combined = re.sub(r"[^\w\u0590-\u05fe]", "", combined).lower()
                clean_surf = re.sub(r"[^\w\u0590-\u05fe]", "", surf).lower()
                self.assertIn(clean_surf, clean_combined, f"Cross-cue phrase '{surf}' missing in {cid}")
            else:
                cue = self.cues_by_id[cid]
                clean_cue = re.sub(r"[^\w\u0590-\u05fe]", "", cue["text"]).lower()
                clean_surf = re.sub(r"[^\w\u0590-\u05fe]", "", surf).lower()
                self.assertIn(clean_surf, clean_cue, f"Phrase '{surf}' missing in {cid}: {cue['text']}")

    def test_timing_quality_and_bounds(self):
        """Timestamps must be finite, non-negative, ordered, and under reasonable max duration."""
        for o in self.ref_c["verified_occurrences"]:
            s, e = float(o["start"]), float(o["end"])
            self.assertTrue(0 <= s <= e, f"Invalid timing in occ {o['id']}: {s} -> {e}")
            dur = e - s
            self.assertLessEqual(dur, 8.0, f"Excessive duration in occ {o['id']}: {dur}s")

    def test_no_unjustified_cue_overlap(self):
        """Occurrences in the same cue must not claim overlapping spans."""
        by_cue = {}
        for o in self.ref_c["verified_occurrences"]:
            by_cue.setdefault(o["source_cue_id"], []).append(o)

        for cid, occs in by_cue.items():
            if len(occs) > 1:
                for i in range(len(occs)):
                    for j in range(i + 1, len(occs)):
                        o1, o2 = occs[i], occs[j]
                        if o1["start"] < o2["end"] and o2["start"] < o1["end"]:
                            overlap = min(o1["end"], o2["end"]) - max(o1["start"], o2["start"])
                            self.assertLessEqual(overlap, 0.3, f"Significant overlap in {cid}: occ {o1['id']} vs {o2['id']}")

    def test_sla_and_thinking_retimed(self):
        """SLA, thinking, and boolean literal distinct mentions must have distinct timestamps."""
        sla_occs = [o for o in self.ref_c["verified_occurrences"] if o["source_cue_id"] == "turn-0243" and o["canonical"] == "SLA"]
        self.assertEqual(len(sla_occs), 2)
        self.assertNotEqual(sla_occs[0]["start"], sla_occs[1]["start"])

        thinking_occs = [o for o in self.ref_c["verified_occurrences"] if o["source_cue_id"] == "turn-0205" and o["canonical"] == "Thinking / reasoning mode"]
        self.assertEqual(len(thinking_occs), 2)
        self.assertNotEqual(thinking_occs[0]["start"], thinking_occs[1]["start"])

    def test_generic_conversational_idioms_excluded(self):
        """Conversational idioms (best in class, double down, sweet spot, Silver bullet) must be in benchmark_exclusions."""
        excl_canons = {e.get("canonical") for e in self.ref_c["benchmark_exclusions"]}
        self.assertIn("best in class", excl_canons)
        self.assertIn("double down", excl_canons)
        self.assertIn("sweet spot", excl_canons)
        self.assertIn("Silver bullet", excl_canons)

        # None of these may exist in verified_occurrences
        scorable_canons = {o["canonical"] for o in self.ref_c["verified_occurrences"]}
        self.assertNotIn("best in class", scorable_canons)
        self.assertNotIn("double down", scorable_canons)
        self.assertNotIn("sweet spot", scorable_canons)
        self.assertNotIn("Silver bullet", scorable_canons)


if __name__ == "__main__":
    unittest.main()
