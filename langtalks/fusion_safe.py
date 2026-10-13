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
from .glossary import BASE_VOCABULARY

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
    mandatory_prefix = core[:2] if len(core) > 3 and core[0] in _PREFIXES and core[1] == "-" else ""
    if mandatory_prefix:
        core = core[2:]
    options = [(mandatory_prefix, core)]
    if len(core) > 2 and core[0] in _PREFIXES and core[1] != "-":
        options.append((mandatory_prefix + core[0] + "-", core[1:]))
    if len(core) > 3 and core[:2] in tuple(c + "-" for c in _PREFIXES):
        options.append((mandatory_prefix + core[:2], core[2:]))
    scored = []
    for prefix, candidate in options:
        raw = _similarity(_romanized(candidate), _romanized(donor))
        consonant = _similarity(_consonants(candidate), _consonants(donor))
        scored.append((min(1.0, max(raw, consonant * 0.96) + (0.006 if prefix else 0)), prefix))
    score, prefix = max(scored, key=lambda v: (v[0], -len(v[1])))
    return prefix, score


def _protected(base_text: str, donor_text: str) -> bool:
    if re.search(r"['׳][\u0590-\u05ff]", base_text):
        return True
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
        for j in range(i + 1, min(i + 10, len(tokens) + 1)):
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
    glossary = {_clean(term) for term in BASE_VOCABULARY}
    glossary.update(_clean(term) for term in glossary_terms or [])
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
        identity_word = (len(donor.words) == 1
                         and bool(re.search(r"[A-Z].*[A-Z]|[a-z][A-Z]|^[A-Z][a-z]{4,}", donor.text)))
        floor = 0.58 if identity_word else 0.72
        if (donor.min_subword_confidence is not None
                and donor.min_subword_confidence < max(min_confidence - 0.12, floor)):
            continue
        for i, j, start, end in _candidate_spans(base_tokens, donor, occupied, time_tolerance):
            base_text = "".join(t.get("text", "") for t in base_tokens[i:j])
            if not base_text.strip():
                continue
            if _HEBREW.search(base_text) and re.search(r"['׳]", base_text):
                continue
            if (i > 0 and base_tokens[i].get("text", "").startswith("-")
                    and _LATIN.search(base_tokens[i - 1].get("text", ""))):
                continue
            normalized_identical = _clean(base_text) == _clean(donor.text)
            # Style-only rewriting is forbidden, except canonical internal
            # capitals of a genuine mixed-case technical identifier.
            official_mixed_caps = (identity_word and bool(re.search(r"[A-Z]{2,}", donor.text))
                                   and "-" in base_text.strip().strip("-")
                                   and not _HEBREW.search(base_text)
                                   and not base_text.lstrip().startswith("-"))
            if normalized_identical and not official_mixed_caps:
                continue
            if (_LATIN.search(base_text) and donor.min_subword_confidence is not None
                    and donor.min_subword_confidence < max(min_confidence, 0.72)):
                continue
            base_parts = base_text.strip().split()
            donor_parts = donor.text.strip().split()
            if len(donor_parts) > 1 and _LATIN.search(base_text):
                base_latin = re.findall(r"[A-Za-z]{3,}", base_text)
                donor_latin = re.findall(r"[A-Za-z]{3,}", donor.text)
                if any(not any(max(_similarity(part.lower(), name.lower()),
                                   _similarity(_consonants(part), _consonants(name))) >= .70
                               for name in donor_latin)
                       for part in base_latin):
                    continue
            if (len(donor_parts) > 1 and not _LATIN.search(base_text)
                    and ("'" in base_text or "׳" in base_text)):
                continue
            if (len(base_parts) == len(donor_parts) and len(donor_parts) > 1
                    and _LATIN.search(base_text) and not _HEBREW.search(base_text)):
                # Reject phrase-window shifts that replace a correct word with
                # a neighboring word. Phonetic agreement must hold per word.
                if any(max(_similarity(_romanized(left), _romanized(right)),
                           _similarity(_consonants(left), _consonants(right))) < .62
                       for left, right in zip(base_parts, donor_parts)):
                    continue
            if len(base_parts) != len(donor_parts):
                # Only a tightly anchored named entity may consume two
                # phonetically related Hebrew words; never intervening
                # conjunctions, fillers, or otherwise correct Latin words.
                if not (not _LATIN.search(base_text)
                        and len(base_parts) == 2 and len(donor_parts) == 1
                        and identity_word and donor.confidence >= 0.97
                        and not any(w in ("ו", "או", "עם", "של", "זה", "גם", "את")
                                    for w in base_parts)
                        and _affix_and_similarity(base_text, donor.text)[1] >= 0.76):
                    continue
            if (len(donor_parts) > 1 and _LATIN.search(base_text)
                    and _HEBREW.search(base_text)
                    and any(len(w) > 1 for w in re.findall(r"[\u0590-\u05ff]+", base_text))):
                continue
            if len(donor.words) > 1 and any(
                    is_hebrewized_loanword(word.text.strip().strip(".,!"),
                                          base_text)
                    for word in donor.words):
                continue
            if (_protected(base_text, donor.text)
                    and not (entity and donor.confidence >= 0.97
                             and _affix_and_similarity(base_text, donor.text)[1] >= 0.78
                             and not is_hebrewized_loanword(donor.text, base_text))):
                continue
            has_latin = bool(_LATIN.search(base_text))
            if not has_latin and not (entity or len(donor.words) > 1):
                continue
            if not has_latin and donor.confidence < max(min_confidence, 0.95 if not entity else 0.86):
                continue
            prefix, similarity = _affix_and_similarity(base_text, donor.text)
            threshold = 0.67 if has_latin else (0.46 if identity_word else 0.59 if entity else 0.66)
            if similarity < threshold:
                continue
            if has_latin and len(base_parts) == 1 and len(donor_parts) == 1:
                if (_clean(base_text).endswith("s") and _clean(base_text)[:-1] == _clean(donor.text)
                        or _clean(donor.text).endswith("s") and _clean(donor.text)[:-1] == _clean(base_text)):
                    continue
            # A good local word-level match is insufficient when the span
            # includes an already-correct Latin donor expression plus extras.
            donor_stem = _clean(donor.text)
            if (donor_stem and _LATIN.search(base_text)
                    and re.search(r"(?<![a-z0-9])" + re.escape(donor_stem)
                                  + r"(?![a-z0-9])", _clean(base_text))
                    and not official_mixed_caps):
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
            if (best[2], best[3]) != (second[2], second[3]) and best[0] - second[0] < 0.012:
                a1, b1, a2, b2 = best[4], best[5], second[4], second[5]
                if min(b1, b2) - max(a1, a2) < 0.5 * min(b1 - a1, b2 - a2):
                    continue
        _, similarity, i, j, start, end, prefix, original = best
        # A written Hebrew prefix is preserved; new ones require a matching
        # donor clitic. Do not guess ו- from loanwords starting with ו.
        explicit_prefix = (original.strip()[:2]
                           if re.match(r"^[ובהלמכ]-", original.strip()) else "")
        prefix = explicit_prefix
        if (donor.hebrew_prefix and original.strip().startswith(donor.hebrew_prefix[0])
                and not explicit_prefix):
            prefix = donor.hebrew_prefix
        leading = re.match(r"\s*", original).group()
        trailing = re.search(r"[.,;:!?]+\s*$", original)
        punctuation = trailing.group().rstrip() if trailing else ""
        replacement = leading + prefix + donor.text.strip() + punctuation
        # A leading dash can join a separately timed Hebrew clitic to its
        # English stem: ה + -dependency, ב + -OneCLI.
        if (original.lstrip().startswith("-") and i > 0
                and base_tokens[i - 1].get("text", "").strip() in _PREFIXES
                and not prefix):
            replacement = leading + "-" + donor.text.strip() + punctuation
        if (_clean(original) == _clean(replacement)
                and not (len(donor.words) == 1 and re.search(r"[A-Z]{2,}", donor.text)
                         and "-" in original.strip().strip("-")
                         and not original.lstrip().startswith("-")
                         and not _HEBREW.search(original))):
            continue
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
            "donor_min_subword_confidence": donor.min_subword_confidence,
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
