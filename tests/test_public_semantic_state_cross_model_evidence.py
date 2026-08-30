"""Regression tests for the public semantic-state evidence verifier."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


VERIFIER_PATH = (
    Path(__file__).resolve().parents[1]
    / "evidence"
    / "semantic_state_cross_model_2026-08"
    / "verify.py"
)
SPEC = importlib.util.spec_from_file_location("semantic_state_evidence_verifier", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
_previous_dont_write_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    SPEC.loader.exec_module(VERIFIER)
finally:
    sys.dont_write_bytecode = _previous_dont_write_bytecode


@pytest.mark.parametrize(
    ("selected", "correct", "truth"),
    [
        ("C", "C", "current"),
        ("A", "C", "historical"),
        ("B", "C", "planned"),
        ("D", "C", "hallucinated"),
        ("INSUFFICIENT", "C", None),
    ],
)
def test_secondary_truth_is_derived_from_frozen_slots(
    selected: str, correct: str, truth: str | None
) -> None:
    assert VERIFIER.expected_secondary(selected, correct)[0] == truth


def test_internally_consistent_false_truth_class_fails_closed() -> None:
    score = {
        "case_id": "case-1",
        "condition": "LUNA_RAW",
        "selected_label": "A",
        "expected_label": "C",
        "admissible": True,
        "answer_correct": False,
        "grader_status": "ran",
        "grader_agreement": True,
        "secondary_status": "ran",
        # A is historically true when C is current. These fields form a
        # self-consistent but false planned-state classification.
        "truth_class": "planned",
        "chronology_authority_status": "planned_state_selected",
        "chronology_authority_error": True,
        "illegal_state_promotions": 1,
        "failure_reasons": [
            "answer_incorrect",
            "chronology_or_authority_error",
            "illegal_state_promotion",
        ],
    }

    with pytest.raises(VERIFIER.VerificationFailure, match="truth class mismatch"):
        VERIFIER.verify_score(
            score,
            case_id="case-1",
            condition="LUNA_RAW",
            selected="A",
            expected="C",
            label="test/case-1",
        )
