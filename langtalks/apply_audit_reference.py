"""Apply ChatGPT's independent semantic audit to create the defensible Reference C.

Integrates:
- Validation of audit JSON against proposed Layer C reference.
- Occurrence-level semantic corrections (reassignments, splits, exclusions, expansions, retimings).
- Evaluation of the 45 candidate suggestions against the authoritative transcript.
- Strict concept-identity rules (distinguishing exact concepts from adjectives, idioms, subtypes).
- Faithful Hebrew morphology, surfaces, and cross-script mappings.
- Explicit provenance documenting human transcript correction vs assistant text-based semantic audit.
- Full compatibility with both reference_review UI and score.py / strict_occurrence.py.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .reference_extraction import _align_term_in_cue, parse_srt

EVAL_DIR = Path(__file__).resolve().parent / "evaluations/0e404ceb-d04b-4818-907d-a74aafa7c155"


def load_audit_and_proposal(
    eval_dir: Path = EVAL_DIR,
    audit_path: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Load and validate all inputs needed for Reference C construction."""
    if audit_path is None:
        audit_path = Path("/home/dan/.gemini/antigravity-cli/brain/27f67f0b-31b6-467b-9f61-2fa19b93c23b/scratch/audit/ep74_semantic_audit.json")

    proposed_path = eval_dir / "reference_terms.proposed.json"
    srt_path = eval_dir / "reference_user_corrected.original.srt"
    transcript_json_path = eval_dir / "reference_transcript.agent_ready.json"
    hybrid_path = eval_dir / "hybrid_revised.original.json"

    proposal = json.loads(proposed_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    srt_content = srt_path.read_text(encoding="utf-8-sig")
    cues = parse_srt(srt_content)
    transcript_json = json.loads(transcript_json_path.read_text(encoding="utf-8"))
    hybrid_tokens = json.loads(hybrid_path.read_text(encoding="utf-8")).get("tokens", [])

    return proposal, audit, cues, transcript_json, hybrid_tokens


def validate_audit_against_proposal(proposal: Dict[str, Any], audit: Dict[str, Any]) -> List[str]:
    """Validate that every occurrence in audit matches proposal exactly."""
    prop_occs = {}
    for term in proposal.get("suggested_terms", []):
        for occ in term.get("occurrences", []):
            prop_occs[occ["id"]] = (term, occ)

    errors = []
    if proposal.get("episode_guid") != audit.get("episode_guid"):
        errors.append(f"Episode GUID mismatch: {proposal.get('episode_guid')} vs {audit.get('episode_guid')}")

    for rev in audit.get("occurrence_reviews", []):
        occ_id = rev["occurrence_id"]
        if occ_id not in prop_occs:
            errors.append(f"Occurrence {occ_id} from audit not found in proposal")
            continue
        term, occ = prop_occs[occ_id]
        if term["canonical"] != rev["existing_canonical"]:
            errors.append(f"Canonical mismatch for occ {occ_id}: {term['canonical']} vs {rev['existing_canonical']}")
        if occ["surface"] != rev["surface"]:
            errors.append(f"Surface mismatch for occ {occ_id}: {occ['surface']} vs {rev['surface']}")
        if occ["source_cue_id"] != rev["source_cue_id"]:
            errors.append(f"Cue mismatch for occ {occ_id}: {occ['source_cue_id']} vs {rev['source_cue_id']}")
        if abs(occ["start"] - rev["start_s"]) > 0.05:
            errors.append(f"Start time mismatch for occ {occ_id}: {occ['start']} vs {rev['start_s']}")

    return errors


def build_reference_c(
    eval_dir: Path = EVAL_DIR,
    audit_path: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Construct versioned, frozen Reference C and detailed validation/audit log."""
    proposal, audit, cues, transcript_json, hybrid_tokens = load_audit_and_proposal(eval_dir, audit_path)
    val_errors = validate_audit_against_proposal(proposal, audit)
    if val_errors:
        raise ValueError(f"Audit failed validation against proposal: {val_errors}")

    cues_by_id = {f"turn-{idx:04d}": c for idx, c in enumerate(cues, 1)}

    # Track occurrences by id
    all_occurrences: Dict[int, Dict[str, Any]] = {}
    occ_to_canonical: Dict[int, str] = {}
    for g in proposal["suggested_terms"]:
        for o in g["occurrences"]:
            occ_copy = deepcopy(o)
            occ_copy["review_status"] = "verified"
            occ_copy["validation_level"] = "assistant_textual_audit_not_audio_verified"
            all_occurrences[o["id"]] = occ_copy
            occ_to_canonical[o["id"]] = g["canonical"]

    audit_changelog = []
    benchmark_exclusions = []

    # 1. Apply occurrence reviews from audit
    for rev in audit["occurrence_reviews"]:
        occ_id = rev["occurrence_id"]
        v = rev["semantic_review"]
        occ = all_occurrences[occ_id]

        if v == "plausible_from_approved_transcript":
            continue

        audit_changelog.append({
            "occurrence_id": occ_id,
            "verdict": v,
            "old_canonical": occ_to_canonical[occ_id],
            "new_canonical": rev.get("suggested_canonical") or occ_to_canonical[occ_id],
            "old_surface": occ["surface"],
            "reason": rev["reason"],
        })

        if v == "preserve_surface_inflection":
            # Occs 54, 59, 61, 183: LLM -> LLM'ים
            occ["surface"] = "LLM'ים"
            occ["matched_text"] = "LLM'ים"
            occ["hebrew_morphology"] = {"prefix": None, "stem": "LLM", "suffix": "'ים"}

        elif v == "reassign":
            new_canon = rev["suggested_canonical"]
            if new_canon == "Agentic behavior / agentic adjective":
                occ_to_canonical[occ_id] = "Agentic behavior"
            elif new_canon == "Boolean literal":
                occ_to_canonical[occ_id] = "Boolean literal"
                # Fix timing for turn-0019 true/false
                if occ_id == 36:
                    occ["start"], occ["end"] = 118.19, 118.43
                elif occ_id == 38:
                    occ["start"], occ["end"] = 118.61, 118.71
                elif occ_id == 37:
                    occ["start"], occ["end"] = 118.87, 118.99
            elif new_canon == "Thinking / reasoning mode":
                occ_to_canonical[occ_id] = "Thinking / reasoning mode"
                if occ_id == 235:
                    occ["start"], occ["end"] = 1314.99, 1315.25
                elif occ_id == 236:
                    occ["start"], occ["end"] = 1315.63, 1315.89
            elif new_canon == "Hugging Face":
                occ_to_canonical[occ_id] = "Hugging Face"
            elif new_canon == "Text features":
                occ_to_canonical[occ_id] = "Text features"
            elif new_canon == "Model-based judging / classification":
                occ_to_canonical[occ_id] = "Model-based judging"
            else:
                occ_to_canonical[occ_id] = new_canon

        elif v == "split":
            # Occ 28: "true false" in turn-0014 -> split into true (occ 28) and false (new occ 331)
            occ_to_canonical[occ_id] = "Boolean literal"
            occ["surface"] = "true"
            occ["matched_text"] = "true"
            occ["start"], occ["end"] = 86.43, 86.67
            occ["timestamp_precision"] = "asr_token_aligned"

            # Create new occurrence for false
            new_occ_id = 331
            all_occurrences[new_occ_id] = {
                "id": new_occ_id,
                "start": 86.67,
                "end": 87.03,
                "timestamp_precision": "asr_token_aligned",
                "source_cue_id": "turn-0014",
                "cue_start": 84.61,
                "cue_end": 90.05,
                "surface": "false",
                "matched_text": "false",
                "context": occ["context"],
                "sources": occ["sources"],
                "state": "confirmed",
                "manual": False,
                "review_status": "verified",
                "validation_level": "assistant_textual_audit_not_audio_verified",
            }
            occ_to_canonical[new_occ_id] = "Boolean literal"

        elif v == "exclude_nested":
            # Occ 199: tokens inside thinking tokens
            benchmark_exclusions.append({
                "occurrence_id": occ_id,
                "expression": occ["surface"],
                "canonical": occ_to_canonical[occ_id],
                "source_cue_id": occ["source_cue_id"],
                "start": occ["start"],
                "end": occ["end"],
                "reason": "Nested inside multiword expression 'thinking tokens' in turn-0182; excluded to prevent double counting.",
            })
            del all_occurrences[occ_id]
            del occ_to_canonical[occ_id]

        elif v == "expand_surface":
            if occ_id == 186:
                occ_to_canonical[occ_id] = "Gemini 3.8 Flash"
                occ["surface"] = "ג'מיני 3.8 Flash"
                occ["matched_text"] = "ג'מיני 3.8 Flash"
                occ["start"], occ["end"] = 1113.67, 1115.99
                occ["hebrew_morphology"] = {"prefix": None, "stem": "ג'מיני 3.8 Flash"}
            elif occ_id == 198:
                occ["surface"] = "ה-thinking tokens"
                occ["matched_text"] = "ה-thinking tokens"
                occ["start"], occ["end"] = 1162.43, 1163.25
                occ["hebrew_morphology"] = {"prefix": "ה-", "stem": "thinking tokens"}

        elif v == "cross_cue_check":
            # Occ 227: Gemini Flash across turn-0198 and turn-0199
            occ["surface"] = "ג'מיני Flash"
            occ["matched_text"] = "ג'מיני Flash"
            occ["start"], occ["end"] = 1268.51, 1269.79
            occ["source_cue_id"] = "turn-0198…turn-0199"
            occ["hebrew_morphology"] = {"prefix": None, "stem": "ג'מיני Flash"}

        elif v == "expand_cross_cue":
            # Occ 175: Bulk operations across turn-0164 and turn-0165
            occ["surface"] = "לבאלק אופריישנס"
            occ["matched_text"] = "לבאלק אופריישנס"
            occ["start"], occ["end"] = 1046.79, 1050.69
            occ["source_cue_id"] = "turn-0164…turn-0165"
            occ["hebrew_morphology"] = {"prefix": "ל-", "stem": "באלק אופריישנס"}

        elif v == "reassign_expand":
            # Occ 240: browser use
            occ_to_canonical[occ_id] = "Browser use"
            occ["surface"] = "browser use"
            occ["matched_text"] = "browser use"
            occ["start"], occ["end"] = 1339.01, 1339.97

        elif v == "retime_distinct_mentions":
            if occ_id == 288:
                occ["start"], occ["end"] = 1563.31, 1563.63
            elif occ_id == 289:
                occ["start"], occ["end"] = 1563.63, 1564.07

        elif v == "scope_check":
            # Occs 63, 107, 228, 330: general-purpose conversational idioms
            benchmark_exclusions.append({
                "occurrence_id": occ_id,
                "expression": occ["surface"],
                "canonical": occ_to_canonical[occ_id],
                "source_cue_id": occ["source_cue_id"],
                "start": occ["start"],
                "end": occ["end"],
                "reason": f"General conversational idiom ({occ_to_canonical[occ_id]}); excluded from strict technical concept inventory per protocol Section 4.",
            })
            del all_occurrences[occ_id]
            del occ_to_canonical[occ_id]

        elif v == "rename_specific":
            # Occ 229: GPT-5.6
            occ_to_canonical[occ_id] = "GPT-5.6"

        elif v == "exclude_or_reassign":
            # Occ 276: Law
            occ_to_canonical[occ_id] = "Law"

        elif v == "identity_check":
            if occ_id == 134:
                occ_to_canonical[occ_id] = "confidence"
                occ["surface"] = "ה-confident"
                occ["hebrew_morphology"] = {"prefix": "ה-", "stem": "confident"}
            elif occ_id == 137:
                # -pobability: retain explicit uncertainty
                occ["uncertainty_flag"] = True
                occ["unresolved_reason"] = "Transcript has -pobability; spoken slip or cross-cue prefix detachment."
            elif occ_id == 270:
                # רלבילי: reliable adjective
                occ_to_canonical[occ_id] = "reliable / reliability"
                occ["uncertainty_flag"] = True
                occ["unresolved_reason"] = "Spoken as Hebrewized adjective רלבילי (reliable) rather than noun Reliability."
            elif occ_id == 328:
                occ_to_canonical[occ_id] = "LangTalks"
                occ["is_url"] = True

    # Rename canonical "confidence score" to "confidence" across all remaining occurrences
    for oid, c in list(occ_to_canonical.items()):
        if c == "confidence score":
            occ_to_canonical[oid] = "confidence"

    # 2. Add verified occurrences from audit candidate suggestions
    accepted_suggestions_meta = [
        # (index, canonical, surface, cue_id, start, end, precision, hebrew_morph)
        (0, "use case", "יוזקיסים", "turn-0033", 206.68, 207.53, "approximate_character_interpolated", {"prefix": None, "stem": "יוזקיס", "suffix": "ים"}),
        (1, "use case", "יוז קייס", "turn-0166", 1058.99, 1059.37, "asr_token_aligned", {"prefix": None, "stem": "יוז קייס"}),
        (2, "use case", "יוז קייסים", "turn-0172", 1095.14, 1096.01, "approximate_character_interpolated", {"prefix": None, "stem": "יוז קייס", "suffix": "ים"}),
        (3, "use case", "יוז קייסים", "turn-0226", 1453.62, 1454.51, "approximate_character_interpolated", {"prefix": None, "stem": "יוז קייס", "suffix": "ים"}),
        (4, "use case", "יוז קייסים", "turn-0285", 1827.81, 1828.64, "approximate_character_interpolated", {"prefix": None, "stem": "יוז קייס", "suffix": "ים"}),
        (5, "repository", "הריפו", "turn-0081", 512.47, 512.91, "asr_token_aligned", {"prefix": "ה-", "stem": "ריפו"}),
        (6, "repository", "ריפוים", "turn-0081", 514.17, 514.59, "asr_token_aligned", {"prefix": None, "stem": "ריפו", "suffix": "ים"}),
        (7, "repository", "ריפואים", "turn-0097", 614.27, 614.79, "asr_token_aligned", {"prefix": None, "stem": "ריפו", "suffix": "אים"}),
        (8, "repository", "ריפואים", "turn-0099", 625.11, 625.61, "asr_token_aligned", {"prefix": None, "stem": "ריפו", "suffix": "אים"}),
        (9, "repository", "ריפואים", "turn-0099", 627.47, 627.95, "asr_token_aligned", {"prefix": None, "stem": "ריפו", "suffix": "אים"}),
        (10, "repository", "ריפואים", "turn-0099", 628.41, 628.89, "asr_token_aligned", {"prefix": None, "stem": "ריפו", "suffix": "אים"}),
        (11, "batch", "באץ'", "turn-0038", 235.75, 236.15, "asr_token_aligned", {"prefix": None, "stem": "באץ'"}),
        (12, "benchmark", "בנצ'מארקים", "turn-0201", 1287.21, 1287.89, "asr_token_aligned", {"prefix": None, "stem": "בנצ'מארק", "suffix": "ים"}),
        (13, "benchmark", "בנצ'מארקים", "turn-0202", 1290.67, 1291.23, "asr_token_aligned", {"prefix": None, "stem": "בנצ'מארק", "suffix": "ים"}),
        (14, "state", "ובסטייט", "turn-0010", 64.43, 65.09, "asr_token_aligned", {"prefix": "וב-", "stem": "סטייט"}),
        (15, "token", "טוקן", "turn-0055", 345.53, 346.11, "asr_token_aligned", {"prefix": None, "stem": "טוקן"}),
        (16, "token", "טוקן", "turn-0055", 346.35, 346.77, "asr_token_aligned", {"prefix": None, "stem": "טוקן"}),
        (17, "token", "טוקן", "turn-0178", 1137.27, 1137.61, "asr_token_aligned", {"prefix": None, "stem": "טוקן"}),
        (18, "cache", "קאש", "turn-0040", 254.31, 254.93, "asr_token_aligned", {"prefix": None, "stem": "קאש"}),
        (19, "cache", "קאש היט", "turn-0041", 255.67, 256.29, "asr_token_aligned", {"prefix": None, "stem": "קאש היט"}),
        (20, "labels", "כלייבלים", "turn-0015", 94.65, 95.18, "approximate_character_interpolated", {"prefix": "כ-", "stem": "לייבל", "suffix": "ים"}),
        (21, "labels", "הלייבלים", "turn-0024", 145.22, 145.90, "approximate_character_interpolated", {"prefix": "ה-", "stem": "לייבל", "suffix": "ים"}),
        (22, "latency", "לייטנסיה", "turn-0204", 1308.43, 1308.91, "asr_token_aligned", {"prefix": None, "stem": "לייטנסיה"}),
        (23, "gradual discovery", "gradual discovery", "turn-0093", 587.37, 589.49, "asr_token_aligned", None),
        (24, "tool calling", "tool call", "turn-0217", 1395.75, 1396.23, "asr_token_aligned", None),
        (28, "Gemini", "וג'מיני", "turn-0204", 1304.80, 1305.32, "approximate_character_interpolated", {"prefix": "ו-", "stem": "ג'מיני"}),
        (29, "Gemini", "ג'מיני", "turn-0204", 1310.41, 1312.33, "asr_token_aligned", {"prefix": None, "stem": "ג'מיני"}),
        (31, "context", "הקונטקסט", "turn-0017", 107.53, 108.31, "asr_token_aligned", {"prefix": "ה-", "stem": "קונטקסט"}),
        (32, "context", "קונטקסט", "turn-0032", 195.57, 196.53, "asr_token_aligned", {"prefix": None, "stem": "קונטקסט"}),
        (33, "context", "הקונטקסט", "turn-0072", 453.35, 453.91, "asr_token_aligned", {"prefix": "ה-", "stem": "קונטקסט"}),
        (34, "context", "הקונטקסט", "turn-0103", 652.07, 653.29, "asr_token_aligned", {"prefix": "ה-", "stem": "קונטקסט"}),
        (35, "context", "הקונטקסט", "turn-0145", 920.33, 921.03, "asr_token_aligned", {"prefix": "ה-", "stem": "קונטקסט"}),
        (36, "context", "הקונטקסט", "turn-0151", 956.81, 957.71, "asr_token_aligned", {"prefix": "ה-", "stem": "קונטקסט"}),
        (37, "context", "קונטקסט", "turn-0160", 1014.91, 1015.35, "asr_token_aligned", {"prefix": None, "stem": "קונטקסט"}),
        (38, "Computer use", "computer use", "turn-0208…turn-0209", 1340.27, 1340.93, "asr_token_aligned", None),
    ]

    next_new_id = 332
    for s_idx, canon, surf, cid, start_s, end_s, prec, morph in accepted_suggestions_meta:
        cue = cues_by_id.get(cid.split("…")[0], {})
        occ_id = next_new_id
        next_new_id += 1
        occ_record = {
            "id": occ_id,
            "start": start_s,
            "end": end_s,
            "timestamp_precision": prec,
            "source_cue_id": cid,
            "cue_start": cue.get("start", start_s),
            "cue_end": cue.get("end", end_s),
            "surface": surf,
            "matched_text": surf,
            "context": cue.get("text", ""),
            "sources": ["user_corrected_srt", "chatgpt_semantic_audit"],
            "state": "confirmed",
            "manual": True,
            "review_status": "verified",
            "validation_level": "assistant_textual_audit_not_audio_verified",
        }
        if morph:
            occ_record["hebrew_morphology"] = morph
        all_occurrences[occ_id] = occ_record
        occ_to_canonical[occ_id] = canon

        audit_changelog.append({
            "occurrence_id": occ_id,
            "verdict": "added_from_candidate_suggestion",
            "old_canonical": None,
            "new_canonical": canon,
            "old_surface": None,
            "new_surface": surf,
            "suggestion_index": s_idx,
            "cue": cid,
        })

    # Record rejected candidate suggestions
    rejected_suggestions_meta = [
        (25, "browser use", "turn-0208", "Duplicate with Occurrence 240, which was expanded to 'browser use'."),
        (26, "Gemini", "turn-0174", "Nested inside multiword model expression 'ג'מיני 3.8 Flash' (Occ 186)."),
        (27, "Gemini", "turn-0198", "Nested inside cross-cue multiword model expression 'ג'מיני Flash' (Occ 227)."),
        (30, "context", "turn-0010", "Nested inside multiword concept 'context window' (לקונטקסט ווינדוס, Occ 21)."),
    ]
    for s_idx, canon, cid, rej_reason in rejected_suggestions_meta:
        benchmark_exclusions.append({
            "suggestion_index": s_idx,
            "canonical": canon,
            "source_cue_id": cid,
            "reason": rej_reason,
        })

    # 3. Group occurrences into concepts
    concept_map: Dict[str, Dict[str, Any]] = {}

    # Seed metadata from proposal (clearing draft uncertainty flags resolved by audit)
    for g in proposal["suggested_terms"]:
        c = g["canonical"]
        concept_map[c] = {
            "canonical": c,
            "term": c,
            "kind": g.get("kind", "technical_concept"),
            "editorial_reason": g.get("editorial_reason", ""),
            "is_cross_script": g.get("is_cross_script", False),
            "uncertainty_flag": False,
            "surfaces": set(),
            "sources": set(g.get("sources", [])),
            "occurrences": [],
        }

    # Add custom metadata for newly introduced/reassigned concepts
    concept_meta_overrides = {
        "Agentic behavior": {
            "kind": "technical_concept",
            "editorial_reason": "Adjectival descriptions of agentic processes, systems, and solutions (האג'נטי, אג'נטית, אג'נטיים).",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "Boolean literal": {
            "kind": "technical_concept",
            "editorial_reason": "Boolean literal values true / false, distinct from the boolean datatype name.",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "Thinking / reasoning mode": {
            "kind": "technical_concept",
            "editorial_reason": "Thinking / reasoning ability and mode, distinct from the multiword phrase 'thinking tokens'.",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "Hugging Face": {
            "kind": "organization",
            "editorial_reason": "Platform / organization (מהגיד פייס), distinct from Spaces product.",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "Text features": {
            "kind": "technical_concept",
            "editorial_reason": "Textual features in text processing / classification (פיצ'רים).",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "Model-based judging": {
            "kind": "technical_practice",
            "editorial_reason": "Evaluation/judging of agent actions using models/classifiers.",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "Browser use": {
            "kind": "technical_practice",
            "editorial_reason": "Agentic automated browser interaction / browser use.",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "Computer use": {
            "kind": "technical_practice",
            "editorial_reason": "Agentic computer control / OS interaction (computer use).",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "GPT-5.6": {
            "kind": "product",
            "editorial_reason": "Explicitly named model version (gpt 5.6).",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "Gemini 3.8 Flash": {
            "kind": "product",
            "editorial_reason": "Explicitly named model version (ג'מיני 3.8 Flash).",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "Law": {
            "kind": "descriptive_concept",
            "editorial_reason": "Industry vertical / legal domain (בlaw).",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "confidence": {
            "kind": "technical_concept",
            "editorial_reason": "Model classification confidence / probability calibration.",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "cache": {
            "kind": "technical_concept",
            "editorial_reason": "LLM response caching and cache hit mechanics (קאש, קאש היט).",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "labels": {
            "kind": "technical_concept",
            "editorial_reason": "Classification category labels (כלייבלים, הלייבלים).",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "gradual discovery": {
            "kind": "technical_practice",
            "editorial_reason": "Progressive context exploration / retrieval technique.",
            "is_cross_script": False,
            "uncertainty_flag": False,
        },
        "context": {
            "kind": "technical_concept",
            "editorial_reason": "Input context / prompt context for LLMs and classifiers (הקונטקסט, קונטקסט).",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "Gemini": {
            "kind": "product",
            "editorial_reason": "Gemini model family / platform (ג'מיני).",
            "is_cross_script": True,
            "uncertainty_flag": False,
        },
        "reliable / reliability": {
            "kind": "technical_concept",
            "editorial_reason": "Production suitability and reliability (רלבילי).",
            "is_cross_script": True,
            "uncertainty_flag": True,
        },
    }

    for canon, overrides in concept_meta_overrides.items():
        if canon not in concept_map:
            concept_map[canon] = {
                "canonical": canon,
                "term": canon,
                "kind": overrides["kind"],
                "editorial_reason": overrides["editorial_reason"],
                "is_cross_script": overrides["is_cross_script"],
                "uncertainty_flag": overrides["uncertainty_flag"],
                "surfaces": set(),
                "sources": {"user_corrected_srt", "chatgpt_semantic_audit"},
                "occurrences": [],
            }
        else:
            concept_map[canon].update(overrides)

    # Populate occurrences into concepts
    for occ_id, occ in sorted(all_occurrences.items()):
        canon = occ_to_canonical[occ_id]
        c_entry = concept_map[canon]
        c_entry["occurrences"].append(occ)
        c_entry["surfaces"].add(occ["surface"])
        if re.search(r"[\u0590-\u05ff]", occ["surface"]):
            c_entry["is_cross_script"] = True

    # Drop empty concepts (e.g. best in class, double down, sweet spot, Silver bullet, or old confidence score)
    approved_concepts = []
    for canon, c_entry in sorted(concept_map.items(), key=lambda x: (-len(x[1]["occurrences"]), x[0].casefold())):
        if not c_entry["occurrences"]:
            continue
        c_entry["occurrences"].sort(key=lambda o: o["start"])
        c_entry["surfaces"] = sorted(list(c_entry["surfaces"]))
        c_entry["sources"] = sorted(list(c_entry["sources"]))
        approved_concepts.append(c_entry)

    # Re-assign concept IDs
    for idx, c in enumerate(approved_concepts, 1):
        c["id"] = idx
        if len(c["surfaces"]) == 1:
            c["surface"] = c["surfaces"][0]
        else:
            c["surface"] = f"{c['canonical']} ({', '.join(c['surfaces'][:3])})"

    # Prepare flat verified occurrences list for scoring
    verified_occurrences = []
    all_english_expressions = set()
    technical_terms = []

    for c in approved_concepts:
        # Technical terms list includes canonicals and unique surfaces
        technical_terms.append(c["canonical"])
        for s in c["surfaces"]:
            if not re.search(r"[\u0590-\u05ff]", s):
                all_english_expressions.add(s)

        for o in c["occurrences"]:
            verified_occurrences.append({
                "id": o["id"],
                "term": c["canonical"],
                "surface": o["surface"],
                "canonical": c["canonical"],
                "kind": c["kind"],
                "start": o["start"],
                "end": o["end"],
                "timestamp_precision": o["timestamp_precision"],
                "source_cue_id": o["source_cue_id"],
                "source_models": o.get("sources", []),
                "hebrew_morphology": o.get("hebrew_morphology"),
                "review_status": "verified",
                "validation_level": "assistant_textual_audit_not_audio_verified",
                "uncertainty_flag": o.get("uncertainty_flag", c.get("uncertainty_flag", False)),
            })

    verified_occurrences.sort(key=lambda o: o["start"])

    # Detailed concept mentions
    concept_mentions = [
        {
            "id": f"mention-{i+1:04d}",
            "occurrence_id": o["id"],
            "turn_id": o["source_cue_id"],
            "start_s": o["start"],
            "end_s": o["end"],
            "surface": o["surface"],
            "canonical": o["canonical"],
            "kind": o["kind"],
            "hebrew_morphology": o.get("hebrew_morphology"),
            "review_status": "verified",
            "validation_level": o["validation_level"],
            "uncertainty_flag": o["uncertainty_flag"],
        }
        for i, o in enumerate(verified_occurrences)
    ]

    total_occurrences_count = len(verified_occurrences)
    cross_script_count = sum(1 for c in approved_concepts if c.get("is_cross_script"))
    uncertain_count = sum(1 for c in approved_concepts if c.get("uncertainty_flag"))

    reference_text = " ".join(t.get("text", "") for t in transcript_json.get("turns", []))

    reference_c = {
        "protocol_layer": "C",
        "version": "1.0-frozen",
        "description": "Defensible ground-truth reference for Episode 74 held-out evaluation, finalized by applying ChatGPT independent semantic audit to user-corrected transcript.",
        "episode_guid": "0e404ceb-d04b-4818-907d-a74aafa7c155",
        "episode_title": "74 - Jev",
        "audio_url": "audio.mp3",
        "window": {"start": 0.0, "end": 1848.89},
        "review_status": "approved",
        "terms_exhaustive": True,
        "provenance": {
            "transcript_authority": "human_corrected_SRT_subtitle_edit",
            "transcript_file": "reference_user_corrected.original.srt",
            "transcript_sha256": "e5e2245dc8126bfc1fd6394cb6f4bfceeff06851ce1471fcb583cdd1365a5d53",
            "terminology_audit_authority": "chatgpt_independent_semantic_audit",
            "audit_file": "ep74_semantic_audit.json",
            "audit_sha256": "598d92e0c0f7022b287b5601c6baa51b79f4cd94b366a58459e80824e1849cd0",
            "audit_validation": "text_based_semantic_review_not_audio_verified",
            "timestamp_derivation": "hybrid_asr_token_aligned_and_interpolated_cue_bounds_not_word_audio_verified",
        },
        "summary": {
            "total_concepts_count": len(approved_concepts),
            "total_occurrences_count": total_occurrences_count,
            "cross_script_concepts_count": cross_script_count,
            "uncertain_concepts_count": uncertain_count,
            "excluded_occurrences_count": len(benchmark_exclusions),
            "cues_scanned": len(cues),
        },
        "technical_terms": sorted(technical_terms),
        "all_verified_english_expressions": sorted(list(all_english_expressions)),
        "reference_text": reference_text,
        "verified_occurrences": verified_occurrences,
        "concept_mentions": concept_mentions,
        "suggested_terms": approved_concepts,
        "benchmark_exclusions": benchmark_exclusions,
        "audit_changelog": audit_changelog,
    }

    report = {
        "total_proposed_occurrences": 330,
        "total_audit_modifications": len(audit_changelog),
        "total_added_occurrences": len([c for c in audit_changelog if c.get("verdict") == "added_from_candidate_suggestion"]),
        "total_excluded_items": len(benchmark_exclusions),
        "total_verified_occurrences": total_occurrences_count,
        "total_approved_concepts": len(approved_concepts),
        "cross_script_concepts": cross_script_count,
        "uncertain_concepts": uncertain_count,
    }

    return reference_c, report


def main():
    eval_dir = EVAL_DIR
    ref_c, report = build_reference_c(eval_dir)

    out_approved = eval_dir / "reference_terms.approved.json"
    out_approved.write_text(json.dumps(ref_c, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved frozen Reference C to {out_approved}")
    print(f"Report: {json.dumps(report, indent=2)}")


if __name__ == "__main__":
    main()
