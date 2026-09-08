import json
from types import SimpleNamespace

import pytest

from analysis.lesson_bank_v4 import attempt, counted_failure, total_spending


@pytest.mark.parametrize("code,pending,expected", [
    ("invalid_native_arguments", 0, True), ("response_incomplete", 0, True),
    ("recipient_limit_or_deadline", 0, True), ("http_error", 0, False),
    ("network_failure", 532372800, False), ("invalid_usage", 0, False),
    ("invalid_native_arguments", 532372800, False)])
def test_only_fully_settled_model_mistakes_can_be_scored(code, pending, expected):
    adapter = SimpleNamespace(meters=[SimpleNamespace(failure_code=code)])
    assert counted_failure({"usage": {"calls": 6}}, adapter,
        {"unresolved_reservation_nano_usd": pending}) is expected


def test_failure_consumes_recipient_without_repair_or_retry(monkeypatch, tmp_path):
    calls = []
    def failed(*args):
        calls.append(1)
        (tmp_path/"result.json").write_text(json.dumps({"passed": False, "integrity_valid": False,
            "usage": {"calls": 6}, "error": "RuntimeError"}))
        raise RuntimeError("model output failed")
    monkeypatch.setattr("analysis.lesson_bank_v4.run_recipient", failed)
    adapter = SimpleNamespace(meters=[SimpleNamespace(failure_code="invalid_native_arguments")])
    guard = SimpleNamespace(snapshot=lambda: {"unresolved_reservation_nano_usd": 0})
    row = attempt(adapter, {}, [], "lesson", tmp_path, guard)
    assert len(calls) == 1 and not row["passed"] and row["integrity_valid"]
    assert row["outcome"] == "model_failure_counted" and row["usage"]["calls"] == 6


def test_individual_journals_preserve_entire_prior_and_pending_charge():
    original = 1462606300
    snapshots = [{"prior_upper_nano_usd": original, "measured_usage_upper_nano_usd": 1000,
                  "unresolved_reservation_nano_usd": 0, "requests_reserved": 1, "blocked": True},
                 {"prior_upper_nano_usd": original+1000, "measured_usage_upper_nano_usd": 700,
                  "unresolved_reservation_nano_usd": 532372800, "requests_reserved": 2, "blocked": True}]
    result = total_spending(original, snapshots)
    assert result["total_upper_nano_usd"] == original + 1700 + 532372800
    assert result["requests_reserved"] == 3 and result["blocked"]
