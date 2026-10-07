"""Model-free authority tests for the RC1 protected diagnostic boundary."""

import asyncio
import base64
import copy
import json

import pytest

from hive_canonical import diagnostics
from hive_canonical.controller import _protected_agent_call, ProtectedDiagnosticTransportError
from hive_canonical import CandidateSpec, produce_candidate
from hive_canonical.legacy.workshop import hive, hive_review


SCOPE = ("src/main/java/example/Widget.java",)
SENTINEL = "PROTECTED_SENTINEL_001C_XYZZY"


def poisoned_report(location="message"):
    detail = {
        "tests": [{"class_name": SENTINEL, "tests": 3, "failures": 1,
                   "errors": 0, "skipped": 0,
                   "failure_diagnostics": [{"test_name": SENTINEL, "type": SENTINEL,
                                            "message": SENTINEL}]}],
        "stdout_tail": SENTINEL, "stderr_tail": SENTINEL,
        "report_error": SENTINEL, "error": SENTINEL,
        "acceptance_mismatches": [{"class_name": SENTINEL, "message": SENTINEL}],
        "reported_test_failures": [{"message": SENTINEL}],
        "timed_out": False,
    }
    report = {"passed": False, "checks": [{"name": "frozen_junit_acceptance",
                                            "passed": False, "detail": detail}],
              "error": SENTINEL, "diagnostics": {"last_observed_phase": SENTINEL,
                                                "stdout": SENTINEL}}
    if location == "check_name":
        report["checks"][0]["name"] = SENTINEL
    if location == "extra_field":
        report[SENTINEL] = {"schema_version": 1, "verifier_status": "PASSED"}
    return report


@pytest.mark.parametrize("location", ["message", "check_name", "extra_field"])
def test_raw_audit_sentinal_never_enters_structured_model_projection(location):
    raw = poisoned_report(location)
    assert SENTINEL in json.dumps(raw)
    safe = diagnostics.project(raw, phase="TARGETED", scope=SCOPE, expected_cases=3)
    assert isinstance(safe, diagnostics.SafeVerificationDiagnostic)
    assert type(raw) is dict
    encoded = json.dumps(safe)
    assert SENTINEL not in encoded
    assert SENTINEL.encode().hex() not in encoded
    assert base64.b64encode(SENTINEL.encode()).decode() not in encoded
    assert safe["verifier_status"] == "FAILED"
    assert safe["host_expected_cases"] == 3
    assert "reported_xml_counts" not in safe
    assert safe["compilation_status"] == "UNKNOWN"


@pytest.mark.parametrize("payload", [
    {"passed": "false", "checks": []},
    {"passed": False, "checks": "not a list"},
    {"passed": False, "checks": [{"name": "frozen_junit_acceptance", "passed": "false"}]},
])
def test_malformed_report_fails_closed(payload):
    with pytest.raises(diagnostics.DiagnosticBoundaryError):
        diagnostics.project(payload, phase="TARGETED", scope=SCOPE)


@pytest.mark.parametrize("bad", [-1, 10001, "3", True, None, 9876])
def test_candidate_xml_counts_cannot_change_projection(bad):
    raw = poisoned_report()
    ordinary = diagnostics.project(raw, phase="TARGETED", scope=SCOPE, expected_cases=3)
    raw["checks"][0]["detail"]["tests"][0]["tests"] = bad
    assert diagnostics.project(raw, phase="TARGETED", scope=SCOPE, expected_cases=3) == ordinary


def _safe_run(report):
    return {"request": "Change Widget behavior", "diff": "-old\n+new\n",
            "changed_files": list(SCOPE), "verification": copy.deepcopy(report),
            "targeted_verifications": [{"role": "backend", "result": copy.deepcopy(report)}],
            "verified_stage_sha256": "a" * 64}


