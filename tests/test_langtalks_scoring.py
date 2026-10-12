"""Code-switch metric regression tests."""
import unittest

from langtalks.score import score, term_recall, timed_term_recall


class ScoringTests(unittest.TestCase):
    def test_latin_term_boundaries_ignore_longer_product_names(self):
        recall, found, missed = term_recall(
            "agentic behavior with Agents", ["agent", "MCP"])
        self.assertEqual(recall, 0)
        self.assertEqual(found, [])
        self.assertEqual(missed, ["agent", "MCP"])

    def test_hebrew_prefix_before_latin_acronym_is_valid(self):
        recall, found, missed = term_recall("עובדים בMCP ולמדנו LangGraph",
                                            ["MCP", "LangGraph"])
        self.assertEqual(recall, 1)
        self.assertEqual(len(found), 2)
        self.assertEqual(missed, [])

    def test_phrases_scored_by_spoken_words_not_semantic_alias(self):
        spoken = ["managed hosted version"]
        self.assertEqual(term_recall("יש גם managed hosted version", spoken)[0], 1)
        self.assertEqual(term_recall("יש גם managed hosting", spoken)[0], 0)

    def test_timed_occurrence_recall_catches_missing_repeat_mentions(self):
        ref = {
            "technical_terms": ["OneCLI"],
            "verified_occurrences": [
                {"surface": "OneCLI", "start": 600, "end": 601,
                 "review_status": "verified"},
                {"surface": "OneCLI", "start": 610, "end": 611,
                 "review_status": "verified"},
                {"surface": "OneCLI", "start": 620, "end": 621,
                 "review_status": "verified"},
            ],
        }
        tokens = [
            {"text": " OneCLI", "start": 600, "end": 601},
            {"text": " CLI", "start": 610, "end": 611},
            {"text": " another", "start": 615, "end": 616},
            {"text": " OneCLI", "start": 620, "end": 621},
        ]
        self.assertEqual(term_recall("OneCLI CLI OneCLI", ["OneCLI"])[0], 1.0)
        result = timed_term_recall(tokens, ref)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["missed"], [{"term": "OneCLI", "at_s": 610.0}])
        self.assertTrue(result["diagnostic_only"])
        self.assertEqual(score("OneCLI CLI OneCLI", tokens, ref)["timed_term_recall"]["matched"], 2)

    def test_no_false_exact_timing_for_coarse_paragraph_segments(self):
        ref = {
            "technical_terms": ["OneCLI"],
            "verified_occurrences": [
                {"surface": "OneCLI", "start": 600, "end": 601,
                 "review_status": "verified"},
            ],
        }
        self.assertIsNone(timed_term_recall([
            {"text": "OneCLI", "start": 590, "end": 620},
        ], ref))

    def test_partial_reference_cannot_prove_hallucinations(self):
        result = score("LangGraph NanoClaw", [], {
            "technical_terms": ["LangGraph"], "review_status": "draft",
        }, ["LangGraph", "NanoClaw"])
        self.assertIsNone(result["components"]["term_precision"])
        self.assertEqual(result["hallucinated_terms"], [])
        self.assertEqual(result["components"]["term_recall"], 1)

    def test_precision_uses_approved_spoken_words_outside_semantic_index(self):
        ref = {
            "review_status": "approved", "terms_exhaustive": True,
            "technical_terms": ["OneCLI"],
            "all_verified_english_expressions": ["OneCLI", "agent", "Auth"],
            "verified_occurrences": [
                {"surface": "OneCLI", "canonical": "OneCLI", "kind": "product",
                 "review_status": "verified"},
                {"surface": "Auth", "canonical": "OAuth", "kind": "protocol",
                 "review_status": "verified"},
            ],
        }
        output = score("OneCLI OAuth agent", [], ref, ["OneCLI", "OAuth", "agent"])
        self.assertEqual(output["hallucinated_terms"], [])
        self.assertEqual(output["components"]["term_precision"], 1.0)
        self.assertEqual(output["components"]["term_recall"], 1.0)

    def test_approved_exhaustive_reference_enables_precision(self):
        result = score("LangGraph NanoClaw", [], {
            "technical_terms": ["LangGraph"], "review_status": "approved",
            "terms_exhaustive": True,
        }, ["LangGraph", "NanoClaw"])
        self.assertEqual(result["components"]["term_precision"], 0.5)
        self.assertEqual(result["hallucinated_terms"], ["NanoClaw"])


if __name__ == "__main__":
    unittest.main()
