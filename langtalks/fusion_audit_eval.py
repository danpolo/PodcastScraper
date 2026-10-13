"""Offline-only audit replay for the reviewed Episode 71 benchmark.

Never connects to a transcription provider, never writes over cached ASR or
human reference files. Output is JSON on stdout (or a separate --output path).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from .hybrid import HEBREWIZED_LOANWORDS, align_and_merge
from .score import _edit_distance, _normalize, load_reference, score

ROOT = Path(__file__).resolve().parent
GUID = "74fc0625-0a6b-4ca1-9488-31be7860360d"


def word_error_rate(candidate: str, reference: str):
    """Case-insensitive, punctuation-normalized WER; auxiliary, not canonical."""
    a, b = _normalize(candidate).split(), _normalize(reference).split()
    return round(_edit_distance(a, b) / len(b), 4) if b else None


def char_error_rate(candidate: str, reference: str):
    a, b = _normalize(candidate), _normalize(reference)
    return round(_edit_distance(a, b) / len(b), 4) if b else None


def loanword_recall(candidate: str, reference: str) -> dict:
    """Exact surface recall of *known* Hebrewized forms, not exhaustive."""
    forms = set().union(*HEBREWIZED_LOANWORDS.values())
    normalize = lambda x: x.replace("׳", "'").replace("״", '"')
    clean = lambda w: w.strip(".,;:!?")
    expected = Counter(clean(w) for w in normalize(reference).split() if clean(w) in forms)
    if not expected:
        return {"expected": 0, "observed": 0, "recall": None}
    found = Counter(clean(w) for w in normalize(candidate).split() if clean(w) in forms)
    observed = sum(min(n, found[w]) for w, n in expected.items())
    total = sum(expected.values())
    return {"expected": total, "observed": observed, "recall": round(observed / total, 4)}


def unsupported_latin_tokens(candidate: str, reference: str) -> list:
    """Only candidates for human review: not verified hallucinations."""
    get = lambda txt: Counter(x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9]+", txt))
    spoken, emitted = get(reference), get(candidate)
    return sorted({term for term in emitted if term not in spoken})


def summarize(transcript: dict, reference: dict) -> dict:
    text = transcript.get("text", "")
    reference_text = reference.get("reference_text", "")
    scored = score(text, transcript.get("tokens", []), reference)
    return {
        "overall_legacy_weighted_score": scored["overall"],
        "unique_term_recall": scored["components"]["term_recall"],
        "timed_occurrence_diagnostic": scored["timed_term_recall"],
        "one_to_one_timed_occurrence_diagnostic": scored["timed_term_recall_strict"],
        "hebrew_character_accuracy": scored["components"]["hebrew_accuracy"],
        "script_density_fidelity": scored["components"]["script_fidelity"],
        "glossary_limited_term_precision": scored["components"]["term_precision"],
        "word_error_rate": word_error_rate(text, reference_text),
        "character_error_rate": char_error_rate(text, reference_text),
        "known_loanword_recall": loanword_recall(text, reference_text),
        "extra_latin_tokens_for_manual_review": unsupported_latin_tokens(text, reference_text),
    }


def replay(root: Path = ROOT, include_merged: bool = False):
    pilot = root / "reviewed" / "episode71" / "optimized-pilot"
    stem = str(GUID) + "."
    with (pilot / (stem + "optimized_modal_l4.json")).open(encoding="utf-8") as fh:
        base = json.load(fh)
    with (pilot / (stem + "optimized_soniox.json")).open(encoding="utf-8") as fh:
        donor = json.load(fh)
    with (pilot / (stem + "optimized_hybrid.json")).open(encoding="utf-8") as fh:
        previous = json.load(fh)
    reference = load_reference(root / "reference" / (GUID + ".json"))
    merged, mods = align_and_merge(base, donor)
    result = {
        "benchmark": "Episode 71, 480-780s, development set only",
        "glossary_leakage": "No glossary or reference supplied to fusion at replay time",
        "baseline_ivrit": summarize(base, reference),
        "baseline_soniox": summarize(donor, reference),
        "previous_hybrid": summarize(previous, reference),
        "revised_hybrid": summarize(merged, reference),
        "changes": mods,
        "modification_count": len(mods),
        "rejected_candidates_sample": merged["provenance"].get("rejected_candidates_sample", []),
        "limitations": [
            "Episode 71 was used during development: these are NOT held-out metrics",
            "Strict occurrence matching is one-to-one but still approximate due to ASR word timestamps",
            "Glossary precision cannot establish the absence of hallucinations",
            "Extra Latin tokens are review flags, not automatically proven hallucinations",
            "Word error rate is an imperfect proxy for Hebrew code-switching quality",
        ],
    }
    return (result, merged) if include_merged else result


def assert_no_development_regression(result: dict) -> None:
    """Offline gates against the *frozen* previous output, not production KPIs.

    Episode 71 is a DEVELOPMENT benchmark, so passing these constraints
    demonstrates only non-regression against these cached reference annotations.
    """
    prior, current = result["previous_hybrid"], result["revised_hybrid"]
    old_occ = prior["one_to_one_timed_occurrence_diagnostic"]
    new_occ = current["one_to_one_timed_occurrence_diagnostic"]
    assert old_occ and new_occ, "timed term evidence unavailable"
    assert new_occ["matched"] >= old_occ["matched"], "timed occurrences regressed"
    assert current["word_error_rate"] <= prior["word_error_rate"], "WER regressed"
    assert current["hebrew_character_accuracy"] >= prior["hebrew_character_accuracy"], "Hebrew accuracy regressed"
    a = current["known_loanword_recall"]
    b = prior["known_loanword_recall"]
    assert a["observed"] >= b["observed"], "known Hebrewized loanwords regressed"
    for mod in result["changes"]:
        assert mod["donor_token_indices"], "edit lacks donor evidence"
        assert mod["base_token_indices"], "edit lacks base provenance"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--output", type=Path, help="Optional NEW report JSON path")
    p.add_argument("--merged-output", type=Path,
                   help="Optional NEW hybrid transcript JSON path; never overwrites ASR outputs")
    args = p.parse_args()
    for path in (args.output, args.merged_output):
        if path is not None and path.exists():
            p.error(f"refusing to overwrite existing file: {path}")
    if args.output and args.output == args.merged_output:
        p.error("report and hybrid output paths must differ")
    if args.merged_output:
        result, merged = replay(args.root, include_merged=True)
    else:
        result = replay(args.root)
        merged = None
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as fh:
            fh.write(serialized + "\n")
    else:
        print(serialized)
    if args.merged_output:
        with args.merged_output.open("x", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
            fh.write("\n")


if __name__ == "__main__":
    main()
