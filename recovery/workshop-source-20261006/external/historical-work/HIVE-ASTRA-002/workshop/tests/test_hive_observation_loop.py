import asyncio
import json
from pathlib import Path

import pytest

from workshop import hive, hive_context


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "static").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "workshop").mkdir()
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "static" / "index.html").write_text(
        "<section id='view-settings'><h3>OpenAI</h3></section>\n"
        "<script>\n"
        "async function refreshStatus(){ return fetch('/api/status'); }\n"
        "</script>\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_existing.py").write_text(
        "def test_existing():\n    assert True\n", encoding="utf-8"
    )
    (root / "workshop" / "core.py").write_text(
        "def core_helper():\n    return 'health'\n", encoding="utf-8"
    )
    return root


def _plan(*, backend_goal="implement the health summary", backend_files=None,
          ui_goal="no change needed", ui_files=None, tests_goal="no change needed",
          tests_files=None, contracts=None):
    return {
        "summary": "Implement the health summary feature",
        "ui_goal": ui_goal,
        "backend_goal": backend_goal,
        "tests_goal": tests_goal,
        "worker_files": {
            "ui": ui_files if ui_files is not None else [],
            "backend": backend_files if backend_files is not None else ["app.py"],
            "tests": tests_files if tests_files is not None else [],
        },
        "acceptance": ["The health summary feature is safe and verified."],
        "worker_acceptance": {
            "ui": ["The UI displays the health summary."] if ui_files else [],
            "backend": [] if hive._no_change_goal(backend_goal) else ["The health summary endpoint is implemented."],
            "tests": ["Regression tests cover the health summary."] if tests_files else [],
        },
        "interface_contracts": contracts or [],
    }


def _review():
    return json.dumps({"approve": True, "summary": "reviewed", "issues": [], "confidence": 1.0})


def _run(root, runs, plan, worker, monkeypatch):
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    async def call(role, prompt):
        if role == "planner":
            return json.dumps(plan)
        if role == "backend":
            return worker(prompt)
        return _review()

    return asyncio.run(hive.run_build(root, runs, "Implement the health summary", "local", call))


def _implementation(find="return {'ok': True}", replace="return {'ok': True, 'summary': 'ready'}"):
    return json.dumps({
        "status": "implemented",
        "summary": "implement the health summary",
        "edits": [{
            "path": "app.py",
            "operation": "replace",
            "find": find,
            "replace": replace,
        }],
        "risks": [],
    })


def _observe(operation="list_symbols", arguments=None, reason="inspect the local implementation pattern"):
    if arguments is None:
        arguments = {"path": "app.py"}
    return json.dumps({
        "status": "observe",
        "operation": operation,
        "arguments": arguments,
        "reason": reason,
    })


