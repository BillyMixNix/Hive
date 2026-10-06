import asyncio
import json
import os
import time
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
from workshop import external_root, hive, runtime


def _plan():
    return {
        "summary": "Update Widget behavior",
        "ui_goal": "no change needed",
        "backend_goal": "Change the value returned by Widget.value",
        "tests_goal": "no change needed",
        "worker_files": {
            "ui": [],
            "backend": ["src/Widget.txt"],
            "tests": [],
        },
        "acceptance": ["Widget.value returns the requested value."],
        "worker_acceptance": {
            "ui": [],
            "backend": ["Widget value is 2."],
            "tests": [],
        },
        "interface_contracts": [],
        "provider_changes": [],
    }


def _setup_api(monkeypatch, tmp_path):
    workshop_root = tmp_path / "workshop"
    workshop_root.mkdir()
    runs_root = workshop_root / "hive_runs"
    runs_root.mkdir()
    (workshop_root / "static").mkdir()
    monkeypatch.setattr(app, "ROOT", workshop_root)
    monkeypatch.setattr(app, "HIVE_RUNS", runs_root)
    monkeypatch.setattr(app, "SELF_SNAPSHOTS", workshop_root / "self_snapshots")
    monkeypatch.setattr(app, "JOBS", runtime.JobManager(max_jobs=20))
    monkeypatch.setattr(app, "require_mode_for_code", lambda: None)
    monkeypatch.setattr(app.db, "add_ledger", lambda *args, **kwargs: None)
    return workshop_root, runs_root


def _external_repo(tmp_path):
    root = tmp_path / "external-repository"
    (root / "src").mkdir(parents=True)
    (root / "src" / "Widget.txt").write_text("value=1\n", encoding="utf-8")
    return root


def _gradle_repo(tmp_path):
    root = tmp_path / "external-gradle-repository"
    wrapper = root / "gradle" / "wrapper"
    source = root / "src" / "main" / "java" / "example"
    source.mkdir(parents=True)
    wrapper.mkdir(parents=True)
    (source / "Widget.java").write_text("package example; class Widget { int value() { return 1; } }\n", encoding="utf-8")
    (root / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (root / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (root / "gradlew.bat").write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    (wrapper / "gradle-wrapper.jar").write_bytes(b"fixture wrapper jar")
    (wrapper / "gradle-wrapper.properties").write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.2.1-bin.zip\n"
        "distributionSha256Sum=" + "a" * 64 + "\n", encoding="utf-8"
    )
    return root


def _frozen_test_spec():
    return {
        "path": "src/test/java/example/WidgetAcceptanceTest.java",
        "class_name": "example.WidgetAcceptanceTest",
        "expected_cases": 1,
        "source": "package example; class WidgetAcceptanceTest { @org.junit.jupiter.api.Test void accepted() {} }\n",
    }


def _wait_for_job(client, job_id):
    status = None
    for _ in range(200):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["state"] in {"completed", "failed", "cancelled"}:
            return status
        time.sleep(0.01)
    raise AssertionError(f"job did not finish: {status}")


def _persistent_fake(monkeypatch, baseline, malicious=False):
    prompts = []
    plan = _plan()
    baseline = Path(baseline)

    class FakePersistentBackend:
        def __init__(self, model):
            assert model == "gpt-6-astra"
            self.metrics = []

        async def __call__(self, role, prompt):
            prompts.append((role, str(prompt)))
            if role == "planner":
                return json.dumps(plan)
            if role == "backend":
                edit_path = str(baseline / "src" / "Widget.txt") if malicious else "src/Widget.txt"
                return json.dumps({
                    "status": "implemented",
                    "summary": "update Widget.value",
                    "edits": [{
                        "path": edit_path,
                        "operation": "replace",
                        "find": "value=1",
                        "replace": "value=2",
                    }],
                    "risks": [],
                })
            if role == "reviewer":
                return json.dumps({"approve": True, "summary": "reviewed", "issues": [], "confidence": 1})
            raise AssertionError(f"unexpected agent role {role}")

    monkeypatch.setattr(app.persistent_agent, "PersistentAgentBackend", FakePersistentBackend)
    return prompts


def test_normal_build_without_external_root_keeps_workshop_root(monkeypatch, tmp_path):
    workshop_root, runs_root = _setup_api(monkeypatch, tmp_path)
    captured = {}

    async def fake_build(source_root, runs, request, local_model, call, metadata=None, on_stage=None):
        captured.update(root=Path(source_root), runs=Path(runs), metadata=metadata)
        return {"id": "a" * 12, "status": "rejected", "changed_files": [],
                "verification": {"passed": False}, "review": {"approve": False},
                "metadata": metadata, "prompt_trace": []}

    monkeypatch.setattr(app.hive, "run_build", fake_build)
    monkeypatch.setattr(app.hive, "save_run", lambda *args: None)
    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={"request": "Use this path in the description: C:/external/repo"})
        assert response.status_code == 200
        status = _wait_for_job(client, response.json()["job_id"])
    assert status["state"] == "completed"
    assert captured["root"] == workshop_root
    assert captured["runs"] == runs_root
    assert "external_root" not in captured["metadata"]


