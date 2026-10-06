"""A host task's exact write scope is an additional planner boundary."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

import factorial_runner_adapter
from workshop import external_root, hive


ALLOWED = "src/main/java/example/Widget.java"
OUTSIDE = "src/test/java/example/WidgetTest.java"


def plan(files=None):
    return {
        "summary": "Change Widget without expanding task ownership",
        "ui_goal": "no change needed",
        "backend_goal": "Change Widget.value to return 2",
        "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": files if files is not None else [ALLOWED], "tests": []},
        "interface_contracts": [], "provider_changes": [],
        "acceptance": ["Widget.value returns 2"],
        "worker_acceptance": {"ui": [], "backend": ["Widget.value returns 2"], "tests": []},
    }


def plan_with_unauthorized_test_role():
    result = plan()
    result["tests_goal"] = "Add Widget regression coverage"
    result["worker_files"]["tests"] = [OUTSIDE]
    result["worker_acceptance"]["tests"] = ["Widget regression coverage exists"]
    result["interface_contracts"] = [{
        "name": "widget_value", "owner": "backend", "consumer_roles": ["tests"],
        "contract": "Widget.value returns 2 for regression coverage",
    }]
    return result


def candidate(tmp_path):
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    runs = workshop / "hive_runs"
    runs.mkdir()
    baseline = tmp_path / "baseline"
    source = baseline / ALLOWED
    source.parent.mkdir(parents=True)
    source.write_text("package example; class Widget { int value() { return 1; } }\n", encoding="utf-8")
    run_id = "a" * 12
    descriptor = external_root.prepare_candidate(
        str(baseline), runs / "external_candidates" / run_id, workshop, runs,
    )
    return baseline, runs, descriptor, run_id


def run_fixture(tmp_path, monkeypatch, planner_responses, *, worker_edit_path=ALLOWED, controller="hive"):
    baseline, runs, descriptor, run_id = candidate(tmp_path)
    checks = []
    monkeypatch.setattr(hive, "targeted_verify", lambda tree, role, paths: {
        "passed": True, "checks": [{"name": "synthetic_targeted_boundary", "passed": True}],
    })

    def full_verifier(tree):
        checks.append(("full", str(tree)))
        return {"passed": True, "checks": [{"name": "synthetic_full_boundary", "passed": True}]}

    monkeypatch.setattr(hive, "verify_tree", full_verifier)
    roles = []
    prompts = []
    planner = iter(planner_responses)

    async def call(role, prompt):
        roles.append(role)
        prompts.append((role, prompt))
        if role == "planner":
            return json.dumps(next(planner))
        if role == "backend":
            assert ALLOWED in prompt
            assert OUTSIDE not in prompt
            return json.dumps({
                "status": "implemented", "summary": "Change Widget value within the bounded Java file",
                "edits": [{"path": worker_edit_path, "operation": "replace",
                           "find": "return 1;", "replace": "return 2;"}], "risks": [],
            })
        if role == "reviewer":
            return json.dumps({"approve": True, "summary": "reviewed", "issues": [], "confidence": 1.0})
        raise AssertionError(f"unexpected role: {role}")

    result = asyncio.run(factorial_runner_adapter.run_condition(
        controller=controller,
        task={"request": "Change Widget.value only", "files": [ALLOWED]},
        candidate=Path(descriptor["candidate_root"]), runs=runs, model="local",
        provider_call=call, metadata={"external_root": descriptor}, run_id=run_id,
    ))
    return result, roles, prompts, checks, baseline


def test_rejected_outer_scope_reaches_one_planner_correction_before_worker(tmp_path, monkeypatch):
    result, roles, prompts, checks, baseline = run_fixture(
        tmp_path, monkeypatch, [plan([ALLOWED, OUTSIDE]), plan()],
    )
    assert roles == ["planner", "planner", "backend", "reviewer"]
    assert result["candidate_disposition"] == "verified_review_approved", result.get("errors")
    assert not result["human_review_eligible"]  # external candidate-only policy
    assert result["applied"] is False
    assert result["metadata"]["host_write_scope"] == [ALLOWED]
    assert len(checks) == 1
    assert "return 1;" in (baseline / ALLOWED).read_text(encoding="utf-8")
    assert "return 2;" in (tmp_path / "workshop/hive_runs" / result["id"] / "stage" / ALLOWED).read_text(encoding="utf-8")
    failure = result["plan_attempts"][0]["failure"]
    assert failure["exception_type"] == "HostWriteScopeError"
    assert "worker_files.backend" in failure["exception_message"]
    assert OUTSIDE in failure["exception_message"]
    assert ALLOWED in prompts[0][1] and "HOST-AUTHORIZED TASK WRITE FILES" in prompts[0][1]
    assert OUTSIDE in prompts[1][1] and "ONE correction attempt" in prompts[1][1]


def test_single_agent_contract_reaches_same_worker_and_verifier_boundary(tmp_path, monkeypatch):
    result, roles, _, checks, _ = run_fixture(tmp_path, monkeypatch, [], controller="single")
    assert roles == ["backend"]
    assert result["candidate_disposition"] == "verified_review_approved"
    assert not result["human_review_eligible"]  # external candidate-only policy
    assert result["metadata"]["host_write_scope"] == [ALLOWED]
    assert len(checks) == 1
    assert result["changed_files"] == [ALLOWED]


def test_scope_correction_can_deactivate_unauthorized_role_without_fake_contract(tmp_path, monkeypatch):
    result, roles, prompts, checks, _ = run_fixture(
        tmp_path, monkeypatch, [plan_with_unauthorized_test_role(), plan()],
    )
    assert roles == ["planner", "planner", "backend", "reviewer"]
    assert result["candidate_disposition"] == "verified_review_approved", result.get("errors")
    assert not result["human_review_eligible"]  # external candidate-only policy
    assert len(checks) == 1
    correction_prompt = prompts[1][1]
    assert all("minItems" not in branch["properties"]["interface_contracts"]
               for branch in correction_prompt.response_schema["anyOf"])
    assert OUTSIDE in correction_prompt
    assert result["plan"]["worker_files"]["tests"] == []
    assert result["plan"]["interface_contracts"] == []


def test_invalid_correction_fails_closed_before_workers(tmp_path, monkeypatch):
    result, roles, _, checks, _ = run_fixture(
        tmp_path, monkeypatch, [plan([ALLOWED, OUTSIDE]), plan([ALLOWED, OUTSIDE])],
    )
    assert roles == ["planner", "planner"]
    assert result["status"] == "failed"
    assert len(result["plan_attempts"]) == 2
    assert not checks
    assert result["changed_files"] == []


def test_worker_cannot_expand_a_valid_plan_to_an_unowned_file(tmp_path, monkeypatch):
    result, roles, _, checks, baseline = run_fixture(
        tmp_path, monkeypatch, [plan()], worker_edit_path=OUTSIDE,
    )
    assert roles == ["planner", "backend", "reviewer"]
    assert result["status"] != "ready"
    assert result["changed_files"] == []
    assert "return 1;" in (baseline / ALLOWED).read_text(encoding="utf-8")


def test_replan_scope_expansion_is_rejected_with_exact_path():
    token = hive._HOST_WRITE_SCOPE.set((ALLOWED,))
    try:
        revised = copy.deepcopy(plan([ALLOWED, OUTSIDE]))
        with pytest.raises(hive.PlanValidationError, match="WidgetTest.java"):
            hive._validate_host_write_scope(revised)
    finally:
        hive._HOST_WRITE_SCOPE.reset(token)


@pytest.mark.parametrize("unsafe", ["../escape.java", "/tmp/escape.java", "C:/escape.java", "src/./Widget.java", "src\\Widget.java"])
def test_unsafe_host_authority_rejected_before_agent(tmp_path, unsafe):
    source = tmp_path / "source"
    source.mkdir()
    calls = []

    async def call(role, prompt):
        calls.append(role)
        raise AssertionError("model must not be called")

    with pytest.raises(ValueError):
        asyncio.run(hive.run_build(source, tmp_path / "runs", "request", "local", call,
                                   allowed_write_files=[unsafe]))
    assert calls == []


def test_absent_host_authority_preserves_existing_behavior(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    prompt = hive._planner_prompt("request", external_mode=True)
    assert "HOST-AUTHORIZED TASK WRITE FILES" not in prompt
    assert hive._HOST_WRITE_SCOPE.get() is None
