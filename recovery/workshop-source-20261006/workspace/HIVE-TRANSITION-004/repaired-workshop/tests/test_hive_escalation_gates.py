"""Regression coverage for the preconditions on worker replanning."""
import asyncio
import json
from pathlib import Path

import pytest

from workshop import hive


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "static").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "workshop").mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "static" / "index.html").write_text("<section>Settings</section>\n", encoding="utf-8")
    (root / "tests" / "test_existing.py").write_text("def test_existing():\n    assert True\n", encoding="utf-8")
    (root / "workshop" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root


def _single_backend_plan(*, files=None, contracts=None):
    return {
        "summary": "Implement the bounded backend change",
        "ui_goal": "no change needed",
        "backend_goal": "Implement the backend change",
        "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": files or ["app.py"], "tests": []},
        "acceptance": ["The backend change is verified."],
        "worker_acceptance": {"ui": [], "backend": ["The backend change is verified."], "tests": []},
        "interface_contracts": contracts or [],
    }


def _multi_role_plan(*, contracts=None):
    return {
        "summary": "Deliver the cross-role feature",
        "ui_goal": "Display the feature in Settings",
        "backend_goal": "Implement the feature endpoint",
        "tests_goal": "Add regression coverage for the feature",
        "worker_files": {"ui": ["static/index.html"], "backend": ["app.py"], "tests": ["tests/test_feature.py"]},
        "acceptance": ["The feature works across the endpoint, UI and tests."],
        "worker_acceptance": {
            "ui": ["The Settings display is present."],
            "backend": ["The endpoint is present."],
            "tests": ["The feature has regression coverage."],
        },
        "interface_contracts": contracts or [],
    }


def _contract():
    return [{
        "name": "feature_endpoint",
        "owner": "backend",
        "consumer_roles": ["ui", "tests"],
        "contract": "GET /api/feature returns the feature JSON consumed by UI and tests.",
    }]


def _observe(query="VALUE"):
    return json.dumps({
        "status": "observe",
        "operation": "search_text",
        "arguments": {"query": query},
        "reason": "Inspect the assigned implementation pattern before deciding whether the contract is sufficient.",
    })


def _escalation(*, blocker_type="scope_change", requested_files=None):
    return json.dumps({
        "status": "plan_insufficient",
        "blocker_type": blocker_type,
        "reason": "The assigned source proves that an additional helper is required.",
        "evidence": "The assigned implementation references a helper boundary that is not in the current plan.",
        "requested_files": requested_files or ["workshop/extra.py"],
        "requested_plan_change": "Authorize the helper file for this worker.",
    })


def _implementation(path="app.py"):
    return json.dumps({
        "status": "implemented",
        "summary": "Implement the bounded backend change",
        "edits": [{"path": path, "operation": "replace", "find": "VALUE = 1", "replace": "VALUE = 2"}],
        "risks": [],
    })


def _review():
    return json.dumps({"approve": True, "summary": "verified", "issues": [], "confidence": 1.0})


def test_owned_file_is_rejected_before_any_scope_escalation():
    payload = json.loads(_escalation(requested_files=["app.py"]))
    history = [{"iteration": i} for i in range(1, hive.MAX_OBSERVATIONS_PER_WORKER + 1)]
    with pytest.raises(hive.WorkerProtocolError, match="already in the current exact plan"):
        hive._validate_worker_escalation(payload, ["app.py"], history)


def test_repository_information_escalation_requires_all_observations():
    payload = json.loads(_escalation(blocker_type="repository_information"))
    short_history = [{"iteration": i} for i in range(1, hive.MAX_OBSERVATIONS_PER_WORKER)]
    with pytest.raises(hive.WorkerProtocolError, match="completed observations first"):
        hive._validate_worker_escalation(payload, ["app.py"], short_history)
    full_history = short_history + [{"iteration": hive.MAX_OBSERVATIONS_PER_WORKER}]
    assert hive._validate_worker_escalation(payload, ["app.py"], full_history)["blocker_type"] == "repository_information"


