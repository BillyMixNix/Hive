"""Offline tests of paid-request admission, accounting, redaction and rerun gates."""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from hive_learning.cloud_trial import BRANCH, LAUNCH_MESSAGE, allowed_launch
from hive_learning.openai_adapter import OpenAIHive
from hive_learning.spending import (CONTEXT_TOKENS, INPUT_NUSD, LIMIT_NUSD, MODEL,
                                    OUTPUT_NUSD, SpendingGuard)


NOW = datetime(2026, 9, 8, 8, tzinfo=timezone.utc)
KEY = "test_credential_not_a_real_api_key"
MESSAGES = [{"role": "user", "content": "Return JSON."}]


def test_cumulative_ceiling_is_enforced_before_network_even_with_new_meters(monkeypatch, tmp_path):
    guard = SpendingGuard(tmp_path / "budget.jsonl", now=NOW)
    adapter = OpenAIHive(MODEL, KEY, max_requests=325, spending=guard)
    requests = []
    def opened(self, request, **kwargs):
        requests.append(request)
        assert guard.pending == guard.reservation
        persisted = json.loads((tmp_path / "budget.jsonl").read_text().splitlines()[-1])
        assert persisted["event"] == "reserved_before_network"
        assert persisted["total_upper_nano_usd"] <= LIMIT_NUSD
        body = json.loads(request.data)
        assert body["service_tier"] == "default" and "tools" not in body
        return io.BytesIO(json.dumps({"model": MODEL, "status": "completed", "error": None,
            "service_tier": "default", "usage": {"input_tokens": CONTEXT_TOKENS, "output_tokens": 4096},
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "{}"}]}]}).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opened)
    accepted = LIMIT_NUSD // guard.reservation
    for _ in range(accepted):
        adapter._new_meter(36)(MESSAGES)
    with pytest.raises(RuntimeError, match="remaining trial budget"):
        adapter._new_meter(36)(MESSAGES)
    assert len(requests) == accepted == adapter.budget.calls
    assert guard.snapshot()["total_upper_nano_usd"] <= LIMIT_NUSD
    assert guard.blocked
    guard.close()


def test_small_measured_requests_refund_reservation_without_resetting_total(tmp_path):
    guard = SpendingGuard(tmp_path / "budget.jsonl", now=NOW)
    for _ in range(325):
        guard.reserve()
        guard.settle(MODEL, 10000, 1000, "default")
    assert guard.committed == 325 * (10000 * INPUT_NUSD + 1000 * OUTPUT_NUSD)
    assert guard.pending == 0 and guard.committed < LIMIT_NUSD
    guard.close()


@pytest.mark.parametrize("kind", ["network", "missing_usage", "wrong_model", "wrong_tier", "quota"])
def test_ambiguous_request_keeps_entire_reservation_and_blocks_paid_retry(monkeypatch, tmp_path, kind):
    guard = SpendingGuard(tmp_path / "budget.jsonl", now=NOW)
    adapter = OpenAIHive(MODEL, KEY, max_requests=325, spending=guard)
    requests = []
    def opened(self, request, **kwargs):
        requests.append(request)
        if kind == "network":
            raise urllib.error.URLError(KEY)
        if kind == "quota":
            body = json.dumps({"error": {"code": "insufficient_quota", "message": KEY}}).encode()
            raise urllib.error.HTTPError(request.full_url, 429, KEY, {}, io.BytesIO(body))
        value = {"model": MODEL, "service_tier": "default", "usage": {"input_tokens": 20, "output_tokens": 10}}
        if kind == "missing_usage": del value["usage"]
        if kind == "wrong_model": value["model"] = "different"
        if kind == "wrong_tier": value["service_tier"] = "priority"
        return io.BytesIO(json.dumps(value).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opened)
    with pytest.raises((ValueError, RuntimeError)) as caught:
        adapter._new_meter(1)(MESSAGES)
    assert KEY not in str(caught.value)
    if kind == "quota": assert "insufficient_quota" in str(caught.value)
    with pytest.raises(RuntimeError): adapter._new_meter(36)(MESSAGES)
    assert len(requests) == 1 and guard.pending == guard.reservation and guard.blocked
    assert KEY not in (tmp_path / "budget.jsonl").read_text()
    guard.close()


def test_restart_expired_prices_and_overlapping_requests_are_refused(tmp_path):
    path = tmp_path / "budget.jsonl"
    guard = SpendingGuard(path, now=NOW)
    guard.reserve()
    with pytest.raises(RuntimeError): guard.reserve()
    guard.close()
    with pytest.raises(FileExistsError): SpendingGuard(path, now=NOW)
    with pytest.raises(ValueError):
        SpendingGuard(tmp_path / "later.jsonl", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert not (tmp_path / "later.jsonl").exists()


def test_only_the_single_authorized_push_first_attempt_can_start():
    env = {"GITHUB_REPOSITORY": "BillyMixNix/Hive", "GITHUB_REF": BRANCH,
           "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ATTEMPT": "1",
           "HIVE_LAUNCH_PARENT": "a" * 40, "GITHUB_SHA": "b" * 40}
    event = {"before": "a" * 40, "head_commit": {"id": "b" * 40, "message": LAUNCH_MESSAGE}}
    assert allowed_launch(env, event)
    for key, value in [("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_EVENT_NAME", "workflow_dispatch"),
                       ("GITHUB_REPOSITORY", "another/Hive"), ("GITHUB_SHA", "c" * 40),
                       ("GITHUB_REF", "refs/heads/main"), ("HIVE_LAUNCH_PARENT", "d" * 40)]:
        assert not allowed_launch({**env, key: value}, event)
    assert not allowed_launch(env, {**event, "before": "c" * 40})


def test_cloud_report_exports_the_actual_ledger_and_never_inherits_key(monkeypatch, tmp_path, capsys):
    from hive_learning import cloud_trial
    from hive_learning.demo import ScriptedAdapter
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "a" * 40,
                     "head_commit": {"id": "b" * 40, "message": LAUNCH_MESSAGE}}))
    env = {"GITHUB_REPOSITORY": "BillyMixNix/Hive", "GITHUB_REF": BRANCH,
           "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ATTEMPT": "1",
           "HIVE_LAUNCH_PARENT": "a" * 40, "GITHUB_SHA": "b" * 40,
           "GITHUB_EVENT_PATH": str(event), "GITHUB_RUN_ID": "offline-fixture",
           "OPENAI_API_KEY": KEY, "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}
    for key, value in env.items(): monkeypatch.setenv(key, value)
    def offline_adapter(*args, **kwargs):
        assert "OPENAI_API_KEY" not in os.environ
        return ScriptedAdapter()
    def no_network(*args, **kwargs): raise AssertionError("offline test")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    monkeypatch.setattr(cloud_trial, "OpenAIHive", offline_adapter)
    monkeypatch.setattr(cloud_trial, "SpendingGuard", lambda path: SpendingGuard(path, now=NOW))
    monkeypatch.setattr("sys.argv", ["cloud_trial", str(tmp_path / "evidence")])
    assert cloud_trial.main() == 0
    report = json.loads((tmp_path / "evidence/report.json").read_text())
    assert report["scope"] == "development_simulated" and report["ledger_verified"]
    assert len(report["trials"]) == 9 and report["spending"]["requests_reserved"] == 0
    assert report["ordinary_jarvis_guidance"] == 0
    assert KEY not in capsys.readouterr().out
    for name in ("report.json", "events.json", "manifest.json", "spending.jsonl"):
        assert KEY not in (tmp_path / "evidence" / name).read_text()
