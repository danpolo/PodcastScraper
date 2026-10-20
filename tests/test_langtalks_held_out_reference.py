"""Tests for Phase 2-3 ground-truth reference extraction and review generation.

Covers:
- Verbatim import of user-corrected SRT
- Hebrewized technical terminology cross-script concept linking (e.g., ההרנס -> harness)
- Phonetic filename discovery (e.g., באג'נטס MD / האג'נטס MD / ב-agents MD -> AGENTS.md)
- Semantic separation of Subagent, Agentic search, Agent harness from generic AI agent
- Concepts appearing exclusively in Hebrew script (צ'אנקינג, ריזנינג, פולבקים, פילטור, סכמה, פרמטרים, etc.)
- Multi-word compound precedence and duplicate prevention
- Review progress preservation and concept migration engine
- SRT timestamp handling and token precision
- Dataset A, B, and C isolation invariants
- Self-contained review HTML generation with migration support
"""

import json
import subprocess
import tempfile
from pathlib import Path
import unittest

from langtalks.import_reviewed_srt import import_srt, parse_srt
from langtalks.agent_format import from_asr
from langtalks.reference_extraction import (
    extract_reference_candidates,
    _align_term_in_cue,
    LEXICON,
)
from langtalks.generate_review_html import (
    build_review_html,
    migrate_review_session,
    bulk_approve_confident,
    export_approved_reference,
)


class HeldOutReferenceExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eval_dir = Path(__file__).resolve().parents[1] / "langtalks/evaluations/0e404ceb-d04b-4818-907d-a74aafa7c155"
        cls.srt_path = cls.eval_dir / "reference_user_corrected.original.srt"
        cls.hybrid_path = cls.eval_dir / "hybrid_revised.original.json"
        cls.glossary_a_path = cls.eval_dir / "engine_glossary.original.json"
        cls.detected_b_path = cls.eval_dir / "engine_terms_detected.original.json"
        cls.proposed_c_path = cls.eval_dir / "reference_terms.proposed.json"

    def test_verbatim_srt_import_invariants(self):
        """User-corrected SRT must import with 100% text fidelity and valid bounds."""
        content = self.srt_path.read_text(encoding="utf-8-sig")
        cues = parse_srt(content)
        self.assertEqual(len(cues), 287)
        self.assertAlmostEqual(cues[0]["start"], 0.21)
        self.assertAlmostEqual(cues[-1]["end"], 1839.25)

        # Check verbatim wording in key cues
        self.assertIn("LangTalks", cues[0]["text"])
        self.assertIn("ההרנס", cues[3]["text"])
        self.assertIn("RAG", cues[3]["text"])
        self.assertIn("SDLC", cues[3]["text"])
        self.assertIn("בJev", cues[2]["text"])

        asr = json.loads(self.hybrid_path.read_text(encoding="utf-8"))
        draft = from_asr(asr)
        imported = import_srt(draft, content, full_audio_reviewed=True)

        self.assertEqual(len(imported["turns"]), 287)
        self.assertEqual(imported["status"], "human_reviewed")
        self.assertTrue(all(t["review_status"] == "verified" for t in imported["turns"]))
        self.assertEqual(imported["turns"][0]["text"], cues[0]["text"])
        self.assertEqual(imported["turns"][3]["text"], cues[3]["text"])

    def test_hebrewized_terminology_cross_script_linking(self):
        """Cross-script Hebrew expressions (ההרנס, בארנס) must map to harness while retaining surface."""
        proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        harness = next((g for g in proposal["suggested_terms"] if g["canonical"] == "harness"), None)
        self.assertIsNotNone(harness)
        self.assertTrue(harness["is_cross_script"])
        self.assertTrue(harness["uncertainty_flag"])
        self.assertEqual(harness["kind"], "technical_concept")
        self.assertIn("ההרנס", harness["surfaces"])
        self.assertIn("בארנס", harness["surfaces"])
        self.assertEqual(len(harness["occurrences"]), 2)

        # First occurrence: ההרנס in cue 4
        occ1 = harness["occurrences"][0]
        self.assertEqual(occ1["surface"], "ההרנס")
        self.assertEqual(occ1["source_cue_id"], "turn-0004")
        self.assertEqual(occ1["hebrew_morphology"]["prefix"], "ה-")
        self.assertEqual(occ1["hebrew_morphology"]["stem"], "הרנס")
        self.assertAlmostEqual(occ1["start"], 24.13, places=1)

        # Second occurrence: בארנס in cue 225
        occ2 = harness["occurrences"][1]
        self.assertEqual(occ2["surface"], "בארנס")
        self.assertEqual(occ2["source_cue_id"], "turn-0225")
        self.assertEqual(occ2["hebrew_morphology"]["prefix"], "ב-")
        self.assertEqual(occ2["hebrew_morphology"]["stem"], "ארנס")
        self.assertAlmostEqual(occ2["start"], 1449.49, places=1)

        # Separate specific concept: Agent harness in cue 246
        agent_harness = next((g for g in proposal["suggested_terms"] if g["canonical"] == "Agent harness"), None)
        self.assertIsNotNone(agent_harness)
        self.assertEqual(len(agent_harness["occurrences"]), 1)
        self.assertEqual(agent_harness["occurrences"][0]["surface"], "agent harness")
        self.assertEqual(agent_harness["occurrences"][0]["source_cue_id"], "turn-0246")

    def test_phonetic_filename_discovery_and_separation(self):
        """Phonetic spoken filenames (באג'נטס MD, האג'נטס MD, ב-agents MD) must map to AGENTS.md."""
        proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        agents_md = next((g for g in proposal["suggested_terms"] if g["canonical"] == "AGENTS.md"), None)
        self.assertIsNotNone(agents_md)
        self.assertEqual(agents_md["kind"], "tool")
        self.assertEqual(len(agents_md["occurrences"]), 3)

        cues_found = [o["source_cue_id"] for o in agents_md["occurrences"]]
        surfaces_found = [o["surface"] for o in agents_md["occurrences"]]
        self.assertEqual(cues_found, ["turn-0222", "turn-0223", "turn-0224"])
        self.assertEqual(surfaces_found, ["ב-agents MD", "האג'נטס MD", "באג'נטס MD"])

        # Surfaces of AGENTS.md must not be claimed by AI agent or Markdown
        ai_agent = next((g for g in proposal["suggested_terms"] if g["canonical"] == "AI agent"), None)
        markdown = next((g for g in proposal["suggested_terms"] if g["canonical"] == "Markdown"), None)
        if ai_agent:
            ai_surfaces = {o["surface"] for o in ai_agent["occurrences"]}
            self.assertNotIn("באג'נטס", ai_surfaces)
            self.assertNotIn("האג'נטס", ai_surfaces)
            self.assertNotIn("ב-agents", ai_surfaces)
            self.assertNotIn("באג'נטס MD", ai_surfaces)
        if markdown:
            for cue in ["turn-0222", "turn-0223", "turn-0224"]:
                self.assertFalse(any(o["source_cue_id"] == cue for o in markdown["occurrences"]))

    def test_subagent_and_agentic_search_separation(self):
        """Specific agent paradigms (Subagent, Agentic search) must not be lumped under generic AI agent."""
        proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )

        subagent = next((g for g in proposal["suggested_terms"] if g["canonical"] == "Subagent"), None)
        self.assertIsNotNone(subagent)
        self.assertEqual(len(subagent["occurrences"]), 1)
        self.assertEqual(subagent["occurrences"][0]["surface"], "סאב אייג'נט")
        self.assertEqual(subagent["occurrences"][0]["source_cue_id"], "turn-0160")

        agentic_search = next((g for g in proposal["suggested_terms"] if g["canonical"] == "Agentic search"), None)
        self.assertIsNotNone(agentic_search)
        self.assertEqual(len(agentic_search["occurrences"]), 3)
        surfaces = [o["surface"] for o in agentic_search["occurrences"]]
        self.assertIn("האג'נטיק סרצ'", surfaces)
        self.assertIn("איג'נטיק סארץ'", surfaces)

        ai_agent = next((g for g in proposal["suggested_terms"] if g["canonical"] == "AI agent"), None)
        self.assertIsNotNone(ai_agent)
        # Cue 160 has סאב אייג'נט, cue 88 has האג'נטיק סרצ', cue 162 has איג'נטיק סארץ'
        for cue in ["turn-0160", "turn-0088", "turn-0162"]:
            self.assertFalse(any(o["source_cue_id"] == cue for o in ai_agent["occurrences"]))

    def test_hebrew_exclusive_technical_concepts(self):
        """Technical concepts spoken exclusively in Hebrewized forms must be automatically discovered."""
        proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        by_canonical = {g["canonical"]: g for g in proposal["suggested_terms"]}

        # 1. צ'אנקינג -> Chunking
        self.assertIn("Chunking", by_canonical)
        self.assertIn("צ'אנקינג", by_canonical["Chunking"]["surfaces"])

        # 2. ריזנינג -> Reasoning
        self.assertIn("Reasoning", by_canonical)
        self.assertIn("ריזנינג", by_canonical["Reasoning"]["surfaces"])

        # 3. פולבקים / פולבק -> Fallback
        self.assertIn("Fallback", by_canonical)
        self.assertIn("פולבקים", by_canonical["Fallback"]["surfaces"])

        # 4. פילטור -> Filtering
        self.assertIn("Filtering", by_canonical)
        self.assertIn("פילטור", by_canonical["Filtering"]["surfaces"])

        # 5. סכמה -> Schema
        self.assertIn("Schema", by_canonical)
        self.assertIn("סכמה", by_canonical["Schema"]["surfaces"])

        # 6. פרמטרים -> Parameters
        self.assertIn("Parameters", by_canonical)
        self.assertIn("פרמטרים", by_canonical["Parameters"]["surfaces"])

        # 7. רוברטה -> RoBERTa
        self.assertIn("RoBERTa", by_canonical)
        self.assertIn("רוברטה", by_canonical["RoBERTa"]["surfaces"])

        # 8. דיברט -> DeBERTa
        self.assertIn("DeBERTa", by_canonical)
        self.assertIn("דיברט", by_canonical["DeBERTa"]["surfaces"])

        # 9. רלבילי -> Reliability
        self.assertIn("Reliability", by_canonical)
        self.assertIn("רלבילי", by_canonical["Reliability"]["surfaces"])

        # 10. נהיגה אוטונומית -> Autonomous driving
        self.assertIn("Autonomous driving", by_canonical)
        self.assertTrue(any("אוטונומית" in s for s in by_canonical["Autonomous driving"]["surfaces"]))

        # 11. סילבר בולט -> Silver bullet
        self.assertIn("Silver bullet", by_canonical)
        self.assertIn("סילבר בולט", by_canonical["Silver bullet"]["surfaces"])

    def test_zero_shot_classifier_cross_script(self):
        """Zero-shot classifier must link both Latin and Hebrewized spoken occurrences."""
        proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        zsc = next((g for g in proposal["suggested_terms"] if g["canonical"] == "Zero-shot classifier"), None)
        self.assertIsNotNone(zsc)
        self.assertEqual(len(zsc["occurrences"]), 4)
        surfaces = [o["surface"] for o in zsc["occurrences"]]
        self.assertTrue(any("Zero-shot" in s for s in surfaces))
        self.assertTrue(any("זירושוט" in s for s in surfaces))

    def test_review_session_migration_preserves_progress(self):
        """Session migration must preserve reviewed decisions while remapping refined concepts."""
        old_session = {
            "listened": True,
            "term_groups": [
                {
                    "canonical": "AI agent",
                    "kind": "technical_concept",
                    "occurrences": [
                        {
                            "start": 1437.23,
                            "end": 1438.5,
                            "source_cue_id": "turn-0224",
                            "surface": "באג'נטס MD",
                            "state": "confirmed",
                            "notes": "Reviewed in subtitle edit",
                        },
                        {
                            "start": 1012.61,
                            "end": 1014.0,
                            "source_cue_id": "turn-0160",
                            "surface": "סאב אייג'נט",
                            "state": "confirmed",
                        },
                        {
                            "start": 549.97,
                            "end": 551.5,
                            "source_cue_id": "turn-0088",
                            "surface": "האג'נטיק סרצ'",
                            "state": "rejected",
                        },
                        {
                            "start": 1585.19,
                            "end": 1586.5,
                            "source_cue_id": "turn-0246",
                            "surface": "agent harness",
                            "state": "confirmed",
                        },
                        {
                            "start": 125.0,
                            "end": 126.0,
                            "source_cue_id": "turn-0022",
                            "surface": "האג'נטי",
                            "state": "confirmed",
                        },
                        {
                            "start": 999.0,
                            "end": 1000.0,
                            "source_cue_id": "manual",
                            "surface": "Custom User Term",
                            "state": "confirmed",
                            "manual": True,
                        },
                    ],
                }
            ],
        }

        new_proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        migrated = migrate_review_session(old_session, new_proposal)

        self.assertTrue(migrated["listened"])

        # Check AGENTS.md remapping: previously approved but reassigned -> must require renewed approval
        agents_md = next(g for g in migrated["term_groups"] if g["canonical"] == "AGENTS.md")
        occ_224 = next(o for o in agents_md["occurrences"] if o["source_cue_id"] == "turn-0224")
        self.assertEqual(occ_224["state"], "pending")
        self.assertTrue(occ_224.get("reapproval_required"))
        self.assertEqual(occ_224.get("migrated_from"), "AI agent")
        self.assertTrue(occ_224.get("reassigned"))
        self.assertEqual(occ_224.get("notes"), "Reviewed in subtitle edit")

        # Check Subagent remapping: previously approved but reassigned -> must require renewed approval
        subagent = next(g for g in migrated["term_groups"] if g["canonical"] == "Subagent")
        occ_160 = next(o for o in subagent["occurrences"] if o["source_cue_id"] == "turn-0160")
        self.assertEqual(occ_160["state"], "pending")
        self.assertTrue(occ_160.get("reapproval_required"))
        self.assertEqual(occ_160.get("migrated_from"), "AI agent")
        self.assertTrue(occ_160.get("reassigned"))

        # Check Agentic search remapping: previously rejected under AI agent -> requires fresh decision on new concept
        agentic = next(g for g in migrated["term_groups"] if g["canonical"] == "Agentic search")
        occ_88 = next(o for o in agentic["occurrences"] if o["source_cue_id"] == "turn-0088")
        self.assertEqual(occ_88["state"], "pending")
        self.assertTrue(occ_88.get("reapproval_required"))
        self.assertEqual(occ_88.get("previously_rejected_under"), "AI agent")
        self.assertEqual(occ_88.get("migrated_from"), "AI agent")

        # Check Agent harness remapping: previously approved but reassigned -> must require renewed approval
        agent_harness = next(g for g in migrated["term_groups"] if g["canonical"] == "Agent harness")
        occ_246 = next(o for o in agent_harness["occurrences"] if o["source_cue_id"] == "turn-0246")
        self.assertEqual(occ_246["state"], "pending")
        self.assertTrue(occ_246.get("reapproval_required"))
        self.assertEqual(occ_246.get("migrated_from"), "AI agent")

        # Check generic AI agent preserved
        ai_agent = next(g for g in migrated["term_groups"] if g["canonical"] == "AI agent")
        occ_22 = next(o for o in ai_agent["occurrences"] if o["source_cue_id"] == "turn-0022")
        self.assertEqual(occ_22["state"], "confirmed")
        self.assertIsNone(occ_22.get("migrated_from"))

        # Check manual addition carried over
        manual_occ = next(
            (o for g in migrated["term_groups"] for o in g["occurrences"] if o.get("surface") == "Custom User Term"),
            None,
        )
        self.assertIsNotNone(manual_occ)
        self.assertTrue(manual_occ.get("manual"))
        self.assertEqual(manual_occ.get("state"), "confirmed")

    def test_repeated_occurrences_tracked_exhaustively(self):
        """All occurrences of key repeated terms must be automatically populated."""
        proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        by_canonical = {g["canonical"]: g for g in proposal["suggested_terms"]}

        self.assertGreaterEqual(len(by_canonical["LLM"]["occurrences"]), 35)
        self.assertGreaterEqual(len(by_canonical["Jev"]["occurrences"]), 30)
        self.assertGreaterEqual(len(by_canonical["RAG"]["occurrences"]), 10)
        self.assertGreaterEqual(len(by_canonical["SDLC"]["occurrences"]), 3)
        self.assertGreaterEqual(len(by_canonical["LangTalks"]["occurrences"]), 2)

    def test_duplicate_prevention_on_compound_phrases(self):
        """Compound phrases must not double-count nested sub-terms at the exact same span."""
        proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        claude_code = next(g for g in proposal["suggested_terms"] if g["canonical"] == "Claude Code")
        self.assertEqual(len(claude_code["occurrences"]), 1)
        cc_occ = claude_code["occurrences"][0]

        # Claude standalone must not claim the exact same span as Claude Code
        claude = next((g for g in proposal["suggested_terms"] if g["canonical"] == "Claude"), None)
        if claude:
            self.assertFalse(any(abs(o["start"] - cc_occ["start"]) < 0.5 for o in claude["occurrences"]))

    def test_ambiguous_canonicalization_safeguard(self):
        """Generic terms like CLI must not be blindly promoted to OneCLI in unrelated contexts."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_srt = Path(tmp) / "sample.srt"
            tmp_srt.write_text(
                "1\n00:00:01,000 --> 00:00:04,000\nאנחנו משתמשים ב-CLI גנרי כאן\n\n"
                "2\n00:00:04,000 --> 00:00:08,000\nוהמוצר OneCLI עושה אותנטיקציה\n",
                encoding="utf-8",
            )
            # When processing arbitrary text, OneCLI and CLI remain distinct
            content = tmp_srt.read_text(encoding="utf-8")
            self.assertIn("CLI", content)
            self.assertIn("OneCLI", content)
            # In Ep 74 itself, verify neither CLI nor OneCLI was invented
            proposal = extract_reference_candidates(
                self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
            )
            canonicals = {g["canonical"] for g in proposal["suggested_terms"]}
            self.assertNotIn("OneCLI", canonicals)
            self.assertNotIn("CLI", canonicals)

    def test_srt_timestamp_precision_labels(self):
        """Token-aligned words receive asr_token_aligned; interpolated words receive appropriate precision."""
        c_tokens = [
            {"text": "ההרנס", "start": 24.13, "end": 24.49},
            {"text": "שלכם,", "start": 24.49, "end": 25.03},
        ]
        cue_text = "מחליף לכם בכלל את כל ההרנס שלכם,"
        idx = cue_text.find("ההרנס")
        s, e, prec = _align_term_in_cue(cue_text, (idx, idx + len("ההרנס")), c_tokens, 20.0, 26.0)
        self.assertEqual(prec, "asr_token_aligned")
        self.assertAlmostEqual(s, 24.13, places=2)
        self.assertAlmostEqual(e, 24.49, places=2)

    def test_dataset_isolation_invariants(self):
        """Datasets A, B, and C must remain distinct and immutable."""
        a = json.loads(self.glossary_a_path.read_text(encoding="utf-8"))
        b = json.loads(self.detected_b_path.read_text(encoding="utf-8"))
        c = json.loads(self.proposed_c_path.read_text(encoding="utf-8"))

        self.assertEqual(a["protocol_layer"], "A")
        self.assertEqual(b["protocol_layer"], "B")
        self.assertEqual(c["protocol_layer"], "C")

        self.assertIn("ordered_terms", a)
        self.assertIn("combined_candidate_terms", b)
        self.assertIn("suggested_terms", c)

        # Original raw provider outputs in evaluation directory must exist
        self.assertTrue((self.eval_dir / "provider_ivrit.original.json").exists())
        self.assertTrue((self.eval_dir / "provider_soniox.original.json").exists())
        self.assertTrue((self.eval_dir / "hybrid_revised.original.json").exists())

    def test_review_html_self_contained_bundle(self):
        """Generated HTML must bundle proposal and transcript without remote dependencies."""
        proposal = json.loads(self.proposed_c_path.read_text(encoding="utf-8"))
        transcript = json.loads((self.eval_dir / "reference_transcript.agent_ready.json").read_text(encoding="utf-8"))
        html = build_review_html(proposal, transcript, "audio.mp3")

        self.assertIn("window.__localReviewProposal", html)
        self.assertIn("window.__localAgentTranscript", html)
        self.assertIn("audio.mp3", html)
        self.assertIn("Bulk Approve Confident", html)
        self.assertIn("Exceptions & Uncertain", html)
        self.assertIn("Migrated & Reassigned", html)
        self.assertIn("Reset to Fresh Proposals", html)
        self.assertIn("Export Approved Reference", html)

    def test_end_to_end_saved_review_session_migration(self):
        """End-to-end migration of a complete realistic saved review session JSON.

        Verifies:
        1. Approved occurrences reassigned to refined concepts become 'pending' with 'reapproval_required'.
        2. Rejected occurrences remain 'rejected' regardless of reassignment.
        3. Approved occurrences that remain in the same concept stay 'confirmed'.
        4. Manual concepts and occurrences survive completely with states and notes.
        5. User notes on all occurrences survive untouched.
        6. Global session settings (e.g. listened=True) survive.
        """
        saved_session = {
            "review_session": True,
            "episode_guid": "0e404ceb-d04b-4818-907d-a74aafa7c155",
            "episode_title": "74 - Jev",
            "listened": True,
            "term_groups": [
                {
                    "id": 1,
                    "canonical": "AI agent",
                    "term": "AI agent",
                    "kind": "technical_concept",
                    "occurrences": [
                        {
                            "id": 1,
                            "start": 1424.73,
                            "end": 1426.0,
                            "source_cue_id": "turn-0222",
                            "surface": "ב-agents MD",
                            "state": "confirmed",
                            "notes": "Spoken filename agents.md",
                        },
                        {
                            "id": 2,
                            "start": 1432.03,
                            "end": 1433.5,
                            "source_cue_id": "turn-0223",
                            "surface": "האג'נטס MD",
                            "state": "confirmed",
                            "notes": "Second mention of agents.md",
                        },
                        {
                            "id": 3,
                            "start": 1012.61,
                            "end": 1014.0,
                            "source_cue_id": "turn-0160",
                            "surface": "סאב אייג'נט",
                            "state": "confirmed",
                            "notes": "Distinct subagent architecture",
                        },
                        {
                            "id": 4,
                            "start": 1033.15,
                            "end": 1034.5,
                            "source_cue_id": "turn-0162",
                            "surface": "איג'נטיק סארץ'",
                            "state": "confirmed",
                            "notes": "Agentic search concept",
                        },
                        {
                            "id": 5,
                            "start": 557.43,
                            "end": 558.5,
                            "source_cue_id": "turn-0089",
                            "surface": "לאג'נט",
                            "state": "confirmed",
                            "notes": "Core AI agent mention",
                        },
                        {
                            "id": 6,
                            "start": 622.35,
                            "end": 623.5,
                            "source_cue_id": "turn-0099",
                            "surface": "האג'נט",
                            "state": "rejected",
                            "notes": "Rejected by reviewer: casual phrasing",
                        },
                        {
                            "id": 7,
                            "start": 552.47,
                            "end": 554.0,
                            "source_cue_id": "turn-0088",
                            "surface": "האג'נטיק סרצ'",
                            "state": "rejected",
                            "notes": "Rejected under AI agent: this is search, not an agent",
                        },
                    ],
                },
                {
                    "id": 2,
                    "canonical": "harness",
                    "term": "harness",
                    "kind": "technical_concept",
                    "occurrences": [
                        {
                            "id": 10,
                            "start": 24.13,
                            "end": 25.0,
                            "source_cue_id": "turn-0004",
                            "surface": "ההרנס",
                            "state": "confirmed",
                            "notes": "Spoken harness loanword",
                        },
                        {
                            "id": 11,
                            "start": 1587.51,
                            "end": 1588.5,
                            "source_cue_id": "turn-0246",
                            "surface": "agent harness",
                            "state": "confirmed",
                            "notes": "Agent harness composite",
                        },
                    ],
                },
                {
                    "id": 99,
                    "canonical": "Custom Manual Concept",
                    "term": "Custom Manual Concept",
                    "kind": "architectural_pattern",
                    "editorial_reason": "Manually entered pattern during review",
                    "occurrences": [
                        {
                            "id": 9901,
                            "start": 450.0,
                            "end": 452.0,
                            "source_cue_id": "manual",
                            "surface": "Custom Pattern Expression",
                            "state": "confirmed",
                            "notes": "Identified manually from audio",
                            "manual": True,
                        }
                    ],
                },
            ],
        }

        new_proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        migrated = migrate_review_session(saved_session, new_proposal)

        # 1. Global state preserved
        self.assertTrue(migrated["listened"])

        # 2. AGENTS.md occurrences (reassigned from AI agent) must require renewed approval
        agents_md = next(g for g in migrated["term_groups"] if g["canonical"] == "AGENTS.md")
        occ_222 = next(o for o in agents_md["occurrences"] if o["source_cue_id"] == "turn-0222")
        self.assertEqual(occ_222["state"], "pending")
        self.assertTrue(occ_222.get("reapproval_required"))
        self.assertEqual(occ_222.get("migrated_from"), "AI agent")
        self.assertEqual(occ_222.get("notes"), "Spoken filename agents.md")

        occ_223 = next(o for o in agents_md["occurrences"] if o["source_cue_id"] == "turn-0223")
        self.assertEqual(occ_223["state"], "pending")
        self.assertTrue(occ_223.get("reapproval_required"))
        self.assertEqual(occ_223.get("migrated_from"), "AI agent")
        self.assertEqual(occ_223.get("notes"), "Second mention of agents.md")

        # 3. Subagent occurrence (reassigned from AI agent) must require renewed approval
        subagent = next(g for g in migrated["term_groups"] if g["canonical"] == "Subagent")
        occ_160 = next(o for o in subagent["occurrences"] if o["source_cue_id"] == "turn-0160")
        self.assertEqual(occ_160["state"], "pending")
        self.assertTrue(occ_160.get("reapproval_required"))
        self.assertEqual(occ_160.get("migrated_from"), "AI agent")
        self.assertEqual(occ_160.get("notes"), "Distinct subagent architecture")

        # 4. Agentic search occurrence (reassigned from AI agent) must require renewed approval
        agentic_search = next(g for g in migrated["term_groups"] if g["canonical"] == "Agentic search")
        occ_162 = next(
            o for o in agentic_search["occurrences"]
            if o["source_cue_id"] == "turn-0162" and abs(float(o["start"]) - 1033.15) < 0.5
        )
        self.assertEqual(occ_162["state"], "pending")
        self.assertTrue(occ_162.get("reapproval_required"))
        self.assertEqual(occ_162.get("migrated_from"), "AI agent")
        self.assertEqual(occ_162.get("notes"), "Agentic search concept")

        # 5. Agentic search occurrence (reassigned from rejected in AI agent) must require fresh decision!
        occ_88 = next(o for o in agentic_search["occurrences"] if o["source_cue_id"] == "turn-0088")
        self.assertEqual(occ_88["state"], "pending")
        self.assertTrue(occ_88.get("reapproval_required"))
        self.assertEqual(occ_88.get("previously_rejected_under"), "AI agent")
        self.assertEqual(occ_88.get("migrated_from"), "AI agent")

        # 6. Agent harness occurrence (reassigned from harness) must require renewed approval
        agent_harness = next(g for g in migrated["term_groups"] if g["canonical"] == "Agent harness")
        occ_246 = next(o for o in agent_harness["occurrences"] if o["source_cue_id"] == "turn-0246")
        self.assertEqual(occ_246["state"], "pending")
        self.assertTrue(occ_246.get("reapproval_required"))
        self.assertEqual(occ_246.get("migrated_from"), "harness")
        self.assertEqual(occ_246.get("notes"), "Agent harness composite")

        # 7. Non-reassigned approved occurrences must remain confirmed
        ai_agent = next(g for g in migrated["term_groups"] if g["canonical"] == "AI agent")
        occ_89 = next(o for o in ai_agent["occurrences"] if o["source_cue_id"] == "turn-0089")
        self.assertEqual(occ_89["state"], "confirmed")
        self.assertIsNone(occ_89.get("migrated_from"))
        self.assertEqual(occ_89.get("notes"), "Core AI agent mention")

        harness = next(g for g in migrated["term_groups"] if g["canonical"] == "harness")
        occ_4 = next(o for o in harness["occurrences"] if o["source_cue_id"] == "turn-0004")
        self.assertEqual(occ_4["state"], "confirmed")
        self.assertIsNone(occ_4.get("migrated_from"))
        self.assertEqual(occ_4.get("notes"), "Spoken harness loanword")

        # 8. Non-reassigned rejected occurrences must remain rejected
        occ_99 = next(o for o in ai_agent["occurrences"] if o["source_cue_id"] == "turn-0099")
        self.assertEqual(occ_99["state"], "rejected")
        self.assertEqual(occ_99.get("notes"), "Rejected by reviewer: casual phrasing")

        # 9. Manual additions must survive completely
        custom_group = next(
            (g for g in migrated["term_groups"] if g["canonical"] == "Custom Manual Concept"), None
        )
        self.assertIsNotNone(custom_group)
        self.assertEqual(len(custom_group["occurrences"]), 1)
        manual_occ = custom_group["occurrences"][0]
        self.assertTrue(manual_occ.get("manual"))
        self.assertEqual(manual_occ.get("state"), "confirmed")
        self.assertEqual(manual_occ.get("surface"), "Custom Pattern Expression")
        self.assertEqual(manual_occ.get("notes"), "Identified manually from audio")
        self.assertEqual(manual_occ.get("start"), 450.0)

        # 10. Bulk Approve Confident must NOT approve reassigned or re-approval items
        approved_count = bulk_approve_confident(migrated)
        self.assertGreater(approved_count, 0)
        # Reassigned occurrences must STILL be pending!
        self.assertEqual(occ_222["state"], "pending")
        self.assertEqual(occ_223["state"], "pending")
        self.assertEqual(occ_160["state"], "pending")
        self.assertEqual(occ_162["state"], "pending")
        self.assertEqual(occ_88["state"], "pending")
        self.assertEqual(occ_246["state"], "pending")
        # Same-concept rejected occurrence must STILL be rejected!
        self.assertEqual(occ_99["state"], "rejected")

        # 11. Reference Export lifecycle: pending before complete, approved when verified
        transcript = json.loads((self.eval_dir / "reference_transcript.agent_ready.json").read_text(encoding="utf-8"))
        ref_pending = export_approved_reference(migrated, transcript)
        self.assertEqual(ref_pending["review_status"], "pending")
        self.assertFalse(ref_pending["terms_exhaustive"])

        # Explicitly confirm all remaining pending items and verify approved export
        for g in migrated["term_groups"]:
            for o in g["occurrences"]:
                if o["state"] == "pending":
                    o["state"] = "confirmed"
        migrated["listened"] = True

        ref_approved = export_approved_reference(migrated, transcript)
        self.assertEqual(ref_approved["review_status"], "approved")
        self.assertTrue(ref_approved["terms_exhaustive"])
        self.assertGreaterEqual(len(ref_approved["verified_occurrences"]), 300)

    def test_multi_term_cue_isolation_prevents_unrelated_pairing(self):
        """Migration matching must never pair unrelated terms merely because they share a cue."""
        # Cue turn-0004 contains: 'RAG', 'SDLC', and 'ההרנס' (harness)
        # Saved session only reviewed 'RAG' in turn-0004
        saved_session = {
            "review_session": True,
            "listened": False,
            "term_groups": [
                {
                    "canonical": "RAG",
                    "occurrences": [
                        {
                            "start": 21.0,
                            "source_cue_id": "turn-0004",
                            "surface": "RAG",
                            "state": "confirmed",
                            "notes": "Reviewed RAG in cue 4",
                        }
                    ],
                }
            ],
        }

        new_proposal = extract_reference_candidates(
            self.srt_path, self.hybrid_path, self.glossary_a_path, self.detected_b_path
        )
        migrated = migrate_review_session(saved_session, new_proposal)

        # 1. RAG in turn-0004 must be matched and confirmed
        rag_group = next(g for g in migrated["term_groups"] if g["canonical"] == "RAG")
        rag_occ = next(o for o in rag_group["occurrences"] if o["source_cue_id"] == "turn-0004")
        self.assertEqual(rag_occ["state"], "confirmed")
        self.assertEqual(rag_occ.get("notes"), "Reviewed RAG in cue 4")

        # 2. SDLC in turn-0004 must NOT be paired with RAG; must remain fresh 'pending'
        sdlc_group = next(g for g in migrated["term_groups"] if g["canonical"] == "SDLC")
        sdlc_occ = next(o for o in sdlc_group["occurrences"] if o["source_cue_id"] == "turn-0004")
        self.assertEqual(sdlc_occ["state"], "pending")
        self.assertIsNone(sdlc_occ.get("migrated_from"))
        self.assertFalse(sdlc_occ.get("reassigned", False))

        # 3. harness in turn-0004 must NOT be paired with RAG; must remain fresh 'pending'
        harness_group = next(g for g in migrated["term_groups"] if g["canonical"] == "harness")
        harness_occ = next(o for o in harness_group["occurrences"] if o["source_cue_id"] == "turn-0004")
        self.assertEqual(harness_occ["state"], "pending")
        self.assertIsNone(harness_occ.get("migrated_from"))
        self.assertFalse(harness_occ.get("reassigned", False))

    def test_browser_js_migration_bulk_approve_and_export_lifecycle(self):
        """Execute the browser JavaScript review engine in Node.js to verify browser-side fidelity."""
        proposal = json.loads(self.proposed_c_path.read_text(encoding="utf-8"))
        transcript = json.loads((self.eval_dir / "reference_transcript.agent_ready.json").read_text(encoding="utf-8"))
        html = build_review_html(proposal, transcript, "audio.mp3")

        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(html)
            temp_html_path = f.name

        node_script = f"""
        const fs = require('fs');
        const html = fs.readFileSync({json.dumps(temp_html_path)}, 'utf8');
        
        // Extract script content
        const scriptMatch = html.match(/<script>([\\s\\S]*?)<\\/script>/);
        if(!scriptMatch) throw new Error("No script block found in review HTML");
        const scriptContent = scriptMatch[1];

        // Mock browser DOM and environment
        let lastDownloaded = null;
        global.URL = {{
            createObjectURL: (blob) => {{
                lastDownloaded = {{ blob, data: blob?.data }};
                return "blob:mock";
            }},
            revokeObjectURL: () => {{}}
        }};
        global.Blob = class {{
            constructor(parts, opts){{
                this.parts = parts;
                this.opts = opts;
                try {{
                    this.text = parts.join("");
                    this.data = JSON.parse(this.text);
                }} catch(e){{}}
            }}
        }};
        const mockElements = {{}};
        const $ = id => mockElements[id] || (mockElements[id] = {{ onclick: null, value: "", style: {{}}, checked: false, replaceChildren: ()=>{{}}, append: ()=>{{}} }});
        const document = {{
            getElementById: $,
            createElement: tag => ({{ style: {{}}, setAttribute: ()=>{{}}, append: ()=>{{}}, replaceChildren: ()=>{{}}, click: ()=>{{}} }}),
            createTextNode: text => ({{ textContent: text }}),
            addEventListener: ()=>{{}}
        }};
        const window = {{}};
        const localStorage = {{ getItem: ()=>null, setItem: ()=>{{}}, removeItem: ()=>{{}} }};
        const audio = {{ load: ()=>{{}}, play: ()=>{{}}, pause: ()=>{{}} }};
        let statusText = "";
        function status(s){{ statusText = s; }}

        // Evaluate script in context
        eval(scriptContent);

        // Test saved session import
        const savedSession = {{
            review_session: true,
            listened: true,
            term_groups: [
                {{
                    canonical: "AI agent",
                    occurrences: [
                        {{ start: 1424.73, source_cue_id: "turn-0222", surface: "ב-agents MD", state: "confirmed", notes: "Note agents.md" }},
                        {{ start: 552.47, source_cue_id: "turn-0088", surface: "האג'נטיק סרצ'", state: "rejected", notes: "Search not agent" }},
                        {{ start: 557.43, source_cue_id: "turn-0089", surface: "לאג'נט", state: "confirmed", notes: "Core agent" }}
                    ]
                }}
            ]
        }};

        const migrated = window.migrateReviewSession(savedSession, window.__localReviewProposal);
        
        // Check reassigned approved -> pending
        const agentsMd = migrated.term_groups.find(g => g.canonical === "AGENTS.md");
        const occ222 = agentsMd.occurrences.find(o => o.source_cue_id === "turn-0222");
        if(occ222.state !== "pending") throw new Error("JS error: occ222 should be pending, got " + occ222.state);
        if(!occ222.reapproval_required) throw new Error("JS error: occ222 reapproval_required missing");

        // Check reassigned rejected -> pending with previously_rejected_under
        const agenticSearch = migrated.term_groups.find(g => g.canonical === "Agentic search");
        const occ88 = agenticSearch.occurrences.find(o => o.source_cue_id === "turn-0088");
        if(occ88.state !== "pending") throw new Error("JS error: occ88 should be pending, got " + occ88.state);
        if(occ88.previously_rejected_under !== "AI agent") throw new Error("JS error: occ88 previously_rejected_under missing");

        // Check same concept confirmed -> confirmed
        const aiAgent = migrated.term_groups.find(g => g.canonical === "AI agent");
        const occ89 = aiAgent.occurrences.find(o => o.source_cue_id === "turn-0089");
        if(occ89.state !== "confirmed") throw new Error("JS error: occ89 should be confirmed, got " + occ89.state);

        // Test bulk approve safeguard in JS: loadData and trigger bulkApprove
        window.loadData(migrated);
        mockElements["bulkApprove"].onclick();

        // Verify bulk approve did NOT touch reassigned items
        if(occ222.state !== "pending") throw new Error("JS safeguard failed: occ222 was bulk approved!");
        if(occ88.state !== "pending") throw new Error("JS safeguard failed: occ88 was bulk approved!");

        // Test reference export in JS: when pending exist
        mockElements["listened"].checked = false;
        mockElements["exportRef"].onclick();
        if(!lastDownloaded || lastDownloaded.data.review_status !== "pending"){{
            throw new Error("JS export status should be pending when listened is unchecked and pending exist");
        }}

        // Approve all remaining pending occurrences and check listened:
        for(const g of migrated.term_groups){{
            for(const o of g.occurrences){{
                if(o.state === "pending") o.state = "confirmed";
            }}
        }}
        mockElements["listened"].checked = true;
        mockElements["exportRef"].onclick();
        if(!lastDownloaded || lastDownloaded.data.review_status !== "approved"){{
            throw new Error("JS export status should be approved when all decided and listened checked");
        }}

        console.log("NODE_JS_VERIFICATION_SUCCESS");
        """

        try:
            res = subprocess.run(["node"], input=node_script, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Node script failed: {res.stderr}\nSTDOUT: {res.stdout}")
            self.assertIn("NODE_JS_VERIFICATION_SUCCESS", res.stdout)
        finally:
            Path(temp_html_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
