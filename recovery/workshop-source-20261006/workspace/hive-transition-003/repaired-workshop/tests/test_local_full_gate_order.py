"""External full verification must follow successful cheaper prerequisites."""

import asyncio
import json

from workshop import external_root, hive


def _candidate(tmp_path):
    workshop = tmp_path / "workshop"
    runs = workshop / "hive_runs"
    runs.mkdir(parents=True)
    baseline = tmp_path / "baseline"
    source = baseline / "src" / "Widget.txt"
    source.parent.mkdir(parents=True)
    source.write_text("value=1\n", encoding="utf-8")
    run_id = "a" * 12
    candidate = runs / "external_candidates" / run_id
    descriptor = external_root.prepare_candidate(str(baseline), candidate, workshop, runs)
    return runs, run_id, candidate, descriptor


def _plan():
    return json.dumps({
        "summary": "Change Widget.value", "ui_goal": "no change needed",
        "backend_goal": "Change Widget.value to 2", "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": ["src/Widget.txt"], "tests": []},
        "acceptance": ["Widget.value is 2"],
        "worker_acceptance": {"ui": [], "backend": ["Widget.value is 2"], "tests": []},
        "interface_contracts": [], "provider_changes": [],
    })


def _build(tmp_path, monkeypatch, *, worker_output):
    runs, run_id, candidate, descriptor = _candidate(tmp_path)
    full_calls = []

    def fake_full(stage):
        full_calls.append(stage)
        return {"passed": True, "checks": [{"name": "sealed_full_gate", "passed": True}]}

    monkeypatch.setattr(hive, "verify_tree", fake_full)

    async def call(role, prompt):
        if role == "planner":
            return _plan()
        if role == "backend":
            return worker_output
        if role == "reviewer":
            return json.dumps({"approve": False, "summary": "fixture", "issues": [],
                               "confidence": 0})
        raise AssertionError(role)

    run = asyncio.run(hive.run_build(
        candidate, runs, "Change Widget.value to 2", "local", call,
        metadata={"external_root": descriptor}, run_id=run_id, external_root_mode=True,
    ))
    return run, full_calls


def test_failed_external_worker_skips_full_gate(tmp_path, monkeypatch):
    run, full_calls = _build(tmp_path, monkeypatch, worker_output="not JSON")
    assert run["errors"]
    assert run["verification"]["passed"] is False
    assert run["verification"]["full_gate_skipped"] is True
    assert run["verification"]["checks"][0]["name"] == "external_full_gate_prerequisite"
    assert full_calls == []
    assert run["applied"] is False


def test_valid_external_edits_keep_full_gate_reachable(tmp_path, monkeypatch):
    worker = json.dumps({
        "status": "implemented", "summary": "Updated Widget.value", "risks": [],
        "edits": [{"path": "src/Widget.txt", "operation": "replace",
                   "find": "value=1", "replace": "value=2"}],
    })
    run, full_calls = _build(tmp_path, monkeypatch, worker_output=worker)
    assert not run.get("errors")
    assert run["changed_files"] == ["src/Widget.txt"]
    assert len(full_calls) == 1
    assert run["verification"]["passed"] is True
    assert run["applied"] is False
