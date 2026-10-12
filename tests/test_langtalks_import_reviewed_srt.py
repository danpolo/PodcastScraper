"""Reviewed subtitle roundtrip never invents word or speaker approval."""
import unittest

from langtalks.agent_format import from_asr
from langtalks.import_reviewed_srt import import_srt, parse_srt


class ReviewedSubtitlesTests(unittest.TestCase):
    def setUp(self):
        self.draft = from_asr({
            "episode_guid": "ep", "time_offset": 480, "provider": "local_whisper",
            "text": "שלום OneCLI וזה קונטיינר",
            "tokens": [
                {"text": "שלום OneCLI", "start": 480, "end": 484},
                {"text": " וזה קונטיינר", "start": 484, "end": 490},
            ],
        }, {"episode_guid": "ep", "editorial_topics": [
            {"id": "topic-1", "title": "authentication",
             "turn_ids": ["turn-0001"], "status": "suggested"}]})
        self.srt = (
            "1\n00:00:00,000 --> 00:00:04,000\nשלום OneCLI\n\n"
            "2\n00:00:04,000 --> 00:00:10,000\nוזה קונטיינר\n"
        )

    def test_edit_roundtrip_separates_spoken_text_and_verified_entities(self):
        ref = {
            "episode_guid": "ep", "review_status": "approved",
            "terms_exhaustive": True, "concept_mentions": [
                {"start_s": 481, "end_s": 482, "surface": "OneCLI",
                 "canonical": "OneCLI", "kind": "product",
                 "review_status": "verified"},
                {"start_s": 486, "end_s": 487, "surface": "קונטיינר",
                 "canonical": "container", "kind": "technical_concept",
                 "review_status": "suggested"},
            ],
        }
        d = import_srt(self.draft, self.srt, reference=ref,
                       full_audio_reviewed=True)
        self.assertEqual(d["status"], "human_reviewed")
        self.assertEqual(d["turns"][0]["text"], "שלום OneCLI")
        self.assertEqual(d["turns"][1]["text"], "וזה קונטיינר")
        self.assertEqual(d["turns"][0]["start_s"], 480)
        self.assertEqual(d["turns"][1]["start_s"], 484)
        self.assertTrue(all(t["review_status"] == "verified" for t in d["turns"]))
        self.assertTrue(all(t["speaker_id"] is None for t in d["turns"]))
        self.assertEqual(d["topics"][0]["status"], "suggested")
        self.assertTrue(d["topics"][0]["turn_ids"])
        self.assertEqual([m["review_status"] for m in d["concept_mentions"]],
                         ["verified", "suggested"])
        self.assertIn("original_draft_hash", d["provenance"])

    def test_open_lexical_question_is_not_misrepresented_as_verified(self):
        altered_srt = self.srt.replace("שלום OneCLI", "שלום some")
        ref = {
            "episode_guid": "ep", "review_status": "approved",
            "terms_exhaustive": True,
            "transcript_uncertainties": [
                {"kind": "spoken_english_word",
                 "proposed": "some", "original": "Sum",
                 "episode_start_s": 480.0, "episode_end_s": 484.0,
                 "review_status": "needs_review"},
            ],
        }
        output = import_srt(self.draft, altered_srt, reference=ref,
                            full_audio_reviewed=True)
        self.assertEqual(output["status"], "human_reviewed_with_open_questions")
        self.assertEqual(output["turns"][0]["review_status"], "needs_review")
        self.assertEqual(output["turns"][1]["review_status"], "verified")
        self.assertEqual(len(output["transcript_uncertainties"]), 1)

    def test_without_explicit_approval_transcript_remains_draft(self):
        d = import_srt(self.draft, self.srt, full_audio_reviewed=False)
        self.assertEqual(d["status"], "machine_draft")
        self.assertTrue(all(t["review_status"] == "suggested" for t in d["turns"]))
        self.assertEqual(d["provenance"]["transcript_review"],
                         "edited_draft_not_yet_verified")

    def test_missing_audio_does_not_infer_content(self):
        with self.assertRaisesRegex(ValueError, "different audio window"):
            import_srt(self.draft, (
                "1\n00:00:00,000 --> 00:00:04,000\nשלום\n\n"
                "2\n00:00:04,000 --> 00:00:05,000\nOneCLI\n"
            ))

    def test_reject_overlaps_blank_and_broken_timestamps(self):
        for bad in (
            "1\n00:00:00,000 --> 00:00:04,000\nשלום\n\n2\n00:00:03,000 --> 00:00:06,000\nOther\n",
            "1\n00:00:00,000 --> 00:00:04,000\n\n",
            "1\n00:00:00.000 --> 00:00:04.000\nword\n",
            "1\n00:00:00,000 --> 00:00:04,000\nשלום\n\n1\n00:00:04,000 --> 00:00:10,000\nOther\n",
        ):
            with self.subTest(case=bad[:45]):
                with self.assertRaises(ValueError):
                    parse_srt(bad)

    def test_unicode_bom_and_hebrew_english(self):
        x = parse_srt("\ufeff" + self.srt)
        self.assertEqual(len(x), 2)
        self.assertIn("OneCLI", x[0]["text"])


if __name__ == "__main__":
    unittest.main()
