import json

import pytest

from self_diagnosis import SelfDiagnosis, SelfDiagnosisLedger


def valid_payload():
    return {
        "run_id": "run-17",
        "goal": "preserve path-specific regression selection",
        "observed": "a regression for pkg_a/router.py also matches pkg_b/router.py",
        "expected": "only exact logical paths match when a path is supplied",
        "divergence": "basename fallback collapses distinct files",
        "contributing_component": "regression_gate._case_matches_target",
        "scope": "systemic",
        "cause": "target matching treats equal basenames as equivalent paths",
        "proposed_change": "use exact normalized path matching when the requested target contains a directory",
        "expected_improvement": "regressions execute only against the file they describe",
        "risks": ["callers that intentionally supplied only a basename must retain basename behavior"],
        "falsification_test": "record same-basename cases in two directories and assert each path selects only its own case",
        "evidence": [{
            "source": "source-inspection",
            "observation": "_case_matches_target returns true when Path(case_target).name equals Path(requested).name",
            "artifact": "regression_gate.py",
        }],
        "confidence": 0.99,
    }


def test_diagnosis_requires_evidence():
    payload = valid_payload()
    payload["evidence"] = []
    with pytest.raises(ValueError, match="at least one evidence"):
        SelfDiagnosis.from_dict(payload)


def test_diagnosis_requires_falsifiable_experiment():
    payload = valid_payload()
    payload["falsification_test"] = ""
    with pytest.raises(ValueError, match="falsification_test"):
        SelfDiagnosis.from_dict(payload)


def test_diagnosis_rejects_invalid_confidence():
    payload = valid_payload()
    payload["confidence"] = 1.1
    with pytest.raises(ValueError, match="between 0 and 1"):
        SelfDiagnosis.from_dict(payload)


def test_ledger_round_trip_is_append_only(tmp_path):
    ledger = SelfDiagnosisLedger(tmp_path / "diagnoses.jsonl")
    first = SelfDiagnosis.from_dict(valid_payload())
    second_payload = valid_payload()
    second_payload["run_id"] = "run-18"
    second = SelfDiagnosis.from_dict(second_payload)

    ledger.append(first)
    ledger.append(second)

    loaded = ledger.load()
    assert [item.run_id for item in loaded] == ["run-17", "run-18"]
    lines = (tmp_path / "diagnoses.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["run_id"] == "run-17"
    assert json.loads(lines[1])["run_id"] == "run-18"
