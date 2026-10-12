"""Benchmark scoring.

The point of this file is one idea: **overall word error rate is the wrong
metric for this podcast**. A model that mangles "אבל" and a model that mangles
"Model Context Protocol" score the same on WER, but only the second one
destroys the thing we are mining the podcast for.

So technical-term recall is scored separately and weighted heaviest, and the
specific failure mode we care about — transliterating an English term into
Hebrew letters — gets its own signal.

Reference format (one JSON file per benchmarked window, in reference/):

    {
      "episode_guid": "74fc0625-...",
      "window": {"start": 480, "end": 900},
      "technical_terms": ["Blast Radius", "Supply Chain Security", "MCP"],
      "reference_text": "<optional: corrected transcript of the window>",
      "speaker_turns": [{"start": 481.2, "speaker": "host"}]
    }

``technical_terms`` is the only required annotation and the only one that is
expensive-but-cheap: listen to the window once and write down the English terms
you hear. Everything else is optional and its weight is redistributed when
absent.
"""

import json
import re
import unicodedata

# Weights follow the "what actually hurts" ordering, not convention.
WEIGHTS = {
    "term_recall": 0.45,
    "hebrew_accuracy": 0.30,
    "term_precision": 0.10,
    "speaker_accuracy": 0.10,
    "script_fidelity": 0.05,
}

_HEBREW_RE = re.compile(r"[֐-׿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Casefold, strip punctuation and collapse whitespace for term matching."""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[^\w\s֐-׿]", " ", text)
    return _WS_RE.sub(" ", text).strip().lower()


def _latin_ratio(text: str) -> float:
    letters = _HEBREW_RE.findall(text) + _LATIN_RE.findall(text)
    if not letters:
        return 0.0
    return len(_LATIN_RE.findall(text)) / len(letters)


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance, single-row DP."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (char_a != char_b),
                )
            )
        previous = current
    return previous[-1]


def _has_term(normalized: str, term: str) -> bool:
    """Match Latin terms at Latin/number boundaries, not substrings.

    Keep adjacency to Hebrew legal: speakers may say בMCP without a space.
    """
    name = _normalize(term)
    if not name:
        return False
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(name)
                          + r"(?![a-z0-9])", normalized))


def term_recall(candidate: str, terms: list) -> tuple:
    """Fraction of spoken English terms correctly preserved in Latin script."""
    normalized = _normalize(candidate)
    found, missed = [], []
    for term in terms:
        (found if _has_term(normalized, term) else missed).append(term)
    score = len(found) / len(terms) if terms else None
    return score, found, missed


def term_precision(candidate: str, terms: list, glossary: list = None) -> tuple:
    """Glossary-induced hallucination: prompted terms that were never spoken.

    This measures the specific risk of keyterm prompting. Telling a model to
    expect "LangGraph" does not license it to resolve every unclear "Lang…"
    into LangGraph, and a confidently wrong product name is worse than an
    obvious phonetic guess because it propagates silently into extracted tips.

    Only glossary terms are checked. Ordinary English that the annotator simply
    did not bother to list ("best practices") is not a hallucination, and
    penalising it would drown the signal we actually want.
    """
    from .glossary import BASE_VOCABULARY

    candidates = glossary if glossary else BASE_VOCABULARY
    spoken = {_normalize(term) for term in terms}
    normalized = _normalize(candidate)

    emitted, invented = [], []
    for term in candidates:
        key = _normalize(term)
        # Single short tokens ("CI", "API") match too loosely to judge.
        if len(key) < 4 or not _has_term(normalized, term):
            continue
        emitted.append(term)
        # Spoken if the reference lists it, or lists something containing it.
        if not any(key == s or key in s for s in spoken):
            invented.append(term)

    if not emitted:
        return None, []
    return 1.0 - len(invented) / len(emitted), sorted(invented)


def timed_term_recall(tokens: list, reference: dict, tolerance: float = 1.5):
    """Diagnostic: count recognition of EACH user-reviewed term appearance.

    The old term_recall() only checks whether a term appeared *anywhere*.
    With six OneCLI occurrences a model recognizing only one could misleadingly
    score 100% on that term. This opt-in diagnostic uses absolute episode time.

    Word-level or short-segment timestamps are required; long segment timing is
    too coarse to verify individual mentions. The score remains diagnostic
    (not part of weighted provider rankings) until different adapters' timing
    fidelity has been validated.
    """
    terms = set(reference.get("technical_terms") or [])
    appearances = [
        occ for occ in (reference.get("verified_occurrences") or [])
        if occ.get("surface") in terms and
        occ.get("review_status") == "verified"
    ]
    candidates = []
    for token in tokens or []:
        a, b = token.get("start"), token.get("end")
        if a is None or b is None:
            continue
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            continue
        if a < 0 or b < a or b - a > 6.0:
            continue  # no false precision from coarse paragraph segments
        candidates.append((a, b, str(token.get("text", ""))))
    if not appearances or not candidates:
        return None
    matches, misses = [], []
    for occ in appearances:
        start, end = float(occ["start"]), float(occ["end"])
        nearby = [text for a, b, text in candidates
                  if b >= start - tolerance and a <= end + tolerance]
        observed = "".join(nearby)
        if _has_term(_normalize(observed), occ["surface"]):
            matches.append({"term": occ["surface"], "at_s": round(start, 2)})
        else:
            misses.append({"term": occ["surface"], "at_s": round(start, 2)})
    total = len(appearances)
    return {
        "recall": round(len(matches) / total, 4),
        "matched": len(matches),
        "total": total,
        "missed": misses,
        "method": "relative_word_or_short_segment_audio_alignment",
        "diagnostic_only": True,
    }