def test_worker_can_observe_then_implement_and_trajectory_is_recorded(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = []
    backend_calls = 0

    def worker(prompt):
        nonlocal backend_calls
        calls.append(prompt)
        backend_calls += 1
        return _observe() if backend_calls == 1 else _implementation()

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    assert result["status"] == "ready", result.get("errors")
    assert result["changed_files"] == ["app.py"]
    assert len(result["observations"]) == 1
    assert result["observations"][0]["operation"] == "list_symbols"
    assert "health" in result["observations"][0]["result"]
    assert len(calls) == 2
    assert "READ-ONLY OBSERVATION RESULTS" in calls[1]
    assert (root / "app.py").read_text(encoding="utf-8").endswith("return {'ok': True}\n")


def test_multiple_observations_work_within_budget(tmp_path, monkeypatch):
    root = _source(tmp_path)
    count = 0

    def worker(prompt):
        nonlocal count
        count += 1
        if count == 1:
            return _observe("search_text", {"query": "FastAPI"})
        if count == 2:
            return _observe("find_similar_code", {"query": "health endpoint"})
        if count == 3:
            return _observe("read_symbol", {"path": "app.py", "symbol": "health"})
        return _implementation()

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    assert result["status"] == "ready", result.get("errors")
    assert [item["operation"] for item in result["observations"]] == [
        "search_text", "find_similar_code", "read_symbol"
    ]
    assert count == 4


def test_seventh_observation_fails_closed_at_six(tmp_path, monkeypatch):
    root = _source(tmp_path)
    count = 0

    def worker(prompt):
        nonlocal count
        count += 1
        return _observe("search_text", {"query": f"health {count}"})

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    failure = result["agents"]["backend"]["failure"]
    assert result["status"] == "rejected"
    assert count == 7
    assert len(result["observations"]) == hive.MAX_OBSERVATIONS_PER_WORKER
    assert failure["stage"] == "observation"
    assert failure["observation_iteration"] == 7
    assert failure["observation_budget"] == 6
    assert result["changed_files"] == []


def test_repeated_successful_observation_fails_closed_immediately(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = 0

    def worker(prompt):
        nonlocal calls
        calls += 1
        query = "FastAPI" if calls == 1 else "  fastapi  "
        return _observe("search_text", {"query": query}, reason=f"attempt {calls}")

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    failure = result["agents"]["backend"]["failure"]
    assert calls == 2
    assert len(result["observations"]) == 1
    assert failure["exception_type"] == "RepeatedObservationError"
    assert failure["repeated_observation"] is True
    assert failure["first_observation_iteration"] == 1
    assert failure["observation_iteration"] == 2


def test_materially_different_observations_remain_allowed(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = 0

    def worker(prompt):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return _observe("search_text", {"query": f"health-{calls}"})
        return _implementation()

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    assert result["status"] == "ready", result.get("errors")
    assert calls == 3
    assert [item["arguments"]["query"] for item in result["observations"]] == ["health-1", "health-2"]


def test_no_change_worker_is_skipped_without_a_model_call(tmp_path, monkeypatch):
    root = _source(tmp_path)
    plan = _plan(backend_goal="no change needed", backend_files=[])
    called = []

    def worker(prompt):
        called.append(prompt)
        return _implementation()

    result = _run(root, tmp_path / "runs", plan, worker, monkeypatch)

    assert result["agents"]["backend"]["status"] == "skipped"
    assert called == []


@pytest.mark.parametrize("path", ["../app.py", r"C:\outside.py", "/outside.py"])
def test_observation_traversal_and_absolute_paths_fail_closed(tmp_path, monkeypatch, path):
    root = _source(tmp_path)
    with pytest.raises(hive_context.ObservationError):
        hive_context.observe(root, "read_file_excerpt", {"path": path})

    result = _run(
        root, tmp_path / "runs", _plan(),
        lambda prompt: _observe("read_file_excerpt", {"path": path}), monkeypatch,
    )
    failure = result["agents"]["backend"]["failure"]
    assert failure["stage"] == "observation"
    assert result["changed_files"] == []


def test_observation_is_read_only_bounded_and_deterministic(tmp_path):
    root = _source(tmp_path)
    original = (root / "app.py").read_text(encoding="utf-8")
    (root / "large.py").write_text("MARKER\n" * 5_000, encoding="utf-8")
    arguments = {"path": "large.py", "query": "MARKER", "max_chars": 120}

    first = hive_context.observe(root, "read_file_excerpt", arguments)
    second = hive_context.observe(root, "read_file_excerpt", arguments)

    assert first == second
    assert len(first["result"]) <= 120
    assert (root / "app.py").read_text(encoding="utf-8") == original


def test_observation_cannot_execute_commands_or_repository_code(tmp_path):
    root = _source(tmp_path)
    marker = root / "pwned.txt"
    query = "__import__('pathlib').Path('pwned.txt').write_text('bad')"

    result = hive_context.observe(root, "search_text", {"query": query})

    assert result["ok"] is True
    assert not marker.exists()


def test_observing_outside_write_scope_does_not_grant_edit_permission(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = 0

    def worker(prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _observe("read_file_excerpt", {"path": "static/index.html"})
        return json.dumps({
            "status": "implemented",
            "summary": "implement the health summary",
            "edits": [{
                "path": "static/index.html", "operation": "replace",
                "find": "OpenAI", "replace": "Project Summary",
            }],
            "risks": [],
        })

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)
    failure = result["agents"]["backend"]["failure"]
    assert failure["stage"] == "edit_validation"
    assert "unplanned file" in failure["exception_message"]
    assert "OpenAI" in (root / "static" / "index.html").read_text(encoding="utf-8")


def test_backend_can_inspect_ui_and_tests_but_cannot_edit_them(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = 0

    def worker(prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _observe("search_text", {"query": "refreshStatus"})
        if calls == 2:
            return _observe("search_text", {"query": "def test_existing"})
        return json.dumps({
            "status": "implemented", "summary": "implement the health summary",
            "edits": [{"path": "tests/test_existing.py", "operation": "replace",
                        "find": "assert True", "replace": "assert False"}], "risks": [],
        })

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)
    assert result["agents"]["backend"]["failure"]["stage"] == "edit_validation"
    assert "unplanned file" in result["errors"][0]["exception_message"]
    assert (root / "tests" / "test_existing.py").read_text(encoding="utf-8").endswith("assert True\n")


def test_response_variants_are_mutually_exclusive_and_schema_constrained():
    prompt = hive._worker_prompt("backend", "implement health summary", ["app.py"], "source")
    schema = hive.response_schema_for_prompt("backend", prompt)
    assert len(schema["anyOf"]) == 3
    assert any("anyOf" in branch for branch in schema["anyOf"])
    statuses = {
        tuple(branch.get("properties", {}).get("status", {}).get("enum", []))
        for branch in schema["anyOf"]
        if "properties" in branch
    }
    assert ("implemented",) in statuses
    assert ("plan_insufficient",) in statuses
    valid = {"status": "observe", "operation": "search_text",
             "arguments": {"query": "health"}, "reason": "inspect route"}
    assert hive._validate_worker_observation(valid)["status"] == "observe"
    with pytest.raises(hive.WorkerProtocolError):
        hive._validate_worker_observation({**valid, "edits": []})


def test_structural_repair_still_works_after_observations(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = 0

    def worker(prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _observe()
        if calls == 2:
            return json.dumps({
                "status": "implemented", "summary": "implement the health summary",
                "edits": [{"path": "app.py", "operation": "insert_after_anchor",
                            "anchor": "MISSING_ANCHOR", "insert": "X = 1\n"}], "risks": [],
            })
        assert prompt.startswith("STRUCTURAL EDIT REPAIR\n")
        return json.dumps({
            "status": "implemented", "summary": "implement the health summary",
            "edits": [{"path": "app.py", "operation": "insert_after_symbol",
                        "symbol": "health", "insert": "\nsummary_ready = True\n"}], "risks": [],
        })

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)
    assert result["status"] == "ready", result.get("errors")
    assert len(result["observations"]) == 1
    assert len(result["edit_repairs"]) == 1
    assert result["edit_repairs"][0]["outcome"] == "repaired"


def test_observations_do_not_reset_structural_repair_budget(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = 0
    bad = json.dumps({
        "status": "implemented", "summary": "implement the health summary",
        "edits": [{"path": "app.py", "operation": "insert_after_anchor",
                    "anchor": "MISSING_ANCHOR", "insert": "X = 1\n"}], "risks": [],
    })

    def worker(prompt):
        nonlocal calls
        calls += 1
        if calls <= hive.MAX_OBSERVATIONS_PER_WORKER:
            return _observe("search_text", {"query": f"health {calls}"})
        return bad

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)
    failure = result["agents"]["backend"]["failure"]
    assert calls == hive.MAX_OBSERVATIONS_PER_WORKER + 2
    assert len(result["observations"]) == hive.MAX_OBSERVATIONS_PER_WORKER
    assert len(result["edit_repairs"]) == 1
    assert failure["exception_type"] == "WorkerProtocolError"
    assert "repeated" in failure["exception_message"]


def test_repeated_observation_during_structural_repair_is_stopped(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = 0
    bad = json.dumps({
        "status": "implemented", "summary": "implement the health summary",
        "edits": [{"path": "app.py", "operation": "insert_after_anchor",
                    "anchor": "MISSING_ANCHOR", "insert": "X = 1\n"}], "risks": [],
    })

    def worker(prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _observe("search_text", {"query": "health"})
        if calls == 2:
            return bad
        return _observe("search_text", {"query": " HEALTH "}, reason="repeat during repair")

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    failure = result["agents"]["backend"]["failure"]
    assert calls == 3
    assert len(result["observations"]) == 1
    assert len(result["edit_repairs"]) == 1
    assert result["edit_repairs"][0]["outcome"] == "failed"
    assert failure["exception_type"] == "RepeatedObservationError"
    assert failure["repeated_observation"] is True


def test_targeted_failure_returns_to_originating_worker_for_one_correction(tmp_path, monkeypatch):
    root = _source(tmp_path)
    worker_calls = 0
    targeted_calls = 0

    def targeted(stage, agent, changed_files):
        nonlocal targeted_calls
        targeted_calls += 1
        if targeted_calls == 1:
            return {"passed": False, "checks": [{
                "name": "targeted_pytest", "passed": False,
                "detail": "expected summary key in response",
            }]}
        return {"passed": True, "checks": [{
            "name": "python_compile:app.py", "passed": True,
            "detail": "python compile passed",
        }]}

    monkeypatch.setattr(hive, "targeted_verify", targeted)

    def worker(prompt):
        nonlocal worker_calls
        worker_calls += 1
        if worker_calls == 1:
            return _implementation()
        assert prompt.startswith("TARGETED VERIFICATION CORRECTION\n")
        assert "expected summary key" in prompt
        assert "RepeatedFailedProposal" in prompt
        return _implementation(replace="return {'ok': True, 'summary': 'corrected'}")

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    assert result["status"] == "ready", result.get("errors")
    assert worker_calls == 2
    assert targeted_calls == 2
    assert result["targeted_repairs"][0]["outcome"] == "corrected"
    assert result["agents"]["backend"]["targeted_repaired"] is True
    assert result["changed_files"] == ["app.py"]


def test_targeted_correction_is_bounded_and_restores_failed_candidate(tmp_path, monkeypatch):
    root = _source(tmp_path)
    worker_calls = 0

    monkeypatch.setattr(hive, "targeted_verify", lambda stage, agent, changed: {
        "passed": False,
        "checks": [{"name": "python_compile:app.py", "passed": False,
                     "detail": "synthetic targeted failure"}],
    })

    def worker(prompt):
        nonlocal worker_calls
        worker_calls += 1
        if worker_calls == 1:
            return _implementation()
        return _implementation(replace="return {'ok': True, 'summary': 'changed but still failing'}")

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    failure = result["agents"]["backend"]["failure"]
    assert result["status"] == "rejected"
    assert worker_calls == 2
    assert failure["stage"] == "verify"
    assert failure["targeted_correction_budget_exhausted"] is True
    assert result["targeted_repairs"][0]["outcome"] == "failed"
    assert result["changed_files"] == []
    assert (root / "app.py").read_text(encoding="utf-8").endswith("return {'ok': True}\n")


def test_identical_targeted_correction_is_rejected_without_another_check(tmp_path, monkeypatch):
    root = _source(tmp_path)
    worker_calls = 0
    targeted_calls = 0

    def targeted(stage, agent, changed):
        nonlocal targeted_calls
        targeted_calls += 1
        return {"passed": False, "checks": [{
            "name": "targeted_pytest", "passed": False, "detail": "NameError: api is not defined",
        }]}

    monkeypatch.setattr(hive, "targeted_verify", targeted)

    def worker(prompt):
        nonlocal worker_calls
        worker_calls += 1
        return _implementation()

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)

    failure = result["agents"]["backend"]["failure"]
    assert worker_calls == 2
    assert targeted_calls == 1
    assert failure["exception_type"] == "RepeatedFailedProposal"
    assert failure["targeted_correction_repeated"] is True
    assert result["targeted_repairs"][0]["outcome"] == "failed"
    assert result["changed_files"] == []


def test_targeted_pytest_catches_undefined_helper_hallucinations(tmp_path, monkeypatch):
    stage = tmp_path / "stage"
    (stage / "tests").mkdir(parents=True)
    (stage / "tests" / "test_bad.py").write_text(
        "def test_health_version():\n"
        "    response = api('/api/health')\n"
        "    assert response['version'] == app.version\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(hive.hive_verifier, "targeted_verify_isolated", lambda tree, files: {
        "passed": False,
        "checks": [{"name": "targeted_pytest", "passed": False,
                    "detail": "NameError: name 'api' is not defined"}],
    })
    verification = hive.targeted_verify(stage, "tests", ["tests/test_bad.py"])

    targeted = next(check for check in verification["checks"] if check["name"] == "targeted_pytest")
    assert targeted["passed"] is False
    assert "NameError" in targeted["detail"]
    assert "api" in targeted["detail"]


def test_targeted_correction_cannot_start_a_new_observation_loop(tmp_path, monkeypatch):
    root = _source(tmp_path)
    worker_calls = 0
    monkeypatch.setattr(hive, "targeted_verify", lambda stage, agent, changed: {
        "passed": False, "checks": [{"name": "synthetic", "passed": False, "detail": "try again"}],
    })

    def worker(prompt):
        nonlocal worker_calls
        worker_calls += 1
        if worker_calls == 1:
            return _implementation()
        return _observe("search_text", {"query": "health"})

    result = _run(root, tmp_path / "runs", _plan(), worker, monkeypatch)
    failure = result["agents"]["backend"]["failure"]
    assert failure["stage"] == "observation"
    assert "targeted correction responses must return" in failure["exception_message"]
    assert result["observations"] == []


def test_shared_interface_contract_lets_each_worker_do_its_part(tmp_path, monkeypatch):
    root = _source(tmp_path)
    plan = _plan(
        backend_goal="implement the Project Summary endpoint",
        backend_files=["app.py"],
        ui_goal="display Project Summary in Settings",
        ui_files=["static/index.html"],
        tests_goal="add Project Summary regression tests",
        tests_files=["tests/test_project_summary.py"],
        contracts=[{
            "name": "project_summary_endpoint",
            "owner": "backend",
            "consumer_roles": ["ui", "tests"],
            "contract": "GET /api/project/summary returns project summary JSON.",
        }],
    )
    observed_roles = []

    async def call(role, prompt):
        if role == "planner":
            return json.dumps(plan)
        if role in {"ui", "backend", "tests"}:
            assert "SHARED INTERFACE CONTRACTS" in prompt
            assert "project_summary_endpoint" in prompt
        if role == "reviewer":
            return _review()
        if role not in observed_roles:
            observed_roles.append(role)
            path = {"ui": "static/index.html", "backend": "app.py", "tests": "tests/test_existing.py"}[role]
            return _observe("read_file_excerpt", {"path": path})
        if role == "ui":
            return json.dumps({
                "status": "implemented", "summary": "display Project Summary in Settings",
                "edits": [{"path": "static/index.html", "operation": "replace",
                            "find": "<h3>OpenAI</h3>",
                            "replace": "<h3>OpenAI</h3><p>Project Summary</p>"}], "risks": [],
            })
        if role == "backend":
            return json.dumps({
                "status": "implemented", "summary": "implement the Project Summary endpoint",
                "edits": [{"path": "app.py", "operation": "insert_after_symbol", "symbol": "health",
                            "insert": "\n@app.get('/api/project/summary')\ndef project_summary():\n    return {'name': 'demo'}\n"}], "risks": [],
            })
        return json.dumps({
            "status": "implemented", "summary": "add Project Summary regression tests",
            "edits": [{"path": "tests/test_project_summary.py", "operation": "create",
                        "replace": "def test_project_summary_contract():\n    assert True\n"}], "risks": [],
        })

    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})
    result = asyncio.run(hive.run_build(root, tmp_path / "runs", "Add Project Summary", "local", call))

    assert result["status"] == "ready", result.get("errors")
    assert observed_roles == ["ui", "backend", "tests"]
    assert result["changed_files"] == ["app.py", "static/index.html", "tests/test_project_summary.py"]
    assert result["plan"]["interface_contracts"][0]["owner"] == "backend"
    assert result["replans"] == []