def test_external_root_requires_opt_in_and_valid_nontraversing_directory(monkeypatch, tmp_path):
    workshop_root, runs_root = _setup_api(monkeypatch, tmp_path)
    repo = _external_repo(tmp_path)
    with TestClient(app.app) as client:
        not_opted_in = client.post("/api/hive/build", json={
            "request": "update Widget", "external_source_root": str(repo),
        })
        no_path = client.post("/api/hive/build", json={
            "request": "update Widget", "allow_external_root": True,
        })
        missing = client.post("/api/hive/build", json={
            "request": "update Widget", "allow_external_root": True,
            "external_source_root": str(tmp_path / "missing"),
        })
        traversal = client.post("/api/hive/build", json={
            "request": "update Widget", "allow_external_root": True,
            "external_source_root": str(repo / ".." / "external-repository"),
        })
    assert not_opted_in.status_code == no_path.status_code == missing.status_code == traversal.status_code == 400
    assert "explicit" in not_opted_in.json()["detail"]
    assert "requires external_source_root" in no_path.json()["detail"]
    assert "cannot be resolved" in missing.json()["detail"]
    assert ".." in traversal.json()["detail"]
    assert list(runs_root.iterdir()) == []


def test_external_candidate_isolated_end_to_end_with_persistent_backend(monkeypatch, tmp_path):
    workshop_root, runs_root = _setup_api(monkeypatch, tmp_path)
    baseline = _external_repo(tmp_path)
    prompts = _persistent_fake(monkeypatch, baseline)
    context_roots = []
    verification_roots = []
    targeted_roots = []

    original_context = hive._worker_context

    def capture_context(root, *args, **kwargs):
        context_roots.append(Path(root).resolve())
        return original_context(root, *args, **kwargs)

    monkeypatch.setattr(hive, "_worker_context", capture_context)
    monkeypatch.setattr(hive, "targeted_verify", lambda tree, role, files: (
        targeted_roots.append((Path(tree).resolve(), list(files))) or {"passed": True, "checks": []}
    ))
    monkeypatch.setattr(hive, "verify_tree", lambda tree: (
        verification_roots.append(Path(tree).resolve()) or {"passed": True, "checks": []}
    ))

    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={
            "request": "Change src/Widget.txt to value=2.",
            "allow_cloud": True,
            "agent_backend": "persistent",
            "persistent_agent_model": "gpt-6-astra",
            "external_source_root": str(baseline),
            "allow_external_root": True,
        })
        assert response.status_code == 200, response.text
        job = _wait_for_job(client, response.json()["job_id"])

    run = job["result"]
    external = run["metadata"]["external_root"]
    candidate = Path(external["candidate_root"]).resolve()
    stage = (runs_root / run["id"] / "stage").resolve()
    evidence = (runs_root / run["id"] / "run.json").resolve()
    assert job["state"] == "completed"
    assert run["status"] == "ready" and run["applied"] is False
    assert external["external_root_mode"] == "candidate_only"
    assert external["promotion_allowed"] is False
    assert Path(external["baseline_root"]).resolve() == baseline.resolve()
    assert len(external["baseline_sha256"]) == 64
    assert external["candidate_root"] == str(candidate)
    assert candidate.is_relative_to(runs_root.resolve())
    assert candidate != baseline.resolve()
    assert evidence.is_file() and evidence.is_relative_to(runs_root.resolve())
    assert not evidence.is_relative_to(baseline.resolve())
    assert "run.json" not in {p.name for p in baseline.rglob("*") if p.is_file()}
    assert (baseline / "src/Widget.txt").read_text(encoding="utf-8").find("value=1") >= 0
    assert (candidate / "src/Widget.txt").read_text(encoding="utf-8").find("value=1") >= 0
    assert (stage / "src/Widget.txt").read_text(encoding="utf-8").find("value=2") >= 0
    assert all(path == candidate for path in context_roots)
    assert len(targeted_roots) == 1 and targeted_roots[0][0] == stage
    assert verification_roots == [stage]
    planner_prompt = next(prompt for role, prompt in prompts if role == "planner")
    backend_prompt = next(prompt for role, prompt in prompts if role == "backend")
    assert "src/Widget.txt" in planner_prompt
    assert "value=1" in backend_prompt
    assert str(baseline.resolve()) not in planner_prompt + backend_prompt
    assert run["external_baseline_integrity"] == {
        "baseline_unchanged": True,
        "candidate_unchanged": True,
    }


