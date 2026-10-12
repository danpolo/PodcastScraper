"""User reviewed LangTalks reference invariants (no cloud services)."""
import json
from pathlib import Path
import unittest

from langtalks.agent_format import apply_reference, from_asr


REF_ROOT = Path(__file__).resolve().parents[1] / "langtalks/reference"
GUID = "74fc0625-0a6b-4ca1-9488-31be7860360d"


class UserReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads(
            (REF_ROOT / "annotations/episode71.user-approved.json").read_text(encoding="utf-8")
        )
        cls.reference = json.loads(
            (REF_ROOT / (GUID + ".json")).read_text(encoding="utf-8")
        )

    def test_all_user_reviewed_evidence_preserved(self):
        self.assertTrue(self.reference["review_status"] == "approved")
        self.assertEqual(len(self.original["verified_occurrences"]), 69)
        self.assertEqual(len(self.reference["verified_occurrences"]), 69)
        self.assertEqual(self.reference["editorial_summary"]["original_distinct_expressions"], 41)
        self.assertEqual(len(self.reference["all_verified_english_expressions"]), 41)
        self.assertEqual(
            sorted(round(x["start"], 4) for x in self.original["verified_occurrences"]),
            sorted(round(x["start"], 4) for x in self.reference["verified_occurrences"]),
        )

    def test_onecli_user_correction_all_six_instances(self):
        occurrences = [
            o for o in self.reference["verified_occurrences"]
            if o.get("canonical") == "OneCLI"
        ]
        self.assertEqual(len(occurrences), 6)
        self.assertTrue(all(x["surface"] == "OneCLI" for x in occurrences))
        self.assertTrue(all(x["asr_observed_surface"] == "Onecli" for x in occurrences))
        self.assertIn("OneCLI", self.reference["technical_terms"])
        self.assertNotIn("CLI", self.reference["technical_terms"])
        self.assertNotIn("Onecli", self.reference["technical_terms"])

    def test_approved_word_doesnt_automatically_verify_editorial_merge(self):
        concepts = self.reference["concept_mentions"]
        self.assertEqual(len(concepts), 63)
        self.assertEqual(sum(x["review_status"] == "verified" for x in concepts), 62)
        merges = [x for x in concepts if x["canonical"] == "HTTP Authorization header"]
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0]["review_status"], "suggested")

    def test_user_draft_preserved_while_semantic_types_filled(self):
        manual = [x for x in self.reference["verified_occurrences"]
                  if x["source_models"] == ["manual"]]
        self.assertTrue(manual)
        self.assertTrue(all(x["kind"] != "other" for x in manual
                            if x["surface"] not in {"use cases"}))
        google = next(x for x in manual if x["surface"] == "Log in with Google")
        self.assertEqual(google["kind"], "technical_practice")
        self.assertEqual(google["canonical"], "Sign in with Google")
        coupled = next(x for x in manual if x["surface"] == "coupled")
        self.assertFalse(coupled["semantic_index_inclusion"])
        self.assertIn("coupled", self.reference["all_verified_english_expressions"])

    def test_approved_reference_never_approves_full_transcript_or_suggested_merge(self):
        doc = from_asr({
            "episode_guid": GUID, "provider": "mock", "source": "excerpt",
            "time_offset": 480, "text": "Hebrew ASR text remains unverified",
            "tokens": [{"text": "Hebrew ASR text remains unverified",
                        "start": 480, "end": 780}],
        })
        updated = apply_reference(doc, self.reference)
        self.assertEqual(updated["status"], "machine_draft")
        self.assertEqual(updated["turns"][0]["review_status"], "suggested")
        self.assertEqual(len(updated["concept_mentions"]), 63)
        self.assertEqual(sum(m["review_status"] == "suggested"
                             for m in updated["concept_mentions"]), 1)
        self.assertEqual(updated["provenance"]["editorial_review"],
                         "terminology_approved_only")


if __name__ == "__main__":
    unittest.main()
