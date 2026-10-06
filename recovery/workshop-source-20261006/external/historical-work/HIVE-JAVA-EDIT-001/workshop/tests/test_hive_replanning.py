import asyncio
import json

import pytest

from workshop import hive


def make_source(tmp_path):
    root = tmp_path / "source"
    (root / "workshop").mkdir(parents=True)
    (root / "static").mkdir()
    (root / "tests").mkdir()
    (root / "app.py").write_text("APP_MARKER = 'owned app source'\n", encoding="utf-8")
    (root / "workshop" / "core.py").write_text(
        "def core_symbol():\n    return 1\n", encoding="utf-8"
    )
    (root / "static" / "index.html").write_text(
        "<script>const ready = true;</script>\n", encoding="utf-8"
    )
    (root / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return root


def plan_for(*, backend_goal="implement the backend change", backend_files=None):
    return {
        "summary": "bounded test plan",
        "ui_goal": "no changes needed",
        "backend_goal": backend_goal,
        "tests_goal": "no changes needed",
        "worker_files": {
            "ui": [],
            "backend": backend_files or ["app.py"],
            "tests": [],
        },
        "acceptance": ["the requested backend behavior is present"],
        "worker_acceptance": {"ui": [], "backend": ["the requested backend behavior is present"], "tests": []},
    }


def observe_payload(query="APP_MARKER"):
    return json.dumps({
        "status": "observe",
        "operation": "search_text",
        "arguments": {"query": query},
        "reason": "Inspect the assigned implementation before deciding whether a scope change is necessary.",
    })


def test_repository_map_is_compact_deterministic_and_excludes_noise(tmp_path):
    root = make_source(tmp_path)
    noise = {
        "data/secret.py",
        "hive_runs/run.json",
        "logs/server.log",
        "snapshots/old.py",
        ".git/config.py",
        ".venv/site.py",
        "__pycache__/cached.py",
        ".pytest_cache/result.txt",
        "dist/release.py",
        "release.zip",
    }
    for rel in noise:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("noise", encoding="utf-8")

    first = hive._repository_map(root)
    second = hive._repository_map(root)

    assert first == second
    assert "app.py" in first
    assert "functions: core_symbol" in first
    assert "workshop/" in first
    for rel in noise:
        assert rel.replace("/", "/") not in first
    assert "hive_runs/" not in first
    assert len(first) < 12000


def test_planner_prompt_receives_repository_map_and_can_assign_mapped_file(tmp_path):
    root = make_source(tmp_path)
    repository_map = hive._repository_map(root)
    prompt = hive._planner_prompt("Add a backend feature", repository_map)

    assert "REPOSITORY MAP" in prompt
    assert "app.py" in prompt
    assert "workshop/\n  core.py" in prompt
    assert "core_symbol" in prompt
    assert "Assign exact files" in prompt


def test_planner_assignment_can_use_a_file_from_the_repository_map(tmp_path):
    root = make_source(tmp_path)
    mapped_plan = plan_for(
        backend_goal="update the core helper",
        backend_files=["workshop/core.py"],
    )

    async def call(role, prompt):
        if role == "planner":
            assert "workshop/\n  core.py" in prompt
            return json.dumps(mapped_plan)
        if role == "backend":
            return json.dumps({"summary": "no-op for this protocol test", "edits": [], "risks": []})
        return json.dumps({"approve": False, "summary": "no staged change", "issues": [], "confidence": 0.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "update helper", "local", call))

    assert run["plan"]["worker_files"]["backend"] == ["workshop/core.py"]


def test_owned_files_are_always_in_worker_context(tmp_path):
    root = make_source(tmp_path)
    context = hive._worker_context(root, "backend", "a query with no matching marker", ["app.py"])
    prompt = hive._worker_prompt("backend", "use the owned backend file", ["app.py"], context)

    assert "OWNED FILE: app.py" in prompt
    assert "APP_MARKER = 'owned app source'" in prompt


def test_worker_escalation_is_not_an_edit_and_replan_authorizes_requested_file(tmp_path):
    root = make_source(tmp_path)
    initial = plan_for(backend_files=["app.py"])
    revised = plan_for(backend_files=["app.py", "workshop/extra.py"])
    calls = []
    backend_calls = 0
    planner_calls = 0

    escalation = {
        "status": "plan_insufficient",
        "blocker_type": "scope_change",
        "reason": "The implementation needs a helper module.",
        "evidence": "app.py imports a helper that is not part of the assigned files.",
        "requested_files": ["workshop/extra.py"],
        "requested_plan_change": "Authorize the helper module for the backend worker.",
    }
    backend_payload = {
        "summary": "created the authorized helper",
        "edits": [{
            "path": "workshop/extra.py",
            "operation": "create",
            "replace": "VALUE = 1\n",
        }],
        "risks": [],
    }

    async def call(role, prompt):
        nonlocal backend_calls, planner_calls
        calls.append((role, prompt))
        if role == "planner":
            planner_calls += 1
            if planner_calls == 1:
                assert "workshop/\n  core.py" in prompt
                return json.dumps(initial)
            assert "plan_insufficient" in prompt
            assert "workshop/extra.py" in prompt
            return json.dumps({
                "decision": "revise",
                "reason": "The helper is justified by the worker evidence.",
                "plan": revised,
            })
        if role == "backend":
            backend_calls += 1
            if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
                return observe_payload(f"APP_MARKER {backend_calls}")
            return json.dumps(escalation if backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 1 else backend_payload)
        return json.dumps({"approve": True, "summary": "verified", "issues": [], "confidence": 1.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "implement helper", "local", call))

    assert run["status"] == "ready"
    assert run["applied"] is False
    assert run["changed_files"] == ["workshop/extra.py"]
    assert backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 2
    assert planner_calls == 2
    assert run["replans"][0]["plan_before"]["worker_files"]["backend"] == ["app.py"]
    assert run["replans"][0]["plan_after"]["worker_files"]["backend"] == ["app.py", "workshop/extra.py"]
    assert run["agents"]["backend"]["prior_escalation"]["requested_files"] == ["workshop/extra.py"]
    assert not (root / "workshop" / "extra.py").exists()
    assert "planner" in [role for role, _ in calls]


def test_planner_can_reject_escalation_without_rerunning_worker(tmp_path):
    root = make_source(tmp_path)
    initial = plan_for()
    calls = []
    backend_calls = 0

    async def call(role, prompt):
        nonlocal backend_calls
        calls.append((role, prompt))
        if role == "planner" and len([r for r, _ in calls if r == "planner"]) == 1:
            return json.dumps(initial)
        if role == "planner":
            assert "WORKER ESCALATION" in prompt
            return json.dumps({"decision": "reject", "reason": "The current contract is sufficient."})
        if role == "backend":
            backend_calls += 1
            if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
                return observe_payload(f"APP_MARKER {backend_calls}")
            return json.dumps({
                "status": "plan_insufficient",
                "blocker_type": "scope_change",
                "reason": "I need another file.",
                "evidence": "The assigned file does not contain the required symbol.",
                "requested_files": ["workshop/extra.py"],
                "requested_plan_change": "Add the helper file.",
            })
        return json.dumps({"approve": False, "summary": "rejected", "issues": ["no edit"], "confidence": 0.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "do work", "local", call))

    assert run["status"] == "rejected"
    assert run["changed_files"] == []
    assert run["replans"][0]["decision"] == "reject"
    assert run["agents"]["backend"]["failure"]["exception_type"] == "PlanInsufficientError"
    assert len([r for r, _ in calls if r == "backend"]) == hive.MAX_OBSERVATIONS_PER_WORKER + 1
    assert not (root / "workshop" / "extra.py").exists()


def test_malformed_escalation_fails_closed_without_replanning(tmp_path):
    root = make_source(tmp_path)
    initial = plan_for()

    async def call(role, prompt):
        if role == "planner":
            return json.dumps(initial)
        if role == "backend":
            return json.dumps({
                "status": "plan_insufficient",
                "blocker_type": "scope_change",
                "reason": "",
                "evidence": "missing reason",
                "requested_files": ["workshop/extra.py"],
                "requested_plan_change": "add the helper",
            })
        return json.dumps({"approve": False, "summary": "rejected", "issues": [], "confidence": 0.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "do work", "local", call))

    failure = run["agents"]["backend"]["failure"]
    assert failure["stage"] == "edit_validation"
    assert failure["exception_type"] == "WorkerProtocolError"
    assert len(run["replans"]) == 0
    assert run["changed_files"] == []
    assert not (root / "workshop" / "extra.py").exists()


def test_escalation_for_already_planned_file_fails_closed_without_replanning(tmp_path):
    root = make_source(tmp_path)
    initial = plan_for()
    calls = []

    async def call(role, prompt):
        calls.append(role)
        if role == "planner":
            return json.dumps(initial)
        if role == "backend":
            return json.dumps({
                "status": "plan_insufficient",
                "blocker_type": "scope_change",
                "reason": "I need the assigned application file.",
                "evidence": "The requested symbol is in app.py, which is already assigned.",
                "requested_files": ["app.py"],
                "requested_plan_change": "Reassign app.py to the backend worker.",
            })
        return json.dumps({"approve": False, "summary": "rejected", "issues": [], "confidence": 0.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "do work", "local", call))

    failure = run["agents"]["backend"]["failure"]
    assert failure["stage"] == "edit_validation"
    assert "already in the current exact plan" in failure["exception_message"]
    assert calls.count("planner") == 1
    assert not run["replans"]
    assert run["changed_files"] == []


def test_replanning_cannot_loop_and_second_escalation_fails_closed(tmp_path):
    root = make_source(tmp_path)
    initial = plan_for()
    revised = plan_for(backend_goal="implement with the helper", backend_files=["app.py", "workshop/extra.py"])
    planner_calls = 0
    backend_calls = 0

    async def call(role, prompt):
        nonlocal planner_calls, backend_calls
        if role == "planner":
            planner_calls += 1
            if planner_calls == 1:
                return json.dumps(initial)
            return json.dumps({"decision": "revise", "reason": "approved once", "plan": revised})
        if role == "backend":
            backend_calls += 1
            if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
                return observe_payload(f"APP_MARKER {backend_calls}")
            if backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 2:
                return observe_payload("APP_MARKER 1")
            return json.dumps({
                "status": "plan_insufficient",
                "blocker_type": "scope_change",
                "reason": "still insufficient",
                "evidence": "the same missing dependency remains",
                "requested_files": ["workshop/extra.py"],
                "requested_plan_change": "expand again",
            })
        return json.dumps({"approve": False, "summary": "rejected", "issues": [], "confidence": 0.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "do work", "local", call))

    assert planner_calls == 2
    assert backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 2
    assert run["status"] == "rejected"
    assert len(run["replans"]) == 1
    assert run["agents"]["backend"]["failure"]["exception_type"] == "RepeatedObservationError"
    assert run["agents"]["backend"]["failure"]["repeated_observation"] is True
    assert not (root / "workshop" / "extra.py").exists()


def test_revised_scope_still_rejects_unrelated_file_atomically(tmp_path):
    root = make_source(tmp_path)
    initial = plan_for()
    revised = plan_for(backend_files=["app.py", "workshop/extra.py"])
    backend_calls = 0

    async def call(role, prompt):
        nonlocal backend_calls
        if role == "planner":
            if "WORKER ESCALATION" not in prompt:
                return json.dumps(initial)
            return json.dumps({"decision": "revise", "reason": "authorize helper", "plan": revised})
        if role == "backend":
            backend_calls += 1
            if backend_calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
                return observe_payload(f"APP_MARKER {backend_calls}")
            if backend_calls == hive.MAX_OBSERVATIONS_PER_WORKER + 1:
                return json.dumps({
                    "status": "plan_insufficient",
                    "blocker_type": "scope_change",
                    "reason": "helper required",
                    "evidence": "the helper is absent",
                    "requested_files": ["workshop/extra.py"],
                    "requested_plan_change": "authorize helper",
                })
            return json.dumps({
                "summary": "attempted helper and unrelated file",
                "edits": [
                    {"path": "workshop/extra.py", "operation": "create", "replace": "VALUE = 1\n"},
                    {"path": "workshop/unrelated.py", "operation": "create", "replace": "VALUE = 2\n"},
                ],
                "risks": [],
            })
        return json.dumps({"approve": False, "summary": "rejected", "issues": [], "confidence": 0.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "do work", "local", call))

    failure = run["agents"]["backend"]["failure"]
    assert failure["stage"] == "edit_validation"
    assert "unplanned file" in failure["exception_message"]
    assert run["changed_files"] == []
    assert not (root / "workshop" / "extra.py").exists()
    assert not (root / "workshop" / "unrelated.py").exists()


def test_escalation_with_edits_is_rejected_before_apply():
    payload = {
        "status": "plan_insufficient",
        "blocker_type": "scope_change",
        "reason": "need a file",
        "evidence": "the assigned file is insufficient",
        "requested_files": ["workshop/extra.py"],
        "requested_plan_change": "add the file",
        "edits": [{"path": "workshop/extra.py", "operation": "create", "replace": "bad"}],
    }

    with pytest.raises(hive.WorkerProtocolError, match="may not contain edits"):
        hive._validate_worker_escalation(payload)