def hebrew_accuracy(candidate: str, reference_text: str) -> float:
    """1 - CER over Hebrew characters only.

    Restricting to Hebrew keeps this component from double-counting the English
    terms already measured by term_recall.
    """
    if not reference_text:
        return None
    strip = lambda text: _WS_RE.sub("", "".join(_HEBREW_RE.findall(text or "")))
    reference, hypothesis = strip(reference_text), strip(candidate)
    if not reference:
        return None
    return max(0.0, 1.0 - _edit_distance(hypothesis, reference) / len(reference))


def script_fidelity(candidate: str, reference_text: str, terms: list) -> float:
    """How close the candidate's Latin density is to the reference's.

    A model that transliterates English into Hebrew letters produces fluent,
    plausible text whose Latin ratio has collapsed. On this repo's existing
    YouTube-caption corpus that ratio is 2%; a transcript that preserves the
    English terms sits far higher. Overshooting is not rewarded.
    """
    if reference_text:
        target = _latin_ratio(reference_text)
    elif terms:
        # Without a reference transcript, approximate the target from how much
        # Latin the known terms alone would contribute.
        target = None
    else:
        return None
    if not target:
        return None
    actual = _latin_ratio(candidate)
    return max(0.0, 1.0 - abs(actual - target) / target)


def speaker_accuracy(tokens: list, speaker_turns: list, tolerance: float = 2.0) -> float:
    """Fraction of annotated turn boundaries the provider also placed a change at."""
    if not speaker_turns or not tokens:
        return None
    # A provider that emits no speaker labels at all does not diarize; that is
    # a capability gap, not a bad result, so it must not score as a zero.
    if not any(token.get("speaker") is not None for token in tokens):
        return None
    changes = []
    previous = object()
    for token in tokens:
        speaker = token.get("speaker")
        if speaker != previous and token.get("start") is not None:
            changes.append(token["start"])
            previous = speaker
    if not changes:
        return 0.0
    matched = sum(
        1 for turn in speaker_turns
        if any(abs(change - turn["start"]) <= tolerance for change in changes)
    )
    return matched / len(speaker_turns)


def score(candidate_text: str, tokens: list, reference: dict, glossary: list = None) -> dict:
    """Score one candidate transcript window against its reference annotation.

    Components that the reference cannot support are reported as None and their
    weight is redistributed across the rest, so a provider is never penalised
    for an annotation the reference simply does not carry.
    """
    terms = reference.get("technical_terms", []) or []
    reference_text = reference.get("reference_text", "")
    turns = reference.get("speaker_turns", []) or []

    recall, found, missed = term_recall(candidate_text, terms)
    # Without an exhaustive, listening-verified list, an apparently new
    # glossary term cannot be classified as a hallucination. Do not award or
    # penalize precision from partial annotations.
    if reference.get("review_status") == "approved" and reference.get("terms_exhaustive"):
        # ASR *recall* is deliberately strict about high-value Latin terms.
        # Hallucination *precision* must consider the fuller list of confirmed
        # speech too, otherwise an ordinary English word excluded from semantic
        # indexing could be falsely called invented. Reviewed product/protocol
        # identities also have canonical aliases, e.g. ASR 'Auth' vs OAuth.
        precision_spoken = list(
            reference.get("all_verified_english_expressions") or terms
        )
        precision_spoken.extend(
            occ.get("canonical")
            for occ in reference.get("verified_occurrences") or []
            if occ.get("review_status") == "verified"
            and occ.get("kind") in ("product", "protocol")
            and occ.get("canonical")
        )
        precision, invented = term_precision(candidate_text, precision_spoken, glossary)
    else:
        precision, invented = None, []

    components = {
        "term_recall": recall,
        "hebrew_accuracy": hebrew_accuracy(candidate_text, reference_text),
        "term_precision": precision,
        "speaker_accuracy": speaker_accuracy(tokens, turns),
        "script_fidelity": script_fidelity(candidate_text, reference_text, terms),
    }

    usable = {k: v for k, v in components.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in usable)
    overall = (
        sum(WEIGHTS[k] * v for k, v in usable.items()) / total_weight
        if total_weight
        else None
    )

    return {
        "overall": overall,
        "components": components,
        "scored_components": sorted(usable),
        "terms_found": found,
        "terms_missed": missed,
        "hallucinated_terms": invented[:40],
        "latin_ratio": round(_latin_ratio(candidate_text), 4),
        "timed_term_recall": timed_term_recall(tokens, reference),
    }


def load_reference(path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
