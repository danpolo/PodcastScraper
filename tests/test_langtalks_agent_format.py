"""Contract tests for agent-readable Hebrew/English transcript v1."""
import json
import tempfile
import unittest
from pathlib import Path

from langtalks.agent_format import from_asr, render_markdown, validate, apply_reference


class AgentTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.asr = {
            "provider": "local_ivrit_turbo", "source": "excerpt",
            "time_offset": 480, "episode_guid": "episode-71",
            "episode_title": "Claw Architectures",
            "text": "עושים code review ואז managed hosted version",
            "tokens": [
                {"text": " עושים", "start": 488.1, "end": 488.5},
                {"text": " code", "start": 489.0, "end": 489.4},
                {"text": " review", "start": 489.4, "end": 489.8},
                {"text": " ואז", "start": 490, "end": 490.6},
                {"text": " managed", "start": 491, "end": 491.7},
                {"text": " hosted", "start": 491.8, "end": 492.4},
                {"text": " version", "start": 492.5, "end": 493},
            ],
        }
        self.proposal = {
            "episode_guid": "episode-71",
            "suggested_terms": [
                {"term": "code review", "kind": "technical_practice",
                 "occurrences": [{"start": 489, "end": 489.8,
                                  "text": "code review",
                                  "sources": ["local_ivrit_turbo"]}]},
                {"term": "managed hosted version", "kind": "descriptive_concept",
                 "canonical": "managed hosting",
                 "occurrences": [{"start": 491, "end": 493,
                                  "text": "managed hosted version"}]},
            ],
        }

    def test_faithful_words_not_replaced_by_concept_canonical(self):
        document = from_asr(self.asr, self.proposal)
        text = " ".join(t["text"] for t in document["turns"])
        self.assertIn("managed hosted version", text)
        self.assertNotIn("managed hosting", text)
        m = next(x for x in document["concept_mentions"]
                 if x["canonical"] == "managed hosting")
        self.assertEqual(m["surface"], "managed hosted version")
        self.assertEqual(m["review_status"], "suggested")
        self.assertIsNotNone(m["turn_id"])
        md = render_markdown(document)
        self.assertIn("managed hosted version", md)
        self.assertIn("managed hosting", md)
        self.assertIn("Unverified technical terminology", md)
        self.assertIn("08:09", md)

    def test_never_invents_speaker_or_verification(self):
        d = from_asr(self.asr)
        self.assertEqual(d["status"], "machine_draft")
        self.assertEqual(d["provenance"]["editorial_review"], "not_approved")
        self.assertTrue(all(t["speaker_id"] is None for t in d["turns"]))
        self.assertTrue(all(t["review_status"] == "suggested" for t in d["turns"]))

    def test_preserves_separate_multilingual_turns_with_speakers(self):
        self.asr["tokens"][0]["speaker"] = "host"
        for tok in self.asr["tokens"][1:]:
            tok["speaker"] = "guest"
        doc = from_asr(self.asr)
        self.assertEqual(len(doc["turns"]), 2)
        self.assertEqual(doc["turns"][0]["speaker_id"], "host")
        self.assertEqual(doc["turns"][1]["speaker_id"], "guest")

    def test_empty_token_timing_does_not_invent_word_alignment(self):
        self.asr["tokens"] = []
        doc = from_asr(self.asr, self.proposal)
        self.assertEqual(doc["turns"][0]["timestamp_precision"], "window_only")
        self.assertEqual(doc["turns"][0]["text"], self.asr["text"])
        self.assertEqual(doc["turns"][0]["end_s"], 480.0 if not self.proposal.get("window") else 780)

    def test_unknown_turn_ref_rejected(self):
        doc = from_asr(self.asr, self.proposal)
        doc["concept_mentions"][0]["turn_id"] = "imagined-turn"
        with self.assertRaisesRegex(ValueError, "nonexistent turn"):
            validate(doc)

    def test_editorial_topics_are_suggested_and_grounded_in_turn_ids(self):
        self.proposal["editorial_topics"] = [{
            "id": "topic-auth", "title": "Credential management",
            "turn_ids": ["turn-0001"], "status": "verified",
        }]
        result = from_asr(self.asr, self.proposal)
        self.assertEqual(result["topics"][0]["status"], "suggested")
        self.assertIn("Credential management", render_markdown(result))

    def test_proposed_topic_cannot_claim_verified_status(self):
        doc = from_asr(self.asr)
        doc["topics"].append({"title": "Credential management",
                              "turn_ids": ["turn-0001"], "status": "inferred"})
        with self.assertRaisesRegex(ValueError, "qualified"):
            validate(doc)

    def test_approved_review_attaches_concepts_but_doesnt_verify_hebrew(self):
        doc = from_asr(self.asr, self.proposal)
        approved = {
            "episode_guid": "episode-71", "review_status": "approved",
            "terms_exhaustive": True,
            "verified_occurrences": [{
                "term": "managed hosting",
                "surface": "managed hosted version",
                "kind": "descriptive_concept",
                "start": 491, "end": 493,
                "source_models": ["local_ivrit_turbo"],
            }],
        }
        result = apply_reference(doc, approved)
        self.assertEqual(len(result["concept_mentions"]), 1)
        self.assertEqual(result["concept_mentions"][0]["canonical"],
                         "managed hosting")
        self.assertEqual(result["concept_mentions"][0]["review_status"],
                         "verified")
        self.assertIn("managed hosted version", result["turns"][0]["text"])
        self.assertEqual(result["turns"][0]["review_status"], "suggested")
        self.assertEqual(result["status"], "machine_draft")

    def test_reviewed_reference_does_not_promote_editorial_suggestion(self):
        doc = from_asr(self.asr, self.proposal)
        data = {
            "episode_guid": "episode-71", "review_status": "approved",
            "terms_exhaustive": True,
            "concept_mentions": [
                {
                    "start_s": 489, "end_s": 489.8,
                    "surface": "code review", "canonical": "code review",
                    "kind": "technical_practice", "review_status": "verified",
                },
                {
                    "start_s": 491, "end_s": 493,
                    "surface": "managed hosted version",
                    "canonical": "managed hosting",
                    "kind": "descriptive_concept", "review_status": "suggested",
                    "provenance": {"editorial_note": "Confirm wording"},
                },
            ],
        }
        result = apply_reference(doc, data)
        self.assertEqual(
            [m["review_status"] for m in result["concept_mentions"]],
            ["verified", "suggested"],
        )
        self.assertEqual(
            result["concept_mentions"][1]["provenance"]["human_review"],
            "not_yet_approved",
        )
        self.assertIn("Unverified technical terminology", render_markdown(result))

    def test_user_confirmed_onecli_repairs_only_matching_asr_spelling(self):
        guid = "episode-71"
        transcript = from_asr({
            "episode_guid": guid, "provider": "ivrit", "source": "excerpt",
            "time_offset": 480,
            "text": "1.cli עושה auth ואז שוב 1.Cלי",
            "tokens": [
                {"text": "1.cli", "start": 646, "end": 647},
                {"text": " עושה auth ואז שוב ", "start": 647, "end": 660},
                {"text": "1.Cלי", "start": 660, "end": 661},
            ],
        })
        ref = {
            "episode_guid": guid,
            "review_status": "approved", "terms_exhaustive": True,
            "verified_occurrences": [
                {"surface": "OneCLI", "canonical": "OneCLI",
                 "start": 646, "end": 647, "review_status": "verified",
                 "speaker_correction_source": "user_explicit_confirmation"},
                {"surface": "OneCLI", "canonical": "OneCLI",
                 "start": 660, "end": 661, "review_status": "verified",
                 "speaker_correction_source": "user_explicit_confirmation"},
            ],
        }
        result = apply_reference(transcript, ref)
        text = " ".join(t["text"] for t in result["turns"])
        self.assertEqual(text.count("OneCLI"), 2)
        self.assertIn("auth", text)
        self.assertTrue(any("1.cli" in t.get("original_asr_text", "")
                            for t in result["turns"]))
        edits = result["provenance"]["explicit_text_corrections"]
        self.assertTrue(any(x["status"] == "corrected" for x in edits))
        self.assertTrue(all(t["review_status"] == "suggested" for t in result["turns"]))

    def test_onecli_correction_fails_closed_on_mismatch(self):
        doc = from_asr({
            "episode_guid": "episode-71", "text": "1.cli בלבד",
            "provider": "test",
            "tokens": [{"text": "1.cli בלבד", "start": 646, "end": 660}],
        })
        ref = {
            "episode_guid": "episode-71",
            "review_status": "approved", "terms_exhaustive": True,
            "verified_occurrences": [
                {"surface": "OneCLI", "start": 646, "end": 647,
                 "speaker_correction_source": "user_explicit_confirmation",
                 "review_status": "verified"},
                {"surface": "OneCLI", "start": 651, "end": 652,
                 "speaker_correction_source": "user_explicit_confirmation",
                 "review_status": "verified"},
            ],
        }
        result = apply_reference(doc, ref)
        self.assertEqual(result["turns"][0]["text"], "1.cli בלבד")
        self.assertEqual(
            result["provenance"]["explicit_text_corrections"][0]["status"],
            "skipped_ambiguous_alignment",
        )

    def test_pending_review_never_verifies_models(self):
        doc = from_asr(self.asr, self.proposal)
        result = apply_reference(doc, {
            "episode_guid": "episode-71", "review_status": "pending",
            "terms_exhaustive": False, "verified_occurrences": [{
                "term": "managed hosting", "surface": "managed hosted version",
                "start": 491, "end": 493,
            }],
        })
        self.assertTrue(all(m["review_status"] == "suggested"
                            for m in result["concept_mentions"]))
        self.assertEqual(result["provenance"]["reference_review_status"], "pending")

    def test_markdown_is_deterministic(self):
        doc = from_asr(self.asr, self.proposal)
        self.assertEqual(render_markdown(doc), render_markdown(json.loads(json.dumps(doc))))


if __name__ == "__main__":
    unittest.main()
