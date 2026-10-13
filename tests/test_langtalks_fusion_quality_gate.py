"""Small tests for objective quality gates; the expensive replay runs in CI."""
import copy

import pytest

from langtalks.fusion_audit_eval import assert_no_development_regression


def example():
    s = {"one_to_one_timed_occurrence_diagnostic": {"matched": 35},
         "word_error_rate": .12, "hebrew_character_accuracy": .91,
         "known_loanword_recall": {"observed": 14}}
    t = copy.deepcopy(s)
    t["one_to_one_timed_occurrence_diagnostic"]["matched"] = 40
    t["word_error_rate"] = .10
    t["hebrew_character_accuracy"] = .93
    t["known_loanword_recall"]["observed"] = 15
    return {"previous_hybrid": s, "revised_hybrid": t,
            "changes": [{"donor_token_indices": [2], "base_token_indices": [5]}]}


def test_nonregressive_metrics_pass():
    assert_no_development_regression(example())


@pytest.mark.parametrize("field,bad", [
    ("word_error_rate", .15),
    ("hebrew_character_accuracy", .89),
])
def test_development_gate_fails_on_transcript_regression(field, bad):
    report = example()
    report["revised_hybrid"][field] = bad
    with pytest.raises(AssertionError):
        assert_no_development_regression(report)


def test_development_gate_fails_on_missing_donor_evidence():
    report = example()
    report["changes"][0]["donor_token_indices"] = []
    with pytest.raises(AssertionError):
        assert_no_development_regression(report)
