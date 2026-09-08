import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hive_learning.cloud_study import read_plan
from hive_learning.ledger import digest
from hive_learning.lesson_study import (ARMS, assess_confirmation, choose_signal, neutral_lesson,
                                        public_record, run_stage, sign_p)

ROOT = Path(__file__).resolve().parents[1]


def complete_confirmation(endpoint="accuracy"):
    study = json.loads((ROOT / "examples/lesson-study-v2.json").read_text())
    rows = []
    for case in study["cases"]:
        if (case["family"] == "paired_sort" and case["split"] == "confirmation") or case["split"] == "retention":
            for arm in ARMS:
                rows.append({"case_id": case["id"], "arm": arm, "integrity_valid": True,
                             "passed": arm == "lesson" or case["split"] == "retention",
                             "usage": {"calls": 8 if arm == "lesson" else 12}})
    return study, {"selection": {"family": "paired_sort", "endpoint": endpoint}, "confirmation": rows}


def test_confirmation_requires_full_frozen_sample_and_both_controls():
    study, state = complete_confirmation()
    assert assess_confirmation(state, study)["verdict"] == "CONFIRMED_GAIN"
    partial = copy.deepcopy(state)
    partial["confirmation"].pop()
    assert assess_confirmation(partial, study)["verdict"] == "INCOMPLETE"
    partial["confirmation"].append(partial["confirmation"][0])
    assert assess_confirmation(partial, study)["verdict"] == "INCOMPLETE"
    for row in state["confirmation"]:
        if row["arm"] == "neutral":
            row["passed"] = True
    assert assess_confirmation(state, study)["verdict"] == "GAIN_NOT_CONFIRMED"


def test_confirmation_rejects_retention_harm_and_integrity_failure():
    study, state = complete_confirmation()
    row = next(r for r in state["confirmation"] if r["case_id"].startswith("retention") and r["arm"] == "lesson")
    row["passed"] = False
    assert assess_confirmation(state, study)["verdict"] == "GAIN_NOT_CONFIRMED"
    row["passed"], row["integrity_valid"] = True, False
    assert assess_confirmation(state, study)["verdict"] == "INVALID"


def test_efficiency_never_rewards_fast_wrong_answers():
    study, state = complete_confirmation("model_calls")
    assert assess_confirmation(state, study)["verdict"] == "GAIN_NOT_CONFIRMED"
    for row in state["confirmation"]:
        row["passed"] = True
    assert assess_confirmation(state, study)["verdict"] == "CONFIRMED_GAIN"
    state["confirmation"][0]["passed"] = False
    assert assess_confirmation(state, study)["verdict"] == "GAIN_NOT_CONFIRMED"


def test_sign_test_and_development_selection():
    assert sign_p(6, 0) == 0.015625
    assert sign_p(0, 0) == 1
    assert sign_p(2, 0) == .25
    rows = [{"family": "current_input", "arm": arm, "integrity_valid": True,
             "passed": True, "usage": {"calls": 8 if arm == "lesson" else 10}} for arm in ARMS]
    assert choose_signal(rows)["endpoint"] == "model_calls"
    rows[0]["usage"]["calls"] = 8
    assert choose_signal(rows) is None
    rows[0]["passed"] = rows[2]["passed"] = False
    assert choose_signal(rows)["endpoint"] == "accuracy"


def test_public_experience_excludes_grading_and_unverified_claims(tmp_path):
    state_dir = tmp_path / ".agent_runs/hive/objective"
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text(json.dumps({"evidence": {
        "observed": {"verified": True, "payload": {"tool": "pytest", "arguments": {}, "output": "public failure"}},
        "claim": {"verified": False, "payload": {"tool": "pytest", "arguments": {}, "output": "unverified"}}
    }}))
    record = public_record(tmp_path, {"id": "sample", "goal": "repair", "files": {"a.py": "broken"}},
                           {"candidate": {"a.py": "actual patch"}, "score": {"secret": "protected body"}})
    encoded = json.dumps(record)
    assert "public failure" in encoded and "actual patch" in encoded
    assert "protected body" not in encoded and "unverified" not in encoded


def test_no_paid_work_on_consumed_stage(tmp_path):
    previous = {"study_sha256": "frozen", "stages": [{"stage": "formation", "status": "running"}]}
    with pytest.raises(ValueError, match="already consumed"):
        run_stage(SimpleNamespace(), {}, "frozen", "formation", tmp_path, previous)


def test_neutral_word_count_and_committed_preflight():
    lesson = {"when": "when sorting data", "summary": "keep associated values together", "rationale": "pair identities matter"}
    neutral = neutral_lesson(lesson)
    assert {k: len(v.split()) for k, v in lesson.items()} == {k: len(v.split()) for k, v in neutral.items()}
    assert neutral != lesson
    plan, study, prior, previous = read_plan(ROOT)
    assert prior["spending"]["total_upper_nano_usd"] >= 26646000
    preflight = json.loads((ROOT / "results/lesson-v2-preflight.json").read_text())
    assert preflight["validated_cases_sha256"] == digest(study["cases"])
    assert len(preflight["cases"]) == 92
    assert all(c["before"]["valid"] and not c["before"]["passed"] and c["reference"]["passed"] for c in preflight["cases"])
