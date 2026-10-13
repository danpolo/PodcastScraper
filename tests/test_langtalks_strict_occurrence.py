"""Strict occurrence matching guards against reusing one emission twice."""
from langtalks.strict_occurrence import timed_term_recall_strict


def test_single_emission_cannot_satisfy_two_overlapping_reference_mentions():
    ref = {"technical_terms": ["OneCLI"], "verified_occurrences": [
        {"surface": "OneCLI", "start": 10.0, "end": 10.2, "review_status": "verified"},
        {"surface": "OneCLI", "start": 10.6, "end": 10.8, "review_status": "verified"},
    ]}
    tokens = [{"text": " OneCLI", "start": 10.3, "end": 10.5}]
    result = timed_term_recall_strict(tokens, ref)
    assert result["matched"] == 1
    assert result["total"] == 2


def test_subword_product_name_can_match_a_single_occurrence():
    ref = {"technical_terms": ["OneCLI"], "verified_occurrences": [
        {"surface": "OneCLI", "start": 25, "end": 26, "review_status": "verified"},
    ]}
    tokens = [
        {"text": " One", "start": 25.1, "end": 25.3},
        {"text": "C", "start": 25.3, "end": 25.4},
        {"text": "LI", "start": 25.4, "end": 25.6},
    ]
    result = timed_term_recall_strict(tokens, ref)
    assert result["matched"] == 1
    assert result["recall"] == 1.0


def test_no_false_match_from_coarse_or_missing_timestamps():
    ref = {"technical_terms": ["Hermes"], "verified_occurrences": [
        {"surface": "Hermes", "start": 507, "end": 508, "review_status": "verified"},
    ]}
    tokens = [{"text": " Hermes", "start": 500, "end": 515}]
    result = timed_term_recall_strict(tokens, ref)
    assert result["matched"] == 0
