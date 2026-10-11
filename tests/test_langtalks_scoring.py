"""Code-switch metric regression tests."""
import unittest

from langtalks.score import score, term_recall


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

    def test_partial_reference_cannot_prove_hallucinations(self):
        result = score("LangGraph NanoClaw", [], {
            "technical_terms": ["LangGraph"], "review_status": "draft",
        }, ["LangGraph", "NanoClaw"])
        self.assertIsNone(result["components"]["term_precision"])
        self.assertEqual(result["hallucinated_terms"], [])
        self.assertEqual(result["components"]["term_recall"], 1)

    def test_approved_exhaustive_reference_enables_precision(self):
        result = score("LangGraph NanoClaw", [], {
            "technical_terms": ["LangGraph"], "review_status": "approved",
            "terms_exhaustive": True,
        }, ["LangGraph", "NanoClaw"])
        self.assertEqual(result["components"]["term_precision"], 0.5)
        self.assertEqual(result["hallucinated_terms"], ["NanoClaw"])


if __name__ == "__main__":
    unittest.main()