def test_exact_would_be_correction_and_reviewer_prompts_exclude_verifier_sentinel():
    raw = poisoned_report()
    ctx = diagnostics.SafeRunContext(SCOPE, 3)
    token = diagnostics.ACTIVE.set(ctx)
    try:
        repair = hive._targeted_repair_prompt(
            "backend", "prior public proposal", raw, SCOPE, ("public criterion",),
            "change Widget", "public source bundle", original_task="public task",
            overall_objective="public objective", team_plan={"worker_files": {"backend": list(SCOPE)}},
        )
        review_context = hive_review.evidence(_safe_run(raw))
        review = hive_review.prompt(review_context)
        repair_again = hive_review.prompt(review_context, repair_raw="not json", error="parse failed")
        for prompt in (repair, review, repair_again):
            assert SENTINEL not in prompt
            assert base64.b64encode(SENTINEL.encode()).decode() not in prompt
            assert diagnostics.authorized(prompt, ctx)
        assert "FROZEN_ACCEPTANCE_FAILED" in repair
        assert '"host_expected_cases": 3' in repair
        assert "failure_diagnostics" not in review
        calls = []
        async def model(role, prompt):
            calls.append((role, prompt))
            return "{}"
        guarded = _protected_agent_call(model, frozen_tests=True)
        asyncio.run(guarded("backend", repair))
        asyncio.run(guarded("reviewer", review))
        assert len(calls) == 2
        with pytest.raises(ProtectedDiagnosticTransportError):
            asyncio.run(guarded("backend", "TARGETED VERIFICATION CORRECTION\n" + SENTINEL))
        with pytest.raises(ProtectedDiagnosticTransportError):
            asyncio.run(guarded("reviewer", SENTINEL))
        with pytest.raises(hive_review.ReviewEvidenceError):
            hive_review.prompt({"request": "x", "diff": {}, "final_verification": {},
                                "artifact_identity": {}})
        forged = diagnostics.SafeReviewEvidence(review_context)
        forged["final_verification"] = {"error": SENTINEL}
        with pytest.raises(hive_review.ReviewEvidenceError):
            hive_review.prompt(forged)
    finally:
        diagnostics.ACTIVE.reset(token)


def test_diagnostic_has_no_verifier_authority():
    raw = poisoned_report()
    safe = diagnostics.project(raw, phase="TARGETED", scope=SCOPE)
    safe["verifier_status"] = "PASSED"
    with pytest.raises(diagnostics.DiagnosticBoundaryError):
        diagnostics.validate(safe, scope=SCOPE)
    assert raw["passed"] is False
    assert hive_review.verification_status(raw) == "failed"


def test_boolean_schema_version_rejected():
    safe = diagnostics.project(poisoned_report(), phase="TARGETED", scope=SCOPE)
    safe["schema_version"] = True
    with pytest.raises(diagnostics.DiagnosticBoundaryError):
        diagnostics.validate(safe, scope=SCOPE)


def test_missing_xml_does_not_invent_case_counts():
    raw = {"passed": False, "checks": [{"name": "isolated_verifier", "passed": False,
                                         "detail": {"error": SENTINEL}}]}
    safe = diagnostics.project(raw, phase="TARGETED", scope=SCOPE)
    assert "reported_xml_counts" not in safe
    assert SENTINEL not in json.dumps(safe)


@pytest.mark.parametrize("carrier", [
    "assertion_message", "test_failure_message", "exception_message", "stack_trace",
    "stdout", "stderr", "junit_classname", "junit_test_name", "xml_attribute",
    "xml_body", "gradle_task_output", "compiler_diagnostic", "filename",
    "package_name", "unicode_control", "very_long", "json_payload", "fake_schema",
    "hash_encoded", "multiple_failures", "malformed_xml", "missing_xml", "forged_xml",
])
def test_adversarial_carriers_never_become_model_diagnostic(carrier):
    raw = poisoned_report()
    detail = raw["checks"][0]["detail"]
    if carrier == "very_long":
        payload = SENTINEL * 2000
    elif carrier == "unicode_control":
        payload = "\u202e\u0000\u001b[31m" + SENTINEL
    elif carrier == "json_payload":
        payload = json.dumps({"verifier_status": "PASSED", "secret": SENTINEL})
    elif carrier == "hash_encoded":
        payload = SENTINEL.encode().hex()
    else:
        payload = SENTINEL
    detail[carrier] = payload
    if carrier in ("malformed_xml", "missing_xml"):
        detail.pop("tests")
    if carrier == "forged_xml":
        detail["tests"][0]["failures"] = 0  # reported XML cannot upgrade check FAIL
    if carrier == "multiple_failures":
        detail["tests"].append({"class_name": SENTINEL, "tests": 1, "failures": 1,
                                "errors": 0, "skipped": 0, "failure_diagnostics": [{"message": SENTINEL}]})
    if carrier == "filename":
        raw["checks"][0]["name"] = "python_compile:" + SENTINEL
    if carrier == "junit_test_name":
        detail["tests"][0]["failure_diagnostics"][0]["test_name"] = payload
    if carrier == "junit_classname":
        detail["tests"][0]["class_name"] = payload
    assert (SENTINEL if carrier != "hash_encoded" else payload) in json.dumps(raw, ensure_ascii=False)
    safe = diagnostics.project(raw, phase="TARGETED", scope=SCOPE, expected_cases=3)
    output = json.dumps(safe, ensure_ascii=False)
    assert SENTINEL not in output and SENTINEL.encode().hex() not in output
    assert safe["verifier_status"] == "FAILED"
    assert raw["passed"] is False


