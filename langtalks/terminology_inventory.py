"""Generate immutable post-ASR engine-detected terminology inventory (Dataset B).

Runs on machine transcripts ONLY before any human correction or ground truth review.
Preserves raw candidate phrases, observed surfaces, canonical guesses, occurrence
intervals, provider votes, and uncertainties.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from .reference_draft import _candidate_terms, _locate_term, _compact
from .glossary import extract_latin_phrases, extract_latin_terms, BASE_VOCABULARY
from .hybrid import assemble_donor_words


def build_candidate_inventory_for_transcript(
    transcript: dict,
    provider_name: str,
    max_duration: float = float("inf")
) -> Dict[str, dict]:
    """Extract candidate terms and timed occurrences from a single transcript."""
    text = transcript.get("text", "")
    tokens = transcript.get("tokens", [])

    candidates: Dict[str, dict] = {}

    # 1. Base candidate terms (single-word Latin + known BASE_VOCABULARY phrases)
    terms_list = _candidate_terms(text)

    # 2. Extract multi-word Latin phrases present in text
    extra_phrases = extract_latin_phrases(text, max_words=3)
    for p in extra_phrases:
        if p.casefold() not in [t.casefold() for t in terms_list]:
            terms_list.append(p)

    for term in terms_list:
        key = _compact(term)
        if not key:
            continue

        hits = _locate_term(term, tokens, 0.0, max_duration)
        if not hits and " " in term:
            # Try matching individual parts if phrase failed
            continue

        item = candidates.setdefault(key, {
            "canonical_guess": term,
            "surfaces_observed": set(),
            "occurrences": [],
            "provider": provider_name,
        })
        item["surfaces_observed"].add(term)

        for hit in hits:
            # Extract local confidence if available in matching tokens
            start_s, end_s = hit["start"], hit["end"]
            token_confs = [
                t.get("confidence") for t in tokens
                if t.get("start") is not None and t.get("end") is not None
                and not (float(t["end"]) < start_s or float(t["start"]) > end_s)
                and t.get("confidence") is not None
            ]
            avg_conf = round(sum(token_confs) / len(token_confs), 4) if token_confs else None

            # Get surrounding context words
            context_tokens = [
                t.get("text", "") for t in tokens
                if t.get("start") is not None and t.get("end") is not None
                and start_s - 3.0 <= float(t["start"]) <= end_s + 3.0
            ]
            context_str = "".join(context_tokens).strip()

            item["occurrences"].append({
                "start": hit["start"],
                "end": hit["end"],
                "surface": hit["text"],
                "confidence": avg_conf,
                "detection_method": hit.get("alignment", "asr_word_or_segment"),
                "context": context_str[:120],
                "source_provider": provider_name,
            })

    # Convert sets to sorted lists for serialization
    for item in candidates.values():
        item["surfaces_observed"] = sorted(item["surfaces_observed"])
        item["occurrences"].sort(key=lambda o: o["start"])

    return candidates


def generate_dataset_b(
    eval_dir: Path,
    guid: str,
    duration: float = 1848.89
) -> dict:
    """Generate complete Dataset B combining all machine transcripts."""
    ivrit_path = eval_dir / "provider_ivrit.original.json"
    soniox_path = eval_dir / "provider_soniox.original.json"
    hybrid_path = eval_dir / "hybrid_revised.original.json"
    mods_path = eval_dir / "fusion_edits.original.json"

    ivrit_data = json.loads(ivrit_path.read_text(encoding="utf-8"))
    soniox_data = json.loads(soniox_path.read_text(encoding="utf-8"))
    hybrid_data = json.loads(hybrid_path.read_text(encoding="utf-8"))
    mods_data = json.loads(mods_path.read_text(encoding="utf-8")) if mods_path.exists() else []

    ivrit_inv = build_candidate_inventory_for_transcript(ivrit_data, "modal_ivrit_l4", duration)
    soniox_inv = build_candidate_inventory_for_transcript(soniox_data, "soniox", duration)
    hybrid_inv = build_candidate_inventory_for_transcript(hybrid_data, "revised_hybrid", duration)

    # Combine into unified candidate inventory
    all_keys = sorted(set(ivrit_inv.keys()) | set(soniox_inv.keys()) | set(hybrid_inv.keys()))
    combined_terms = []

    for key in all_keys:
        sources = []
        all_surfaces = set()
        all_occurrences = []

        for prov_name, inv in [("modal_ivrit_l4", ivrit_inv), ("soniox", soniox_inv), ("revised_hybrid", hybrid_inv)]:
            if key in inv:
                sources.append(prov_name)
                all_surfaces.update(inv[key]["surfaces_observed"])
                all_occurrences.extend(inv[key]["occurrences"])

        # Determine preferred canonical guess (prefer hybrid, then soniox, then ivrit)
        canonical = (
            hybrid_inv.get(key, {}).get("canonical_guess")
            or soniox_inv.get(key, {}).get("canonical_guess")
            or ivrit_inv.get(key, {}).get("canonical_guess")
            or key
        )

        all_occurrences.sort(key=lambda o: (o["start"], o["source_provider"]))

        # Flag phonetic or spelling uncertainties across providers
        has_uncertainty = len(all_surfaces) > 1 or len(sources) < 2

        combined_terms.append({
            "key": key,
            "canonical_guess": canonical,
            "surfaces_observed": sorted(all_surfaces),
            "sources": sources,
            "votes_count": len(sources),
            "total_estimated_occurrences": len(all_occurrences),
            "occurrences": all_occurrences,
            "uncertainty_flag": has_uncertainty,
            "in_revised_hybrid": "revised_hybrid" in sources,
        })

    # Sort combined terms by votes count (descending), then alphabetically
    combined_terms.sort(key=lambda t: (-t["votes_count"], t["canonical_guess"].casefold()))

    dataset_b = {
        "protocol_layer": "B",
        "description": "Post-ASR engine-detected technical-term inventory (machine observation) before human review",
        "episode_guid": guid,
        "audio_duration_seconds": duration,
        "immutable": True,
        "methodology": "Strict machine observation across base, donor, and revised hybrid. No human ground truth.",
        "summary": {
            "total_unique_candidate_concepts": len(combined_terms),
            "total_estimated_occurrences": sum(t["total_estimated_occurrences"] for t in combined_terms),
            "terms_in_revised_hybrid": sum(1 for t in combined_terms if t["in_revised_hybrid"]),
            "terms_in_soniox_donor": sum(1 for t in combined_terms if "soniox" in t["sources"]),
            "terms_in_ivrit_base": sum(1 for t in combined_terms if "modal_ivrit_l4" in t["sources"]),
            "consensus_terms_count": sum(1 for t in combined_terms if t["votes_count"] >= 2),
            "fusion_modifications_count": len(mods_data),
        },
        "combined_candidate_terms": combined_terms,
        "per_provider_candidate_summaries": {
            "modal_ivrit_l4": {
                "unique_terms_count": len(ivrit_inv),
                "total_occurrences": sum(len(v["occurrences"]) for v in ivrit_inv.values()),
            },
            "soniox": {
                "unique_terms_count": len(soniox_inv),
                "total_occurrences": sum(len(v["occurrences"]) for v in soniox_inv.values()),
            },
            "revised_hybrid": {
                "unique_terms_count": len(hybrid_inv),
                "total_occurrences": sum(len(v["occurrences"]) for v in hybrid_inv.values()),
            },
        },
        "fusion_provenance_summary": {
            "strategy": "timestamp_aligned_confidence_fusion",
            "modifications_count": len(mods_data),
            "edits_sample": mods_data[:15],
        },
        "generator_version": "langtalks.terminology_inventory:generate_dataset_b@dev",
    }

    raw_bytes = json.dumps(dataset_b, ensure_ascii=False, indent=2).encode("utf-8")
    dataset_b["sha256"] = hashlib.sha256(raw_bytes).hexdigest()

    out_file = eval_dir / "engine_terms_detected.original.json"
    out_file.write_bytes(json.dumps(dataset_b, ensure_ascii=False, indent=2).encode("utf-8"))
    return dataset_b
