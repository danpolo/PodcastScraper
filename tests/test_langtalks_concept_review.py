"""Review quality: compound concepts are independent of ASR token boundaries."""
import unittest

from langtalks.concept_review import build


def item(term, a, b, models=None):
    return {"term": term, "seen_in": models or ["m1"],
            "occurrences": [{"start": a, "end": b, "text": term,
                             "sources": models or ["m1"]}]}


class ConceptReviewTests(unittest.TestCase):
    def test_code_review_grouped_not_two_duplicate_words(self):
        source = {"episode_guid": "ep", "window": {"start": 480, "end": 780},
                  "suggested_terms": [
                      item("code", 489.4, 489.58),
                      item("review", 489.58, 489.86),
                      item("NanoClaw", 504, 505)]}
        draft = build(source)
        names = [g["term"] for g in draft["suggested_terms"]]
        self.assertIn("code review", names)
        self.assertNotIn("code", names)
        self.assertNotIn("review", names)
        self.assertIn("NanoClaw", names)
        self.assertEqual(next(g for g in draft["suggested_terms"]
                              if g["term"] == "code review")["kind"],
                         "technical_practice")
        self.assertTrue(draft["draft_only"])

    def test_managed_hosted_version_keeps_surface_different_from_concept(self):
        draft = build({"suggested_terms": [
            item("managed", 751.33, 752.29),
            item("hosted", 752.30, 752.93),
            item("version", 753.00, 753.27)]})
        m = next(g for g in draft["suggested_terms"]
                 if g["term"] == "managed hosted version")
        self.assertEqual(m["canonical"], "managed hosting")
        self.assertEqual(m["surface"], "managed hosted version")
        self.assertEqual(m["review_status"], "needs_review")
        self.assertGreater(m["occurrences"][0]["end"],
                           m["occurrences"][0]["start"])
        self.assertEqual(m["kind"], "descriptive_concept")

    def test_missing_word_never_invents_compound(self):
        draft = build({"suggested_terms": [
            item("managed", 751.3, 751.9),
            item("version", 753, 753.3)]})
        self.assertNotIn("managed hosted version",
                         [g["term"] for g in draft["suggested_terms"]])

    def test_far_apart_terms_not_merged(self):
        draft = build({"suggested_terms": [
            item("code", 490, 490.2),
            item("review", 520, 520.2)]})
        self.assertNotIn("code review",
                         [g["term"] for g in draft["suggested_terms"]])

    def test_no_auto_approval(self):
        draft = build({"suggested_terms": [item("NanoClaw", 500, 501)]})
        self.assertNotEqual(draft["review_status"], "approved")
        self.assertFalse(any(x.get("state") == "confirmed"
                             for g in draft["suggested_terms"]
                             for x in g["occurrences"]))


if __name__ == "__main__":
    unittest.main()
