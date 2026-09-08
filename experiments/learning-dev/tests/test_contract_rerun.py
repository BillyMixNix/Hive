"""The new paid launch retains accounting, task parity and failure scoring."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from analysis import contract_rerun as rerun
from hive_learning.spending import CONTEXT_TOKENS, INPUT_NUSD, OUTPUT_NUSD

ROOT = Path(__file__).resolve().parents[1]
STUDY = json.loads((ROOT/"examples/contract-rerun.json").read_text())


def test_frozen_schedule_has_every_task_and_arm_once_and_arms_stay_adjacent():
    rows = rerun.schedule(STUDY)
    assert len(rows) == 45
    assert len({(c["id"], a) for c, a in rows}) == 45
    for start in range(0, 45, 3):
        triple = rows[start:start+3]
        assert len({c["id"] for c, _ in triple}) == 1
        assert {a for _, a in triple} == {"baseline", "lesson", "neutral"}
    assert rows == rerun.schedule(STUDY)


def test_input_declarations_do_not_prohibit_expected_iterator_consumption():
    gated = [c for c in STUDY["cases"] if rerun.contracts(c)]
    assert len(gated) == 11
    assert {c["family"] for c in STUDY["cases"] if not rerun.contracts(c)} == {"single_pass"}
    top = next(c for c in gated if c["id"] == "checkpoint_top_k_pairs")
    assert rerun.contracts(top)[0].arguments == ("keys", "values", "limit")


def test_failed_controller_completion_cannot_receive_low_effort_credit():
    rows = [{"case_id": c["id"], "arm": a, "integrity_valid": True, "passed": True,
             "usage": {"calls": 9}, "controller_decision": "SATISFIED"}
            for c, a in rerun.schedule(STUDY)]
    case_id = next(c["id"] for c in STUDY["cases"] if c["split"] == "confirmation")
    bad = next(r for r in rows if r["case_id"] == case_id and r["arm"] == "lesson")
    bad.update(passed=False, usage={"calls": 1})
    result = rerun.describe({"trials": rows}, STUDY)
    assert result["verdict"] == "DESCRIPTIVE_ONLY"
    assert result["confirmatory_gain_claim_allowed"] is False
    assert result["transfer_successes"]["lesson"] == 11
    assert result["false_completions"]["lesson"] == 1
    assert result["comparisons"]["baseline"]["lesson_penalized_calls"] == 11*9+36
    assert rerun.describe({"trials": rows[:-1]}, STUDY)["verdict"] == "INCOMPLETE"
    assert rerun.describe({"trials": rows+[rows[0]]}, STUDY)["verdict"] == "INVALID"


def test_guard_carries_prior_charge_and_full_unknown_usage_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(rerun.time, "monotonic", lambda: 0)
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 8, 23, tzinfo=timezone.utc)
    monkeypatch.setattr(rerun, "datetime", Clock)
    guard = rerun.RerunSpendingGuard(tmp_path/"spending.jsonl", deadline=100,
        prior_upper_nano_usd=rerun.PRIOR_NUSD,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc))
    guard.reserve()
    reservation = CONTEXT_TOKENS*INPUT_NUSD + 4096*OUTPUT_NUSD
    assert guard.snapshot()["total_upper_nano_usd"] == rerun.PRIOR_NUSD+reservation
    guard.fail()
    with pytest.raises(RuntimeError):
        guard.reserve()
    assert guard.snapshot()["unresolved_reservation_nano_usd"] == reservation
    guard.close()


def test_guard_rechecks_deadline_and_pricing_before_each_request(tmp_path, monkeypatch):
    guard = rerun.RerunSpendingGuard(tmp_path/"spending.jsonl", deadline=100,
        prior_upper_nano_usd=rerun.PRIOR_NUSD,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc))
    monkeypatch.setattr(rerun.time, "monotonic", lambda: 101)
    with pytest.raises(RuntimeError, match="deadline or pricing"):
        guard.reserve()
    monkeypatch.setattr(rerun.time, "monotonic", lambda: 0)
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(rerun, "datetime", Clock)
    with pytest.raises(RuntimeError, match="deadline or pricing"):
        guard.reserve()
    assert guard.snapshot()["requests_reserved"] == 0
    assert guard.snapshot()["total_upper_nano_usd"] == rerun.PRIOR_NUSD
    guard.close()
