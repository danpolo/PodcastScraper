"""Create reviewable reference candidates from cached ASR output.

This does NOT create ground truth: provider agreement can still be wrong.
The user must listen to audio and explicitly mark reviewed terms.
"""
import json
import re
from pathlib import Path

from .glossary import BASE_VOCABULARY, extract_latin_terms
from .providers.base import window_text


def _candidate_terms(text):
    """Find emitted English words and complete glossary phrases."""
    names = {}
    for term in extract_latin_terms(text):
        if len(term) >= 3:
            names.setdefault(term.casefold(), term)
    for term in BASE_VOCABULARY:
        if " " not in term:
            continue
        if re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])",
                     text, flags=re.IGNORECASE):
            names.setdefault(term.casefold(), term)
    return list(names.values())


def propose(guid, transcript_dir: Path, reference: dict):
    """Return unverified terminology candidates with provider votes."""
    window = reference.get("window") or {}
    start = window.get("start", 0.0)
    end = window.get("end", float("inf"))
    candidates = {}
    sources = []
    for path in sorted(transcript_dir.glob(f"{guid}.*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source") != "excerpt" and not payload.get("tokens"):
            # Untimed full-episode text cannot be compared to an excerpt.
            continue
        name = payload.get("provider") or path.stem.split(".")[-1]
        text = window_text(payload, start, end)
        if not text:
            continue
        sources.append(name)
        for term in _candidate_terms(text):
            key = term.casefold()
            item = candidates.setdefault(key, {"term": term, "seen_in": []})
            if name not in item["seen_in"]:
                item["seen_in"].append(name)
    ordered = sorted(candidates.values(),
                     key=lambda item: (-len(item["seen_in"]),
                                       item["term"].casefold()))
    return {
        "episode_guid": guid,
        "episode_title": reference.get("episode_title", ""),
        "window": window,
        "draft_only": True,
        "provider_outputs_considered": sources,
        "suggested_terms": ordered,
        "review_instructions": (
            "These are unverified candidate words, not ground truth. "
            "Listen to the audio and edit the reference file's technical_terms "
            "to include all actually spoken English technical terms in Latin "
            "script; remove invented names; merge multiword phrases. "
            "Set review_status to approved only after listening."
        ),
    }


def write_draft(guid, reference_dir: Path, transcript_dir: Path,
                output_dir: Path):
    ref_path = reference_dir / f"{guid}.json"
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    draft = propose(guid, transcript_dir, ref)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{guid}.json"
    output.write_text(json.dumps(draft, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    return output, draft