def test_multi_role_plan_without_contract_is_corrected_before_workers(tmp_path, monkeypatch):
    root = _source(tmp_path)
    bad = _multi_role_plan()
    good = _multi_role_plan(contracts=_contract())
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})
    calls = []

    async def call(role, prompt):
        calls.append(role)
        if role == "planner":
            return json.dumps(bad if calls.count("planner") == 1 else good)
        if role == "backend":
            return _implementation()
        if role in hive.AGENT_SCOPES:
            return json.dumps({"status": "implemented", "summary": "no change", "edits": [], "risks": []})
        return _review()

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "cross-role feature", "local", call))

    assert run["status"] == "ready"
    assert [attempt["status"] for attempt in run["plan_attempts"]] == ["rejected", "accepted"]
    assert "multi-role plan requires" in run["plan_attempts"][0]["failure"]["exception_message"]
    assert calls[:2] == ["planner", "planner"]
    assert run["plan"]["interface_contracts"] == _contract()


def test_escalation_observations_are_sent_to_planner_and_replan_is_bounded(tmp_path, monkeypatch):
    root = _source(tmp_path)
    initial = _single_backend_plan()
    revised = _single_backend_plan(files=["app.py", "workshop/extra.py"])
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})
    backend_calls = 0
    planner_calls = 0

    # First six calls observe, the seventh escalates, and the rerun creates the
    # newly authorized file. Keep the branching explicit so a second replan
    # would be observable as an unexpected backend call.
    async def corrected_call(role, prompt):
        nonlocal backend_calls, planner_calls
        if role == "planner":
            planner_calls += 1
            if planner_calls == 1:
                return json.dumps(initial)
            assert "WORKER OBSERVATION TRAJECTORY" in prompt
            assert prompt.count("--- observation") == hive.MAX_OBSERVATIONS_PER_WORKER
            assert '"blocker_type": "scope_change"' in prompt
            return json.dumps({"decision": "revise", "reason": "The helper is required.", "plan": revised})
        if role == "backend":
            backend_calls += 1
            if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
                return _observe(f"VALUE {backend_calls}")
            if backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 1:
                return _escalation()
            return json.dumps({
                "status": "implemented",
                    "summary": "verified authorized helper implementation",
                "edits": [{"path": "workshop/extra.py", "operation": "create", "replace": "VALUE = 2\n"}],
                "risks": [],
            })
        return _review()

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "needs helper", "local", corrected_call))

    assert run["status"] == "ready"
    assert backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 2
    assert planner_calls == 2
    assert len(run["replans"]) == 1
    assert len(run["replans"][0]["observations"]) == hive.MAX_OBSERVATIONS_PER_WORKER
    assert run["changed_files"] == ["workshop/extra.py"]
    assert not (root / "workshop" / "extra.py").exists()


def test_missing_blocker_type_fails_closed_after_observations(tmp_path, monkeypatch):
    root = _source(tmp_path)
    plan = _single_backend_plan()
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})
    calls = 0

    async def call(role, prompt):
        nonlocal calls
        if role == "planner":
            return json.dumps(plan)
        if role == "backend":
            calls += 1
            if calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
                return _observe(f"VALUE {calls}")
            value = json.loads(_escalation())
            value.pop("blocker_type")
            return json.dumps(value)
        return _review()

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "needs helper", "local", call))

    assert run["status"] == "rejected"
    assert not run["replans"]
    assert run["agents"]["backend"]["failure"]["exception_type"] == "WorkerProtocolError"
    assert "requires blocker_type" in run["agents"]["backend"]["failure"]["exception_message"]


def _contract_plan_with(contract):
    plan = _multi_role_plan(contracts=[contract])
    return plan


