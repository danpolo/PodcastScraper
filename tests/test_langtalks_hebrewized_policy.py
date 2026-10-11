"""Protect Hebrewized loanwords from unwanted Latinization or term scoring."""
import unittest

from langtalks.agent_format import from_asr, render_markdown
from langtalks.reference_draft import _candidate_terms


class HebrewizedSpeechTests(unittest.TestCase):
    def test_loanwords_stay_hebrew_in_agent_transcript(self):
        spoken = "היוזרים מריצים אייג'נטים בקונטיינרים, ואחר כך דיבגתי"
        asr = {
            "provider": "local_whisper_turbo", "source": "excerpt",
            "time_offset": 480, "episode_guid": "mixed-hebrew-test",
            "text": spoken,
            "tokens": [{"text": spoken, "start": 490, "end": 500}],
        }
        draft = from_asr(asr)
        md = render_markdown(draft)
        for word in ["היוזרים", "אייג'נטים", "בקונטיינרים", "דיבגתי"]:
            self.assertIn(word, draft["turns"][0]["text"])
            self.assertIn(word, md)
        self.assertNotIn("users", draft["turns"][0]["text"])
        self.assertNotIn("containers", draft["turns"][0]["text"])
        self.assertEqual(draft["concept_mentions"], [])

    def test_english_concept_annotation_does_not_rewrite_hebrew_surface(self):
        spoken = "עם יוזרים שמריצים אייג'נטים בקונטיינרים"
        asr = {
            "provider": "ASR", "episode_guid": "mixed",
            "text": spoken,
            "tokens": [{"text": spoken, "start": 10, "end": 17}],
        }
        proposal = {"suggested_terms": [{
            "term": "אייג'נטים", "canonical": "AI agents",
            "kind": "technical_concept",
            "occurrences": [{"start": 13, "end": 14,
                             "text": "אייג'נטים", "sources": ["ASR"]}],
        }]}
        d = from_asr(asr, proposal)
        self.assertIn("אייג'נטים", d["turns"][0]["text"])
        self.assertEqual(d["concept_mentions"][0]["surface"], "אייג'נטים")
        self.assertEqual(d["concept_mentions"][0]["canonical"], "AI agents")
        self.assertEqual(d["concept_mentions"][0]["review_status"], "suggested")

    def test_loanwords_not_mistaken_for_latin_glossary_words(self):
        terms = _candidate_terms("יוזרים, אייג'נטים, קונטיינרים, דיבגתי")
        self.assertEqual(terms, [])
        self.assertIn("code", _candidate_terms("עושים code review"))
        self.assertIn("review", _candidate_terms("עושים code review"))


if __name__ == "__main__":
    unittest.main()
