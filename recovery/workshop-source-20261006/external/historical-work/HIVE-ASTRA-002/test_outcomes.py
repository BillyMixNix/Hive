from outcomes import Outcome, classify


def test_distinct_success_task_and_false_acceptance():
    gates = {"acceptance": {"passed": True}, "full_gate": {"passed": True}}
    assert classify({"status": "ready", **gates}) is Outcome.VERIFIED_SUCCESS
    assert classify({"status": "rejected", "acceptance": {"passed": False}}) is Outcome.MODEL_TASK_FAILURE
    assert classify({"status": "ready", "acceptance": {"passed": True}}) is Outcome.FALSE_ACCEPTANCE
    assert classify({"status": "rejected", **gates}) is Outcome.MODEL_TASK_FAILURE


def test_verifier_resource_and_provider_failures_are_not_task_failures():
    assert classify({"status": "rejected", "acceptance": {"passed": False,
        "detail": {"stderr_tail": "pthread_create failed (EAGAIN)"}}}) is Outcome.VERIFIER_INFRA_FAILURE
    assert classify({"status": "model_failed", "model": {"error_message":
        "Agents API 503 server_overloaded"}}) is Outcome.PROVIDER_INFRA_FAILURE


def test_oversize_control_input_is_harness_failure():
    assert classify({"status": "model_failed", "model": {"session_id": None, "turns": 0,
        "error_message": "Agents API 400 string_above_max_length"}}) is Outcome.HARNESS_FAILURE


def test_integrity_violation_and_unknown_state_fail_closed():
    assert classify({"status": "rejected", "integrity_violation": True}) is Outcome.INVALID
    assert classify({"status": "mystery"}) is Outcome.INVALID