def test_missing_contract_consumers_gets_deterministic_planner_correction(tmp_path, monkeypatch):
    root = _source(tmp_path)
    bad_contract = {
        "name": "get_project_summary",
        "owner": "backend",
        "contract": "GET /api/project-summary returns JSON with project details",
    }
    good = _contract_plan_with({
        "name": "get_project_summary",
        "owner": "backend",
        "consumer_roles": ["ui", "tests"],
        "contract": "GET /api/project-summary returns JSON with project details",
    })
    planner_prompts = []
    workers = []
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    async def call(role, prompt):
        if role == "planner":
            planner_prompts.append(prompt)
            return json.dumps(_contract_plan_with(bad_contract) if len(planner_prompts) == 1 else good)
        workers.append(role)
        if role == "reviewer":
            return _review()
        if role == "backend":
            return json.dumps({"status": "implemented", "summary": "The endpoint is present.",
                               "edits": [{"path": "app.py", "operation": "replace", "find": "VALUE = 1", "replace": "VALUE = 2"}],
                               "risks": []})
        return json.dumps({"status": "implemented", "summary": "no change needed", "edits": [], "risks": []})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "Project Summary", "local", call))

    assert run["status"] == "ready"
    assert len(planner_prompts) == 2
    correction = planner_prompts[1]
    assert "interface_contracts[0] consumer_roles must contain known roles" in correction
    assert 'ACTIVE ROLES IN THE REJECTED PLAN:\n["ui", "backend", "tests"]' in correction
    assert '"consumer_roles"' in correction and '"minItems": 1' in correction
    assert '"owner": "backend"' in correction
    assert '"consumer_roles": [\n    "ui",\n    "tests"\n  ]' in correction
    assert workers and all(role in hive.AGENT_SCOPES for role in workers if role != "reviewer")
    assert run["plan"]["interface_contracts"][0]["consumer_roles"] == ["ui", "tests"]


@pytest.mark.parametrize("consumers", [["mobile"], []])
def test_invalid_consumer_roles_remain_rejected(consumers):
    plan = _multi_role_plan(contracts=[{
        "name": "bad_contract",
        "owner": "backend",
        "consumer_roles": consumers,
        "contract": "GET /api/example returns JSON",
    }])
    with pytest.raises(hive.PlanValidationError, match="consumer_roles"):
        hive._normalize_plan(plan)


def test_malformed_interface_contract_correction_exhausts_single_budget(tmp_path):
    root = _source(tmp_path)
    bad = _contract_plan_with({
        "name": "get_project_summary",
        "owner": "backend",
        "contract": "GET /api/project-summary returns JSON",
    })
    calls = []

    async def call(role, prompt):
        calls.append(role)
        if role == "planner":
            return json.dumps(bad)
        raise AssertionError("workers must not execute before a valid corrected plan")

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "Project Summary", "local", call))

    assert run["status"] == "failed"
    assert calls == ["planner", "planner"]
    assert run["changed_files"] == []
    assert run["plan_attempts"][-1]["status"] == "rejected"


def test_planner_schema_requires_interface_contracts_field():
    schema = hive.agent_response_schema("planner")
    assert "interface_contracts" in schema["required"]
    contract = schema["properties"]["interface_contracts"]["items"]
    assert "consumer_roles" in contract["required"]


def test_multi_role_plan_correction_carries_stronger_schema_metadata():
    bad = _contract_plan_with({
        "name": "get_project_summary",
        "owner": "backend",
        "contract": "GET /api/project-summary returns JSON",
    })
    raw = json.dumps(bad)
    error = hive.PlanValidationError([
        "interface_contracts[0] consumer_roles must contain known roles",
        "multi-role plan requires an interface contract linking two active roles",
    ])
    prompt = hive._plan_correction_prompt("Project Summary", "repo map", raw, error)
    schema = hive.response_schema_for_prompt("planner", prompt)
    assert schema["properties"]["interface_contracts"]["minItems"] == 1
    contract = schema["properties"]["interface_contracts"]["items"]
    assert "consumer_roles" in contract["required"]
    assert contract["properties"]["consumer_roles"]["minItems"] == 1