def test_persistent_backend_cannot_target_original_baseline(monkeypatch, tmp_path):
    _, runs_root = _setup_api(monkeypatch, tmp_path)
    baseline = _external_repo(tmp_path)
    _persistent_fake(monkeypatch, baseline, malicious=True)
    monkeypatch.setattr(hive, "targeted_verify", lambda *args: {"passed": True, "checks": []})
    monkeypatch.setattr(hive, "verify_tree", lambda *args: {"passed": True, "checks": []})

    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={
            "request": "Change src/Widget.txt to value=2.",
            "allow_cloud": True,
            "agent_backend": "persistent",
            "external_source_root": str(baseline),
            "allow_external_root": True,
        })
        job = _wait_for_job(client, response.json()["job_id"])

    run = job["result"]
    assert run["status"] == "rejected"
    assert run["changed_files"] == []
    assert run["agents"]["backend"]["failure"]["stage"] == "edit_validation"
    assert (baseline / "src/Widget.txt").read_text(encoding="utf-8").find("value=1") >= 0
    assert (Path(run["metadata"]["external_root"]["candidate_root"]) / "src/Widget.txt").read_text(encoding="utf-8").find("value=1") >= 0
    assert (runs_root / run["id"] / "run.json").is_file()


def test_external_run_promotion_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "example.txt").write_text("baseline", encoding="utf-8")
    runs = tmp_path / "runs"
    run_id = "a" * 12
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    metadata = {"external_root": {"external_root_mode": "candidate_only", "promotion_allowed": False}}
    (run_dir / "run.json").write_text(json.dumps({
        "id": run_id, "status": "ready", "applied": False,
        "verification": {"passed": True}, "review": {"approve": True},
        "changed_files": ["example.txt"], "metadata": metadata,
        "base_manifest": {"example.txt": hive._path_state(source / "example.txt")},
        "staged_manifest": {"example.txt": {"kind": "file", "sha256": "0" * 64, "size": 7}},
    }), encoding="utf-8")
    (run_dir / "stage").mkdir()
    (run_dir / "stage" / "example.txt").write_text("promoted", encoding="utf-8")

    with pytest.raises(ValueError, match="candidate/evaluation only"):
        hive.apply_run(source, runs, tmp_path / "snapshots", run_id)
    assert (source / "example.txt").read_text(encoding="utf-8") == "baseline"


