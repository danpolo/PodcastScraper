"""Conservative, donor-evidenced bilingual ASR fusion.

No episode-specific aliases or ground-truth vocabulary enter this algorithm.
A donor occurrence can amend only a temporally aligned, phonetically compatible
base span. Source tokens are never mutated; unresolvable disagreements are logged.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import List, Optional, Tuple

from .hybrid import (assemble_donor_words, extract_latin_donor_phrases,
                     heb_to_latin_approx, _edit_dist, is_hebrewized_loanword)

_LATIN = re.compile(r"[A-Za-z]")
_HEBREW = re.compile(r"[\u0590-\u05ff]")
_PUNCT = re.compile(r"[^a-z0-9\u0590-\u05ff]+", re.I)
_PREFIXES = "ובהלמכ"


def _clean(text: str) -> str:
    return _PUNCT.sub("", unicodedata.normalize("NFKC", text).lower())


def _romanized(text: str) -> str:
    """Approximate graphemes, not an unrestricted Hebrew-to-English translator."""
    norm = _clean(text).replace("1", "one")
    return heb_to_latin_approx(norm)


def _consonants(text: str) -> str:
    return re.sub("[aeiou]", "", _romanized(text)).replace("c", "k")


def _similarity(first: str, second: str) -> float:
    if not first or not second:
        return 0.0
    return 1.0 - _edit_dist(first, second) / max(len(first), len(second))


def _affix_and_similarity(base_text: str, donor_text: str) -> Tuple[str, float]:
    """Choose an optional, acoustically compatible Hebrew clitic."""
    core = base_text.strip().strip('"\u0027.,;:!?()[]{}')
    donor = donor_text.strip().strip('"\u0027.,;:!?()[]{}')
    options = [("", core)]
    if len(core) > 2 and core[0] in _PREFIXES and core[1] != "-":
        options.append((core[0] + "-", core[1:]))
    if len(core) > 3 and core[:2] in tuple(c + "-" for c in _PREFIXES):
        options.append((core[:2], core[2:]))
    scored = []
    for prefix, candidate in options:
        raw = _similarity(_romanized(candidate), _romanized(donor))
        consonant = _similarity(_consonants(candidate), _consonants(donor))
        scored.append((min(1.0, max(raw, consonant * 0.96) + (0.006 if prefix else 0)), prefix))
    score, prefix = max(scored, key=lambda v: (v[0], -len(v[1])))
    return prefix, score


def _protected(base_text: str, donor_text: str) -> bool:
    if is_hebrewized_loanword(donor_text, base_text):
        return True
    if _HEBREW.search(base_text) and not _LATIN.search(base_text):
        words = re.findall(r"[\u0590-\u05ff׳']+", base_text)
        if any(len(w) > 4 and w.endswith(("ים", "ות", "יות", "יתי")) for w in words):
            return True
    return False


def _identity_like(text: str, glossary: set) -> bool:
    clean = _clean(text)
    if clean in glossary:
        return True
    words = text.split()
    if len(words) != 1:
        return False
    word = words[0].strip(".,!?:")
    return bool(re.search(r"[A-Z].*[A-Z]|[A-Za-z]\d|\d[A-Za-z]|[a-z][A-Z]", word)) or (
        len(word) >= 5 and word[0].isupper() and word[1:].islower()
    )


def _valid_time(tok: dict) -> Optional[Tuple[float, float]]:
    try:
        a, b = float(tok["start"]), float(tok["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return (a, b) if math.isfinite(a) and math.isfinite(b) and 0 <= a <= b else None


def _candidate_spans(tokens: List[dict], donor, occupied: set, tolerance: float):
    """Yield tight neighboring base spans, excluding distant words and gaps."""
    for i, first in enumerate(tokens):
        if i in occupied:
            continue
        first_times = _valid_time(first)
        if not first_times or first_times[0] > donor.end + tolerance:
            continue
        if first_times[1] < donor.start - tolerance:
            continue
        for j in range(i + 1, min(i + 6, len(tokens) + 1)):
            if j - 1 in occupied:
                break
            curr = _valid_time(tokens[j - 1])
            if not curr:
                break
            if j > i + 1:
                prev = _valid_time(tokens[j - 2])
                if not prev or curr[0] - prev[1] > 0.45:
                    break
            start, end = first_times[0], curr[1]
            if end - start > max(3.0, donor.end - donor.start + 0.9):
                break
            if end < donor.start - tolerance or start > donor.end + tolerance:
                continue
            yield i, j, start, end


def align_and_merge_v2(base_transcript: dict, donor_transcript: dict,
                       glossary_terms: Optional[List[str]] = None,
                       min_confidence: float = 0.70,
                       time_tolerance: float = 1.5) -> Tuple[dict, List[dict]]:
    """Amend only phonetically compatible, temporally aligned occurrences.

    Confidence is a donor model output, not a calibrated probability of truth.
    Rejected candidates remain inspectable in provenance.
    """
    if not 0 <= min_confidence <= 1 or not 0 <= time_tolerance <= 5:
        raise ValueError("invalid fusion confidence or time tolerance")
    base_tokens = [dict(t) for t in base_transcript.get("tokens", [])]
    words = assemble_donor_words(donor_transcript.get("tokens", []))
    candidates = extract_latin_donor_phrases(words)
    glossary = {_clean(term) for term in glossary_terms or []}
    candidates.sort(key=lambda p: (-len(p.words), p.start, p.end))
    occupied = set()
    used_donor_indices = set()
    modifications = []
    rejected = []

    for donor in candidates:
        indices = {idx for word in donor.words for idx in word.token_indices}
        if indices & used_donor_indices or not _LATIN.search(donor.text) or _HEBREW.search(donor.text):
            continue
        if donor.confidence < max(min_confidence, 0.85):
            continue
        proposed = []
        entity = _identity_like(donor.text, glossary)
        for i, j, start, end in _candidate_spans(base_tokens, donor, occupied, time_tolerance):
            base_text = "".join(t.get("text", "") for t in base_tokens[i:j])
            if not base_text.strip() or _protected(base_text, donor.text):
                continue
            has_latin = bool(_LATIN.search(base_text))
            if not has_latin and not (entity or len(donor.words) > 1):
                continue
            if not has_latin and donor.confidence < max(min_confidence, 0.95 if not entity else 0.92):
                continue
            prefix, similarity = _affix_and_similarity(base_text, donor.text)
            threshold = 0.71 if has_latin else (0.72 if entity else 0.84)
            if similarity < threshold:
                continue
            donor_center = (donor.start + donor.end) / 2
            base_center = (start + end) / 2
            delta = abs(donor_center - base_center)
            if delta > min(time_tolerance, max(0.65, (end - start + donor.end - donor.start) / 2)):
                continue
            overlap = max(0.0, min(end, donor.end) - max(start, donor.start))
            if overlap <= 0 and delta > 0.30:
                continue
            length_penalty = abs((end - start) - (donor.end - donor.start)) * 0.08
            lexical_span_penalty = max(0, j - i - len(donor.words)) * 0.015
            score = similarity - 0.12 * delta - length_penalty - lexical_span_penalty
            proposed.append((score, similarity, i, j, start, end, prefix, base_text))
        if not proposed:
            if len(rejected) < 200 and (entity or donor.confidence >= 0.97):
                rejected.append({"term": donor.text, "start_s": donor.start,
                                 "end_s": donor.end, "reason": "no_safe_base_alignment"})
            continue
        proposed.sort(key=lambda v: v[0], reverse=True)
        best = proposed[0]
        if len(proposed) > 1:
            second = proposed[1]
            if (best[2], best[3]) != (second[2], second[3]) and best[0] - second[0] < 0.035:
                continue
        _, similarity, i, j, start, end, prefix, original = best
        leading = re.match(r"\s*", original).group()
        trailing = re.search(r"[.,;:!?]+\s*$", original)
        punctuation = trailing.group().rstrip() if trailing else ""
        replacement = leading + prefix + donor.text.strip() + punctuation
        if original.strip().casefold() == replacement.strip().casefold():
            continue
        base_tokens[i]["text"] = replacement
        # The merged token covers the complete replaced span, not just its
        # first original subword. The base confidence no longer applies.
        base_tokens[i]["end"] = end
        base_tokens[i]["confidence"] = None
        base_tokens[i]["fusion_source"] = "donor_aligned"
        for idx in range(i + 1, j):
            base_tokens[idx]["text"] = ""
        occupied.update(range(i, j))
        used_donor_indices.update(indices)
        modifications.append({
            "index": len(modifications) + 1,
            "original_text": original,
            "replacement_text": replacement,
            "start_s": start,
            "end_s": end,
            "base_token_indices": list(range(i, j)),
            "donor_token_indices": sorted(indices),
            "donor_start_s": donor.start,
            "donor_end_s": donor.end,
            "donor_term": donor.text,
            "donor_confidence": donor.confidence,
            "alignment_similarity": round(similarity, 4),
            "rule": "verified_timed_phonetic_alignment",
        })

    clean_tokens = [t for t in base_tokens if t.get("text") != ""]
    text = re.sub(r"[ \t]+", " ", "".join(t.get("text", "") for t in clean_tokens)).strip()
    if not modifications and isinstance(base_transcript.get("text"), str):
        # With no grounded edits, return the original ASR surface verbatim.
        text = base_transcript["text"]
    result = {
        "provider": f"hybrid_{base_transcript.get('provider', 'base')}_{donor_transcript.get('provider', 'donor')}",
        "source": base_transcript.get("source", "excerpt"),
        "episode_guid": base_transcript.get("episode_guid", ""),
        "episode_title": base_transcript.get("episode_title", ""),
        "time_offset": base_transcript.get("time_offset", 0.0),
        "text": text,
        "tokens": clean_tokens,
        "provenance": {
            "strategy": "timestamp_aligned_confidence_fusion",
            "version": 2,
            "base_provider": base_transcript.get("provider", "unknown"),
            "donor_provider": donor_transcript.get("provider", "unknown"),
            "min_confidence": min_confidence,
            "modifications_count": len(modifications),
            "modifications": modifications,
            "rejected_candidates_sample": rejected,
            "warning": "ASR confidence and phonetic similarity are not proof of lexical correctness",
        },
    }
    return result, modifications
