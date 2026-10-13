"""Tests for the hybrid Hebrew-English ASR alignment and fusion engine."""

import json
from pathlib import Path

import pytest

from langtalks.hybrid import (
    DonorWord,
    align_and_merge,
    assemble_donor_words,
    extract_hebrew_prefix,
    extract_latin_donor_phrases,
    is_hebrewized_loanword,
)
from langtalks.score import load_reference, score

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT_DIR = ROOT / "langtalks" / "out" / "transcripts"
REFERENCE_DIR = ROOT / "langtalks" / "reference"
EP71_GUID = "74fc0625-0a6b-4ca1-9488-31be7860360d"


def test_assemble_donor_words_from_soniox_subwords():
    raw_tokens = [
        {"text": " One", "start": 1.0, "end": 1.2, "confidence": 0.95},
        {"text": "C", "start": 1.2, "end": 1.3, "confidence": 0.99},
        {"text": "L", "start": 1.3, "end": 1.4, "confidence": 0.99},
        {"text": "I", "start": 1.4, "end": 1.5, "confidence": 0.99},
        {"text": " זה", "start": 1.6, "end": 1.8, "confidence": 0.98},
    ]
    words = assemble_donor_words(raw_tokens)
    assert len(words) == 2
    assert words[0].text == " OneCLI"
    assert words[0].start == 1.0
    assert words[0].end == 1.5
    assert words[0].confidence > 0.95
    assert words[0].token_indices == [0, 1, 2, 3]

    assert words[1].text == " זה"
    assert words[1].start == 1.6
    assert words[1].end == 1.8


def test_extract_latin_donor_phrases():
    words = [
        DonorWord(text="זה", start=1.0, end=1.2, confidence=0.99),
        DonorWord(text="Google", start=1.3, end=1.6, confidence=0.98),
        DonorWord(text="Workspace", start=1.7, end=2.0, confidence=0.99),
        DonorWord(text="שלנו", start=2.1, end=2.3, confidence=0.97),
    ]
    phrases = extract_latin_donor_phrases(words, max_phrase_words=2)
    texts = [p.text for p in phrases]
    assert "Google" in texts
    assert "Workspace" in texts
    assert "Google Workspace" in texts
    assert "זה" not in texts
    assert "שלנו" not in texts


def test_hebrewized_loanwords_protection():
    assert is_hebrewized_loanword("users", "כל היוזרים במערכת") is True
    assert is_hebrewized_loanword("user", "זה מיועד ליוזר") is True
    assert is_hebrewized_loanword("agents", "שני אייג'נטים רצים") is True
    assert is_hebrewized_loanword("agent", "האג'נט עובד") is True
    assert is_hebrewized_loanword("containers", "בתוך קונטיינרים נפרדים") is True
    assert is_hebrewized_loanword("processes", "הפרוססים פתוחים") is True
    assert is_hebrewized_loanword("multi-tenant", "ארכיטקטורת מולטי-טננט") is True

    # Real products/libraries must NOT be protected from Latin insertion
    assert is_hebrewized_loanword("NanoClaw", "הרצנו ננוקו") is False
    assert is_hebrewized_loanword("OneCLI", "השתמשנו ב-1.cli") is False
    assert is_hebrewized_loanword("Hermes", "הרמז") is False


def test_extract_hebrew_prefix():
    assert extract_hebrew_prefix("ו-Hermes") == ("ו-", "Hermes")
    assert extract_hebrew_prefix("ב-OneCLI") == ("ב-", "OneCLI")
    assert extract_hebrew_prefix("מ-Google") == ("מ-", "Google")
    assert extract_hebrew_prefix("בruntime") == ("ב-", "runtime")
    assert extract_hebrew_prefix("OneCLI") == ("", "OneCLI")
    assert extract_hebrew_prefix("שלום") == ("", "שלום")


def test_surgical_subword_replacement():
    base_transcript = {
        "provider": "base_test",
        "tokens": [
            {"text": " אנחנו", "start": 0.0, "end": 0.5},
            {"text": " מריצים", "start": 0.5, "end": 0.9},
            {"text": " 1", "start": 1.0, "end": 1.2},
            {"text": ".cli", "start": 1.2, "end": 1.5},
            {"text": " בסביבה", "start": 1.6, "end": 2.0},
        ],
    }
    donor_transcript = {
        "provider": "donor_test",
        "tokens": [
            {"text": " One", "start": 1.0, "end": 1.2, "confidence": 0.98},
            {"text": "C", "start": 1.2, "end": 1.3, "confidence": 0.99},
            {"text": "L", "start": 1.3, "end": 1.4, "confidence": 0.99},
            {"text": "I", "start": 1.4, "end": 1.5, "confidence": 0.99},
        ],
    }
    merged, mods = align_and_merge(base_transcript, donor_transcript)
    assert len(mods) == 1
    assert mods[0]["donor_term"] == "OneCLI"
    assert "אנחנו מריצים OneCLI בסביבה" in merged["text"]
    assert any(t["text"] == " אנחנו" for t in merged["tokens"])
    assert any(t["text"] == " בסביבה" for t in merged["tokens"])


def test_provenance_completeness():
    base_transcript = {
        "provider": "base_test",
        "tokens": [
            {"text": " והרמז", "start": 507.7, "end": 508.3},
        ],
    }
    donor_transcript = {
        "provider": "donor_test",
        "tokens": [
            {"text": " Hermes", "start": 507.7, "end": 508.3, "confidence": 0.97},
        ],
    }
    merged, mods = align_and_merge(base_transcript, donor_transcript)
    assert len(mods) == 1
    mod = mods[0]
    for required_key in [
        "index",
        "original_text",
        "replacement_text",
        "start_s",
        "end_s",
        "donor_term",
        "donor_confidence",
        "rule",
    ]:
        assert required_key in mod

    assert "provenance" in merged
    assert merged["provenance"]["strategy"] == "timestamp_aligned_confidence_fusion"
    assert merged["provenance"]["modifications_count"] == 1


def test_cached_episode71_hybrid_benchmark_reaches_high_accuracy():
    base_path = TRANSCRIPT_DIR / f"{EP71_GUID}.local_ivrit_turbo.json"
    donor_path = TRANSCRIPT_DIR / f"{EP71_GUID}.soniox.json"
    ref_path = REFERENCE_DIR / f"{EP71_GUID}.json"

    if not base_path.exists() or not donor_path.exists() or not ref_path.exists():
        pytest.skip("Episode 71 cached files not present in workspace")

    with open(base_path, encoding="utf-8") as f:
        base_data = json.load(f)
    with open(donor_path, encoding="utf-8") as f:
        donor_data = json.load(f)

    merged, mods = align_and_merge(base_data, donor_data)
    reference = load_reference(ref_path)

    res = score(merged["text"], merged["tokens"], reference)
    assert res["overall"] > 0.90, f"Overall score {res['overall']} fell below 0.90"
    assert res["components"]["term_recall"] > 0.85, "Term recall fell below 0.85"
    assert res["components"]["hebrew_accuracy"] > 0.95, "Hebrew accuracy fell below 0.95"
    assert res["components"]["term_precision"] == 1.0, "Hallucinated terms found"

