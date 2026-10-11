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
        if len(term) >= 3 or (len(term) == 2 and term.isupper()):
            names.setdefault(term.casefold(), term)
    for term in BASE_VOCABULARY:
        if " " not in term:
            continue
        if re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])",
                     text, flags=re.IGNORECASE):
            names.setdefault(term.casefold(), term)
    return list(names.values())


def _compact(term: str) -> str:
    """Normalize Latin term variants, e.g. Nano-Claw and NanoClaw."""
    return "".join(re.findall(r"[a-z0-9]+", term.casefold()))


def _timed_english_parts(tokens: list, start: float, end: float) -> list:
    """Extract possible English parts from timed ASR words/segments."""
    words = []
    for index, token in enumerate(tokens):
        a, b = token.get("start"), token.get("end")
        if a is None or b is None or not (start <= a < end):
            continue
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9-]*", token.get("text", "")):
            words.append({
                "word": match.group(),
                "key": _compact(match.group()),
                "start": float(a), "end": float(b),
                "index": index, "raw": token.get("text", ""),
            })
    return words


def _locate_term(term: str, tokens: list, start: float, end: float) -> list:
    """Find timestamp windows; never imply they are human-verified.

    Up to four adjacent timed words may form one English phrase. Exact
    provider spelling variants (hyphenation/case) share an occurrence.
    Segments without word-level times yield coarse windows, explicitly
    labeled as such.
    """
    target = _compact(term)
    if not target:
        return []
    words = _timed_english_parts(tokens, start, end)
    hits = []
    for i, word in enumerate(words):
        acc = ""
        for j in range(i, min(i + 4, len(words))):
            part = words[j]
            if j > i and (part["start"] - words[j - 1]["end"] > 1.5 or
                           part["index"] - words[j - 1]["index"] > 2):
                break
            acc += part["key"]
            if len(acc) > len(target):
                break
            if acc == target:
                a = word["start"]
                b = part["end"]
                if not any(abs(o["start"] - a) <= .25 for o in hits):
                    hits.append({
                        "start": round(a, 2), "end": round(b, 2),
                        "text": " ".join(w["word"] for w in words[i:j + 1]),
                        "alignment": "asr_word_or_segment",
                    })
                break
    return hits


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
            key = _compact(term)
            item = candidates.setdefault(
                key, {"term": term, "seen_in": [], "occurrences": []}
            )
            if name not in item["seen_in"]:
                item["seen_in"].append(name)
            for hit in _locate_term(
                term, payload.get("tokens", []), start, end
            ):
                existing = next((
                    o for o in item["occurrences"]
                    if abs(o["start"] - hit["start"]) < 1.5
                ), None)
                if existing:
                    if name not in existing["sources"]:
                        existing["sources"].append(name)
                else:
                    item["occurrences"].append({
                        **hit, "sources": [name],
                    })
    ordered = sorted(candidates.values(),
                     key=lambda item: (-len(item["seen_in"]),
                                       item["term"].casefold()))
    for item in ordered:
        item["occurrences"].sort(key=lambda o: o["start"])
    return {
        "episode_guid": guid,
        "episode_title": reference.get("episode_title", ""),
        "window": window,
        "draft_only": True,
        "timestamps_are_estimates": True,
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