def test_external_snapshot_rejects_symlink_or_junction_escape(tmp_path):
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    runs = workshop / "hive_runs"
    runs.mkdir()
    repo = _external_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    link = repo / "linked-outside"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable on this platform: {exc}")

    with pytest.raises(external_root.ExternalRootError, match="symlinks/junctions"):
        external_root.prepare_candidate(
            str(repo), runs / "external_candidates" / ("b" * 12), workshop, runs
        )
    assert not (runs / "external_candidates" / ("b" * 12)).exists()


def test_candidate_snapshot_excludes_runtime_state_and_detects_baseline_change(tmp_path):
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    runs = workshop / "hive_runs"
    runs.mkdir()
    repo = _external_repo(tmp_path)
    (repo / "data").mkdir()
    (repo / "data" / "runtime.json").write_text("runtime", encoding="utf-8")
    (repo / "src" / "main" / "resources" / "data" / "example" / "structure").mkdir(parents=True)
    (repo / "src" / "main" / "resources" / "data" / "example" / "structure" / "empty.nbt").write_bytes(b"resource")
    (repo / "source" / "src" / "gametest" / "resources" / "data" / "namespace").mkdir(parents=True)
    (repo / "source" / "src" / "gametest" / "resources" / "data" / "namespace" / "empty.nbt").write_bytes(b"nested project resource")
    (repo / "fixtures" / "data").mkdir(parents=True)
    (repo / "fixtures" / "data" / "generated.json").write_text("generated", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "output.txt").write_text("generated", encoding="utf-8")
    descriptor = external_root.prepare_candidate(
        str(repo), runs / "external_candidates" / ("c" * 12), workshop, runs
    )
    candidate = Path(descriptor["candidate_root"])
    assert (candidate / "src/Widget.txt").is_file()
    assert (candidate / "src/main/resources/data/example/structure/empty.nbt").read_bytes() == b"resource"
    assert (candidate / "source/src/gametest/resources/data/namespace/empty.nbt").read_bytes() == b"nested project resource"
    assert not (candidate / "data").exists()
    assert not (candidate / "fixtures/data").exists()
    assert not (candidate / ".git").exists()
    assert not (candidate / "build").exists()
    assert external_root.baseline_unchanged(descriptor)

    (repo / "src/Widget.txt").write_text("changed outside the candidate\n", encoding="utf-8")
    assert not external_root.baseline_unchanged(descriptor)


def test_candidate_changed_after_snapshot_is_rejected_before_agent_execution(tmp_path):
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    runs = workshop / "hive_runs"
    runs.mkdir()
    repo = _external_repo(tmp_path)
    run_id = "d" * 12
    descriptor = external_root.prepare_candidate(
        str(repo), runs / "external_candidates" / run_id, workshop, runs
    )
    candidate = Path(descriptor["candidate_root"])
    (candidate / "src/Widget.txt").write_text("tampered before execution\n", encoding="utf-8")
    calls = []

    async def unexpected_agent_call(role, prompt):
        calls.append(role)
        raise AssertionError("agent must not execute for a changed candidate")

    with pytest.raises(ValueError, match="changed before Hive execution"):
        asyncio.run(hive.run_build(
            candidate, runs, "Change Widget", "local", unexpected_agent_call,
            metadata={"external_root": descriptor}, run_id=run_id,
            external_root_mode=True,
        ))

    assert calls == []
    assert not (runs / run_id).exists()


def test_external_jvm_project_without_wrapper_fails_closed(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "settings.gradle").write_text("rootProject.name = 'fixture'\n", encoding="utf-8")

    result = hive.hive_verifier.run_isolated(candidate, "full", external_root=True)

    assert result["passed"] is False
    assert "checked-in gradlew" in result["checks"][0]["detail"]
