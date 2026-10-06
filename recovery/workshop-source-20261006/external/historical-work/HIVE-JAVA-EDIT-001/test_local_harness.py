"""No-model checks of the local-only study boundary and outcome taxonomy."""

import pytest

from local_harness import (
    MODEL, OUTCOME_CLASSES, PreflightFailure, build_request, classify,
    no_cloud_key, reference_freeze, task_specs,
)


def test_known_task_and_frozen_test_hashes_match_unchanged_reference():
    tasks = task_specs(reference_freeze())
    assert [task["id"] for task in tasks] == [f"T{i:03d}" for i in range(1, 9)] + [
        f"N{i:03d}" for i in range(1, 9)]
    assert len({task["test_sha256"] for task in tasks}) == 16
    assert next(task for task in tasks if task["id"] == "T005")["expected_cases"] == 2


def test_request_mechanically_forbids_cloud_and_promotion():
    task = task_specs(reference_freeze())[0]
    request = build_request(task, {
        "local_model": {"tag": MODEL}, "baseline": {"root": "C:/frozen/baseline"},
        "lock_sha256": "a" * 64,
    }, "b" * 12)
    assert request["allow_cloud"] is False
    assert request["max_tier"] == "local" and request["max_cost"] == 0.0
    assert request["agent_backend"] == "classic"
    assert request["local_model"] == MODEL
    assert request["allow_external_root"] is True
    assert "approved" not in request and "apply" not in request
    assert request["frozen_junit_tests"][0]["expected_cases"] == 1


def test_key_presence_fails_closed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-unusable-key")
    with pytest.raises(PreflightFailure, match="Cloud credential"):
        no_cloud_key()


def test_outcome_classes_separate_model_runtime_verifier_and_false_acceptance():
    assert set(OUTCOME_CLASSES) == {
        "VERIFIED_SUCCESS", "MODEL_TASK_FAILURE", "VERIFIER_INFRA_FAILURE",
        "LOCAL_RUNTIME_FAILURE", "HARNESS_FAILURE", "FALSE_ACCEPTANCE", "INVALID",
    }
    gates = {"passed": True, "checks": [
        {"name": "frozen_junit_acceptance", "passed": True},
        {"name": "full_gradle_check", "passed": True},
    ]}
    assert classify({"status": "ready", "verification": gates}) == "VERIFIED_SUCCESS"
    assert classify({"status": "ready", "verification": {"passed": False}}) == "FALSE_ACCEPTANCE"
    assert classify({"status": "rejected", "verification": {"passed": False,
        "checks": [{"name": "frozen_junit_acceptance", "passed": False,
                    "detail": "expected 1, observed 0"}]}}) == "MODEL_TASK_FAILURE"
    assert classify({"status": "rejected", "verification": {"passed": False,
        "checks": [{"name": "frozen_junit_acceptance", "passed": False,
                    "detail": "pthread_create failed (EAGAIN)"}]}}) == "VERIFIER_INFRA_FAILURE"
    assert classify({"status": "failed", "metadata": {"agent_calls": [
        {"provider": "ollama", "status": "failed"}]}}) == "LOCAL_RUNTIME_FAILURE"
    assert classify({"status": "failed", "metadata": {"agent_calls": [
        {"provider": "openai_agents", "status": "completed"}]}}) == "INVALID"
    assert classify({"status": "failed", "external_baseline_integrity": {
        "baseline_unchanged": False}}) == "INVALID"
