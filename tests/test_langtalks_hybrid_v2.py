"""Offline regression tests for evidence-based ASR fusion (no API calls)."""
import copy

import pytest

from langtalks.hybrid import align_and_merge


def transcript(words, confidence=None, shift=0.0, step=2.0):
    tokens = []
    for i, word in enumerate(words):
        token = {"text": " " + word, "start": shift + i * step,
                 "end": shift + i * step + 0.55}
        if confidence is not None:
            token["confidence"] = confidence
        tokens.append(token)
    return {"provider": "test", "tokens": tokens}


@pytest.mark.parametrize("corruption", [
    "1CRI", "One-Cלי", "OneCLA", "1.C.L.I.", "One-Cli", "1.Cלי",
])
def test_onecli_variants_need_corresponding_donor(corruption):
    base = transcript(["שלום", corruption, "כאן"])
    donor = transcript(["שלום", "OneCLI", "כאן"], .99)
    merged, mods = align_and_merge(base, donor)
    assert "OneCLI" in merged["text"]
    assert len(mods) == 1
    assert mods[0]["donor_term"] == "OneCLI"


def test_repeated_product_occurrences_not_deduplicated():
    corruptions = ["1CRI", "One-Cלי", "OneCLA", "1.C.L.I.", "One-Cli", "1.Cלי"]
    base = transcript(corruptions)
    donor = transcript(["OneCLI"] * len(corruptions), .99)
    merged, mods = align_and_merge(base, donor)
    assert merged["text"].count("OneCLI") == len(corruptions)
    assert len(mods) == len(corruptions)
    assert len({tuple(m["donor_token_indices"]) for m in mods}) == len(corruptions)


def test_hebrew_clitic_retained_when_corrobated():
    merged, mods = align_and_merge(
        transcript(["עם", "והרמז", "כאן"]),
        transcript(["עם", "ו-Hermes", "כאן"], .97),
    )
    assert "ו-Hermes" in merged["text"]
    assert len(mods) == 1


@pytest.mark.parametrize("donor", [
    transcript([], .99), transcript(["OneCLI"], .40), transcript(["OneCLI"]),
])
def test_unsupported_or_unconfident_donor_never_rewrites(donor):
    base = transcript(["1CRI"])
    merged, mods = align_and_merge(base, donor)
    assert mods == []
    assert merged["text"] == "1CRI"


def test_phonetic_pair_without_donor_never_rewrites():
    merged, mods = align_and_merge(transcript(["והרמז"]), transcript([]))
    assert mods == []
    assert merged["text"] == "והרמז"


def test_unrelated_hebrew_not_replaced_by_nearby_product():
    merged, mods = align_and_merge(transcript(["שלום"]), transcript(["OneCLI"], .99))
    assert mods == []
    assert merged["text"] == "שלום"


def test_loanwords_and_donor_hybrid_script_are_protected():
    base = transcript(["אייג'נטים", "יוזרים", "קונטיינרים", "agentים"])
    donor = transcript(["agents", "users", "containers", "agent-ים"], .99)
    merged, mods = align_and_merge(base, donor)
    assert mods == []
    assert "אייג'נטים" in merged["text"]
    assert "agentים" in merged["text"]


def test_correct_transcript_and_inputs_are_preserved():
    base = transcript(["OneCLI"])
    donor = transcript(["OneCLI"], .99)
    snapshot = copy.deepcopy((base, donor))
    merged, mods = align_and_merge(base, donor)
    assert not mods
    assert merged["text"] == "OneCLI"
    assert (base, donor) == snapshot


def test_multiword_english_correction():
    base = transcript(["Sum", "Security", "Best", "Practices"], step=.6)
    donor = transcript(["some", "security", "best", "practices"], .99, step=.6)
    merged, mods = align_and_merge(base, donor)
    assert "some security best practices" in merged["text"]
    assert mods and all(m["donor_token_indices"] for m in mods)


def test_distant_timestamp_disagreement_not_applied():
    merged, mods = align_and_merge(
        transcript(["1CRI"]), transcript(["OneCLI"], .99, shift=20),
    )
    assert mods == [] and merged["text"] == "1CRI"


def test_provenance_grounded_in_actual_donor_tokens():
    merged, mods = align_and_merge(
        transcript(["1CRI"]), transcript(["OneCLI"], .98),
    )
    assert len(mods) == 1
    m = mods[0]
    assert m["donor_token_indices"] == [0]
    assert m["base_token_indices"] == [0]
    assert m["donor_confidence"] == pytest.approx(.98)
    assert 0 <= m["alignment_similarity"] <= 1
    assert merged["provenance"]["version"] == 2


def test_invalid_thresholds_rejected():
    with pytest.raises(ValueError):
        align_and_merge({}, {}, time_tolerance=-1)


def test_low_confidence_subword_not_hidden_by_confident_letters():
    base = transcript(["1CRI"])
    donor = {"tokens": [
        {"text": " One", "start": 0.0, "end": .10, "confidence": .70},
        {"text": "C", "start": .10, "end": .20, "confidence": .99},
        {"text": "L", "start": .20, "end": .30, "confidence": .99},
        {"text": "I", "start": .30, "end": .55, "confidence": .99},
    ]}
    merged, mods = align_and_merge(base, donor)
    assert not mods
    assert merged["text"] == "1CRI"


def test_multitoken_edit_merges_timing_without_reusing_old_confidence():
    base = {"tokens": [
        {"text": " 1", "start": 1., "end": 1.2, "confidence": .2},
        {"text": ".cli", "start": 1.2, "end": 1.6, "confidence": .2},
    ]}
    donor = {"tokens": [
        {"text": " OneCLI", "start": 1., "end": 1.6, "confidence": .98},
    ]}
    merged, mods = align_and_merge(base, donor)
    assert len(mods) == 1
    assert len(merged["tokens"]) == 1
    assert merged["tokens"][0]["end"] == pytest.approx(1.6)
    assert merged["tokens"][0]["confidence"] is None


def test_no_token_fallback_preserves_original_base_text():
    base = {"provider": "base", "text": "הטקסט המקורי.", "tokens": []}
    merged, mods = align_and_merge(base, transcript(["OneCLI"], .99))
    assert merged["text"] == base["text"]
    assert not mods
