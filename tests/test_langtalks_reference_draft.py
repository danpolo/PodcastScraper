"""Reference suggestions are unverified until someone checks the audio."""
import json
from pathlib import Path
import tempfile
import unittest

from langtalks.reference_draft import propose, write_draft


class ReferenceDraftTests(unittest.TestCase):
    def test_terms_have_provider_votes_but_never_ground_truth_status(self):
        guid = "fake-episode"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcripts = root / "transcripts"
            transcripts.mkdir()
            (transcripts / f"{guid}.groq_v3.json").write_text(
                json.dumps({"provider": "groq_v3", "source": "excerpt",
                            "text": "מפעילים LangGraph דרך MCP ו-NanoClaw",
                            "tokens": []}, ensure_ascii=False), encoding="utf-8")
            (transcripts / f"{guid}.soniox.json").write_text(
                json.dumps({"provider": "soniox", "source": "excerpt",
                            "text": "משתמשים ב LangGraph דרך MCP",
                            "tokens": []}, ensure_ascii=False), encoding="utf-8")
            ref = {"episode_guid": guid, "episode_title": "Example",
                   "window": {"start": 0, "end": 300}}
            result = propose(guid, transcripts, ref)
            terms = {x["term"].casefold(): x for x in result["suggested_terms"]}
            self.assertEqual(set(terms["langgraph"]["seen_in"]),
                             {"groq_v3", "soniox"})
            self.assertEqual(terms["nanoclaw"]["seen_in"], ["groq_v3"])
            self.assertTrue(result["draft_only"])
            self.assertNotIn("technical_terms", result)
            self.assertNotIn("review_status", result)

    def test_occurrences_merge_across_models_with_word_times(self):
        guid = "timed"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ref = {"window": {"start": 480, "end": 780}}
            for source, delta in (("groq_v3", 0), ("local_ivrit_turbo", .4)):
                payload = {
                    "provider": source, "source": "excerpt",
                    "text": " בMCP ו NanoClaw וגם MCP",
                    "tokens": [
                        {"text": "בMCP", "start": 491+delta, "end": 492+delta},
                        {"text": " ו ", "start": 492+delta, "end": 493+delta},
                        {"text": " NanoClaw", "start": 493+delta, "end": 495+delta},
                        {"text": " וגם ", "start": 495+delta, "end": 497+delta},
                        {"text": " MCP", "start": 530+delta, "end": 531+delta},
                    ],
                }
                (root / f"{guid}.{source}.json").write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            draft = propose(guid, root, ref)
            mcp = next(t for t in draft["suggested_terms"]
                       if t["term"].casefold() == "mcp")
            self.assertEqual(len(mcp["occurrences"]), 2)
            self.assertEqual(mcp["occurrences"][0]["sources"],
                             ["groq_v3", "local_ivrit_turbo"])
            self.assertAlmostEqual(mcp["occurrences"][0]["start"], 491)
            self.assertAlmostEqual(mcp["occurrences"][1]["start"], 530)
            nano = next(t for t in draft["suggested_terms"]
                        if t["term"].casefold() == "nanoclaw")
            self.assertEqual(len(nano["occurrences"]), 1)

    def test_multiword_term_timestamp_and_hyphen_variant(self):
        guid = "multiword"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = {
                "provider": "local", "source": "excerpt",
                "text": "Nano-Claw code review",
                "tokens": [
                    {"text": "Nano-Claw", "start": 510, "end": 512},
                    {"text": " code", "start": 513, "end": 514},
                    {"text": " review", "start": 514, "end": 515},
                ],
            }
            (root / f"{guid}.local.json").write_text(json.dumps(payload),
                                                       encoding="utf-8")
            draft = propose(guid, root, {"window": {"start": 480, "end": 780}})
            phrase = next(t for t in draft["suggested_terms"]
                          if t["term"].lower() == "code review")
            self.assertEqual(phrase["occurrences"][0]["start"], 513)
            self.assertEqual(phrase["occurrences"][0]["end"], 515)
            self.assertTrue(draft["timestamps_are_estimates"])

    def test_writing_draft_preserves_original_reference(self):
        guid = "sample"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ref = root / "reference"
            trans = root / "transcripts"
            ref.mkdir()
            trans.mkdir()
            original = {"episode_guid": guid, "technical_terms": [],
                        "window": {"start": 480, "end": 780}}
            (ref / f"{guid}.json").write_text(json.dumps(original), encoding="utf-8")
            path, draft = write_draft(guid, ref, trans, root / "out")
            self.assertTrue(path.exists())
            self.assertEqual(draft["provider_outputs_considered"], [])
            self.assertEqual(json.loads((ref / f"{guid}.json").read_text()), original)

    def test_unscorable_untimed_full_transcripts_ignored(self):
        guid = "sample"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / f"{guid}.groq_v3.json").write_text(
                json.dumps({"provider": "groq_v3", "source": "full",
                            "text": "LangGraph", "tokens": []}), encoding="utf-8")
            result = propose(guid, root, {"window": {"start": 100, "end": 200}})
            self.assertEqual(result["suggested_terms"], [])
            self.assertEqual(result["provider_outputs_considered"], [])


if __name__ == "__main__":
    unittest.main()
