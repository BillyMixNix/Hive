"""Post-study diagnostic classifier tests; never rewrite frozen study results."""

import hashlib
import json
from pathlib import Path

import pytest

from local_harness import classify


HERE = Path(__file__).resolve().parent
IDS = ("T002", "N006", "N008")


@pytest.mark.parametrize("task_id", IDS)
def test_original_misclassified_run_and_portable_fixture(task_id):
    fixture = json.loads((HERE / "classifier-fixtures" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert classify(fixture["run"]) == fixture["expected_reclassification"]
    original = HERE.parent / "HIVE-LOCAL-001" / "execution" / task_id / "run.json"
    if original.is_file():
        content = original.read_bytes()
        assert hashlib.sha256(content).hexdigest() == fixture["source_run_sha256"]
        assert classify(json.loads(content)) == fixture["expected_reclassification"]


def test_routine_gradle_cache_notice_does_not_make_model_failure_infrastructure():
    run = {"status": "rejected", "errors": [{"exception_type": "TargetedVerificationError",
            "exception_message": "targeted verification failed",
            "targeted_verification": {"checks": [{"name": "frozen_junit_acceptance", "passed": False,
                "detail": {"stdout_tail": "Shared read-only dependency cache is an incubating feature.\n> Task :compileJava FAILED",
                           "stderr_tail": "/work/candidate/src/main/java/example/A.java:1: error: cannot find symbol"}}]}}]}
    assert classify(run) == "MODEL_TASK_FAILURE"


def test_true_verifier_resource_failure_stays_infrastructure():
    run = {"status": "rejected", "verification": {"checks": [{
        "name": "frozen_junit_acceptance", "passed": False,
        "detail": {"stderr_tail": "pthread_create failed (EAGAIN): unable to create native thread"}}]}}
    assert classify(run) == "VERIFIER_INFRA_FAILURE"