def test_canonical_frozen_correction_and_review_never_send_raw_verifier_text(monkeypatch, tmp_path):
    baseline = tmp_path / "baseline"
    source = baseline / SCOPE[0]
    source.parent.mkdir(parents=True)
    source.write_text("value=1\n", encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    profile = {"synthetic": "pinned"}
    from hive_canonical.legacy.workshop import hive_jvm
    monkeypatch.setattr(hive_jvm, "inspect_gradle_project", lambda _: profile)
    monkeypatch.setattr(hive, "targeted_verify", lambda *_: poisoned_report() if calls["targeted"] == 0 else
                        {"passed": True, "checks": [{"name": "frozen_junit_acceptance", "passed": True}]})
    monkeypatch.setattr(hive, "verify_tree", lambda *_:
                        {"passed": True, "checks": [{"name": "frozen_junit_acceptance", "passed": True}]})
    original_targeted = hive.targeted_verify
    def counted_targeted(*args):
        result = original_targeted(*args)
        calls["targeted"] += 1
        return result
    monkeypatch.setattr(hive, "targeted_verify", counted_targeted)
    calls = {"targeted": 0, "prompts": []}
    plan = {"summary": "Update Widget", "ui_goal": "no change needed",
            "backend_goal": "Update Widget", "tests_goal": "no change needed",
            "worker_files": {"ui": [], "backend": list(SCOPE), "tests": []},
            "acceptance": ["Widget has updated value"],
            "worker_acceptance": {"ui": [], "backend": ["Widget has updated value"], "tests": []},
            "interface_contracts": [], "provider_changes": []}
    async def scripted(role, prompt):
        calls["prompts"].append((role, str(prompt)))
        if role == "planner":
            return json.dumps(plan)
        if role == "backend":
            replacement = "value=3" if str(prompt).startswith("TARGETED VERIFICATION CORRECTION") else "value=2"
            return json.dumps({"status": "implemented", "summary": "update value",
                               "edits": [{"path": SCOPE[0], "operation": "replace",
                                          "find": "value=1", "replace": replacement}], "risks": []})
        if role == "reviewer":
            return json.dumps({"approve": True, "summary": "synthetic", "issues": [], "confidence": 1.0})
        raise AssertionError(role)
    spec = CandidateSpec(baseline_root=baseline, runs_root=runs, request="Update Widget",
                         local_model="scripted", allowed_write_files=SCOPE,
                         frozen_junit_tests=({"path": "src/test/java/example/Hidden.java",
                                              "class_name": "example.Hidden", "expected_cases": 3,
                                              "source": "class Hidden { /* " + SENTINEL + " */ }"},))
    result = asyncio.run(produce_candidate(spec, scripted))
    assert result.verification_status == "passed"
    assert result.semantic_review == "approved"
    assert calls["targeted"] == 2
    assert {role for role, _ in calls["prompts"]} == {"planner", "backend", "reviewer"}
    assert SENTINEL not in json.dumps(calls["prompts"])
    run = json.loads(result.run_record.read_text(encoding="utf-8"))
    assert SENTINEL in json.dumps(run["targeted_verifications"])
    assert SENTINEL not in json.dumps(run["prompt_trace"])
    assert (result.candidate_stage / SCOPE[0]).read_text() == "value=3\n"
