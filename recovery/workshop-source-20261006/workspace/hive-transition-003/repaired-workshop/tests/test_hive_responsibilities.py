"""Exercise the actual call boundary, including repair and replanning."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from workshop import hive


def project_plan():
    return {
        "summary": "Add Project Summary to Settings",
        "ui_goal": "Display Project Summary in Settings",
        "backend_goal": "Implement the backend Project Summary endpoint",
        "tests_goal": "Add regression tests for Project Summary",
        "worker_files": {"ui": ["static/index.html"], "backend": ["app.py"],
                         "tests": ["tests/test_summary.py"]},
        "acceptance": ["GLOBAL: the endpoint, display and regression tests deliver the feature"],
        "worker_acceptance": {
            "ui": ["UI_ONLY: Settings renders the summary and refresh control"],
            "backend": ["BACKEND_ONLY: endpoint returns the expected schema",
                        "BACKEND_ONLY: existing backend behavior remains compatible"],
            "tests": ["TESTS_ONLY: regression tests cover the endpoint and display"],
        },
        "interface_contracts": [{
            "name": "project_summary_endpoint",
            "owner": "backend",
            "consumer_roles": ["ui", "tests"],
            "contract": "GET /api/project/summary returns project summary JSON.",
        }],
    }


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "static").mkdir(parents=True)
    (root / "workshop").mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "static/index.html").write_text("<div>Settings</div>\n", encoding="utf-8")
    (root / "workshop/summary.py").write_text("COUNT = 0\n", encoding="utf-8")
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})
    return root


def run(source, call):
    return asyncio.run(hive.run_build(source, source.parent / "runs", "Project Summary request", "local", call))


def observation(query="VALUE"):
    return json.dumps({"status": "observe", "operation": "search_text",
                       "arguments": {"query": query},
                       "reason": "Inspect the assigned implementation before deciding whether a scope change is necessary"})


def own_criteria(prompt):
    return prompt.split("YOUR ACCEPTANCE CRITERIA (only your responsibility):", 1)[1].split("READ-ONLY INTEGRATION CONTEXT:", 1)[0]


def check_assignment(role, prompt, plan):
    assert isinstance(prompt, hive.AgentPrompt)
    assert "OVERALL OBJECTIVE (context only):\n" + plan["summary"] in prompt
    assert "YOUR RESPONSIBILITY:\n" + plan[f"{role}_goal"] in prompt
    files = prompt.split("YOUR FILES (exact write ownership):", 1)[1].split("TEAM PLAN", 1)[0]
    teammates = prompt.split("TEAM PLAN (read-only teammate assignments):", 1)[1].split("YOUR ACCEPTANCE CRITERIA", 1)[0]
    criteria = own_criteria(prompt)
    for other in hive.AGENT_SCOPES:
        if role == other:
            for path in plan["worker_files"][role]:
                assert path in files
            for item in plan["worker_acceptance"][role]:
                assert item in criteria
        else:
            assert plan[f"{other}_goal"] in teammates
            for path in plan["worker_files"][other]:
                assert path in teammates and path not in files
            for item in plan["worker_acceptance"][other]:
                assert item not in criteria
    assert "GLOBAL:" not in prompt
    instructions = prompt.split("CURRENT SCOPED SOURCE:", 1)[0]
    assert "NOT responsible for completing the entire feature" in instructions
    assert "Do NOT request another role's files merely because" in instructions
    assert "concrete blocker" not in instructions
    implementation = next(branch for branch in prompt.response_schema["anyOf"]
                          if branch.get("properties", {}).get("status", {}).get("enum") == ["implemented"])
    escalation = next(branch for branch in prompt.response_schema["anyOf"]
                      if branch.get("properties", {}).get("status", {}).get("enum") == ["plan_insufficient"])
    assert implementation["properties"]["status"]["enum"] == ["implemented"]
    assert escalation["properties"]["status"]["enum"] == ["plan_insufficient"]
    for edit in implementation["properties"]["edits"]["items"]["anyOf"]:
        assert edit["properties"]["path"]["enum"] == plan["worker_files"][role]


@pytest.mark.parametrize("repair_backend", [False, True])
def test_live_call_contract_gives_each_role_its_own_work_and_team(source, monkeypatch, repair_backend):
    plan = project_plan()
    original_context = hive._worker_context
    queries, worker_prompts = {}, []

    def context(root, role, query, files, previous):
        queries[role] = query
        return original_context(root, role, query, files, previous)

    monkeypatch.setattr(hive, "_worker_context", context)
    proposals = {
        "ui": {"path": "static/index.html", "operation": "replace", "find": "Settings", "replace": "Settings Summary"},
        "backend": {"path": "app.py", "operation": "replace", "find": "VALUE = 1", "replace": "VALUE = 2"},
        "tests": {"path": "tests/test_summary.py", "operation": "create", "replace": "def test_summary():\n    assert True\n"},
    }

    async def call(role, prompt):
        if role == "planner":
            assert "worker_acceptance" in prompt and "Do not copy global acceptance" in prompt
            return json.dumps(plan)
        if role == "reviewer":
            return json.dumps({"approve": True})
        check_assignment(role, prompt, plan)
        worker_prompts.append((role, prompt))
        if role == "backend" and repair_backend:
            if len([item for item in worker_prompts if item[0] == "backend"]) == 1:
                return '{"status":"implemented","summary":"bad JSON'
            assert prompt.startswith("Repair the previous BACKEND response")
            assert "JSON formatting error" in prompt
        summaries = {
            "ui": "project summary UI portion",
            "backend": "project summary backend portion",
            "tests": "project summary tests portion",
        }
        return json.dumps({"status": "implemented", "summary": summaries[role], "edits": [proposals[role]], "risks": []})

    result = run(source, call)
    assert result["status"] == "ready", result.get("errors")
    assert result["changed_files"] == ["app.py", "static/index.html", "tests/test_summary.py"]
    assert not result["applied"] and result["replans"] == []
    assert len(worker_prompts) == 3 + int(repair_backend)
    assert result["plan"]["acceptance"] == plan["acceptance"]
    for role, query in queries.items():
        assert "GLOBAL:" not in query
        assert all(item in query for item in plan["worker_acceptance"][role])
        assert all(item not in query for other in hive.AGENT_SCOPES if other != role
                   for item in plan["worker_acceptance"][other])
    assert (source / "app.py").read_text() == "VALUE = 1\n"


@pytest.mark.parametrize("defect", ["missing", "missing_role", "empty_active", "non_list", "blank", "inactive_criteria"])
def test_plan_requires_explicit_criteria_per_responsibility(defect):
    plan = project_plan()
    if defect == "missing": plan.pop("worker_acceptance")
    elif defect == "missing_role": plan["worker_acceptance"].pop("backend")
    elif defect == "empty_active": plan["worker_acceptance"]["backend"] = []
    elif defect == "non_list": plan["worker_acceptance"]["backend"] = "endpoint works"
    elif defect == "blank": plan["worker_acceptance"]["backend"] = [" "]
    elif defect == "inactive_criteria":
        plan["ui_goal"] = "no change needed"
        plan["worker_files"]["ui"] = []
    with pytest.raises(hive.PlanValidationError, match="acceptance"):
        hive._normalize_plan(plan)


def test_missing_worker_criteria_gets_planner_correction_before_work(source):
    plan = project_plan()
    bad = deepcopy(plan)
    bad.pop("worker_acceptance")
    calls = []

    async def call(role, prompt):
        calls.append(role)
        if role == "planner":
            if len(calls) == 1: return json.dumps(bad)
            assert calls == ["planner", "planner"]
            assert "worker_acceptance" in prompt
            return json.dumps(plan)
        if role == "reviewer": return '{"approve": false}'
        check_assignment(role, prompt, plan)
        return '{"status":"implemented","summary":"only a contract check","edits":[],"risks":[]}'

    result = run(source, call)
    assert [item["status"] for item in result["plan_attempts"]] == ["rejected", "accepted"]
    assert not result.get("errors")
    assert calls == ["planner", "planner", "ui", "backend", "tests", "reviewer"]


def test_actual_ui_call_receives_settings_markup_and_helpers(source):
    page = (Path(__file__).resolve().parents[1] / "static/index.html").read_text(encoding="utf-8")
    (source / "static/index.html").write_text(page, encoding="utf-8")
    plan = project_plan()
    observed = []

    async def call(role, prompt):
        if role == "planner": return json.dumps(plan)
        if role == "reviewer": return '{"approve": false}'
        check_assignment(role, prompt, plan)
        observed.append(role)
        if role == "ui":
            owned = prompt.split("===== OWNED FILE: static/index.html =====", 1)[1].split("===== INTEGRATION SUPPORTING CONTEXT", 1)[0]
            assert '<section id="view-settings"' in owned
            assert '<h3>OpenAI</h3>' in owned
            assert "async function api(" in owned
            refresh = "async function refreshStatus(){" + page.split("async function refreshStatus(){", 1)[1].split("\n}", 1)[0] + "\n}"
            assert refresh in owned
            assert len(owned) < 5100
        return '{"status":"implemented","summary":"only a prompt check","edits":[],"risks":[]}'

    result = run(source, call)
    assert not result.get("errors"), result.get("errors")
    assert observed == ["ui", "backend", "tests"]
    assert result["changed_files"] == []


def test_replan_cannot_change_a_teammates_criteria():
    plan = project_plan()
    revised = deepcopy(plan)
    revised["worker_acceptance"]["tests"] = ["No tests required"]
    with pytest.raises(hive.WorkerProtocolError, match="another role's acceptance"):
        hive._merge_replan_plan(plan, {"decision": "revise", "plan": revised}, "backend")


def test_approved_replan_rerun_and_repair_receive_updated_own_criteria(source):
    plan = project_plan()
    revised = deepcopy(plan)
    revised["worker_files"]["backend"].append("workshop/summary.py")
    revised["worker_acceptance"]["backend"].append("BACKEND_REPLAN_ONLY: helper returns count")
    backend_calls = 0

    async def call(role, prompt):
        nonlocal backend_calls
        if role == "planner":
            if prompt.startswith("PLANNER REPLAN REQUEST"):
                assert "worker_acceptance" in prompt and "this worker's assigned responsibility" in prompt
                return json.dumps({"decision": "revise", "reason": "Endpoint requires its existing helper", "plan": revised})
            return json.dumps(plan)
        if role == "reviewer": return '{"approve": true}'
        if role != "backend":
            check_assignment(role, prompt, revised if backend_calls else plan)
            return '{"status":"implemented","summary":"no change in fixture","edits":[],"risks":[]}'
        backend_calls += 1
        check_assignment(role, prompt, plan if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER + 1 else revised)
        if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
            return observation(f"VALUE {backend_calls}")
        if backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 1:
            assert not hive.validate_edit("backend", {"path": "workshop/summary.py", "find": "COUNT = 0"}, ["app.py"])[0]
            return json.dumps({"status": "plan_insufficient", "blocker_type": "scope_change", "reason": "The endpoint delegates its calculation to the unassigned helper",
                              "evidence": "workshop/summary.py defines COUNT = 0",
                              "requested_files": ["workshop/summary.py"], "requested_plan_change": "Authorize the backend helper"})
        if backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 2: return '{"status":"implemented"'
        assert prompt.startswith("Repair the previous BACKEND response")
        return json.dumps({"status": "implemented", "summary": "helper updated", "risks": [],
                           "edits": [{"path": "workshop/summary.py", "operation": "replace", "find": "COUNT = 0", "replace": "COUNT = 1"}]})

    result = run(source, call)
    assert result["status"] == "ready", result.get("errors")
    assert backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 3 and result["replans"][0]["decision"] == "revise"
    assert result["changed_files"] == ["workshop/summary.py"] and not result["applied"]
    assert (source / "workshop/summary.py").read_text() == "COUNT = 0\n"


def test_adding_global_criteria_alone_cannot_trigger_worker_rerun(source):
    plan = project_plan()
    revised = deepcopy(plan)
    revised["acceptance"].append("GLOBAL: still complete the whole feature")
    backend_calls = 0

    async def call(role, prompt):
        nonlocal backend_calls
        if role == "planner":
            return json.dumps({"decision": "revise", "reason": "more global work", "plan": revised}) if prompt.startswith("PLANNER REPLAN REQUEST") else json.dumps(plan)
        if role == "backend":
            backend_calls += 1
            if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
                return observation(f"VALUE {backend_calls}")
            if backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 1:
                return json.dumps({"status": "plan_insufficient", "blocker_type": "scope_change", "reason": "Helper missing from contract", "evidence": "workshop/summary.py defines COUNT",
                                   "requested_files": ["workshop/summary.py"], "requested_plan_change": "Assign helper"})
        if role == "reviewer": return '{"approve": false}'
        return '{"status":"implemented","summary":"no change in fixture","edits":[],"risks":[]}'

    result = run(source, call)
    assert backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 1
    assert "did not change the worker contract" in result["replans"][0]["reason"]
    assert result["status"] == "rejected" and result["changed_files"] == []
