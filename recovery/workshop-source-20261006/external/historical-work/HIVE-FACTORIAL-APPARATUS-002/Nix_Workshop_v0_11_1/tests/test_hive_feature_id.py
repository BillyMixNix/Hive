import time

import app
from fastapi.testclient import TestClient


def _catalog(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "FEATURES.md").write_text(
        """# Feature backlog

## Planned
### NW-F010 — Example feature
- **Status:** Planned
- **Objective:** Add the requested report card.
- **Scope:**
  - Read the existing health endpoint.
  - Render the report card in Settings.
- **Dependencies:** Existing health endpoint.
- **Acceptance criteria:**
  1. Settings renders the returned data.
  2. A regression test covers the endpoint.
- **Constraints:**
  - Do not change the health endpoint.
  - Do not apply automatically.

## Queued
### NW-F011 — Undefined feature
- **Status:** Queued / needs definition
- **Objective:** Add a future feature.
- **Scope:** To be defined.
- **Dependencies:** None.
- **Acceptance criteria:** To be defined.
- **Constraints:** Do not invent acceptance criteria.
""",
        encoding="utf-8",
    )


def _configure_app(monkeypatch, tmp_path):
    _catalog(tmp_path)
    monkeypatch.setattr(app, "ROOT", tmp_path)
    monkeypatch.setattr(app, "HIVE_RUNS", tmp_path / "hive_runs")
    monkeypatch.setattr(app, "JOBS", app.runtime.JobManager(max_jobs=5))
    monkeypatch.setattr(app, "require_mode_for_code", lambda: None)
    monkeypatch.setattr(app.hive, "save_run", lambda *args: None)
    monkeypatch.setattr(app.db, "add_ledger", lambda *args: None)


def test_feature_preview_returns_spec_and_hash_without_starting_build(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    with TestClient(app.app) as client:
        response = client.get("/api/hive/features/NW-F010")

    assert response.status_code == 200
    payload = response.json()
    assert payload["feature"]["objective"] == "Add the requested report card."
    assert payload["feature"]["scope"] == [
        "Read the existing health endpoint.",
        "Render the report card in Settings.",
    ]
    assert payload["buildable"] is True
    assert len(payload["spec_sha256"]) == 64


def test_feature_preview_reports_unknown_and_nonbuildable_entries(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    with TestClient(app.app) as client:
        unknown = client.get("/api/hive/features/NW-F999")
        queued = client.get("/api/hive/features/NW-F011")

    assert unknown.status_code == 404
    assert queued.status_code == 200
    assert queued.json()["buildable"] is False
    assert "not Planned" in queued.json()["reason"]


def test_catalog_command_requires_preview_hash_before_queueing(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={"request": "Build NW-F010"})

    assert response.status_code == 409
    assert "preview and explicit confirmation" in response.json()["detail"]
    assert app.JOBS.health()["active_jobs"] == 0


def test_changed_feature_spec_hash_fails_before_queueing(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    with TestClient(app.app) as client:
        preview = client.get("/api/hive/features/NW-F010").json()
        catalog_path = tmp_path / "FEATURES.md"
        catalog_path.write_text(
            catalog_path.read_text(encoding="utf-8").replace(
                "Render the report card in Settings.",
                "Render the updated report card in Settings.",
            ),
            encoding="utf-8",
        )
        response = client.post("/api/hive/build", json={
            "request": "Build NW-F010",
            "feature_id": "NW-F010",
            "feature_spec_sha256": preview["spec_sha256"],
        })

    assert response.status_code == 409
    assert "changed after preview" in response.json()["detail"]
    assert app.JOBS.health()["active_jobs"] == 0


def test_malformed_feature_hash_fails_closed(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={
            "request": "Build NW-F010",
            "feature_id": "NW-F010",
            "feature_spec_sha256": "not-a-hash",
        })

    assert response.status_code == 400
    assert "64-character SHA-256" in response.json()["detail"]
    assert app.JOBS.health()["active_jobs"] == 0


def test_confirmed_feature_spec_is_frozen_into_hive_run_metadata(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    captured = {}
    saved = {}
    monkeypatch.setattr(app.hive, "save_run", lambda _root, run: saved.setdefault("run", run))

    async def fake_build(root, runs_root, request, local_model, call, metadata=None, on_stage=None):
        captured["request"] = request
        captured["metadata"] = metadata
        return {
            "id": "feature-run",
            "status": "rejected",
            "changed_files": [],
            "verification": {"passed": False},
            "review": {"approve": False},
            "metadata": metadata,
            "prompt_trace": [],
        }

    monkeypatch.setattr(app.hive, "run_build", fake_build)
    with TestClient(app.app) as client:
        preview = client.get("/api/hive/features/NW-F010").json()
        queued = client.post("/api/hive/build", json={
            "request": "Build NW-F010",
            "feature_id": "NW-F010",
            "feature_spec_sha256": preview["spec_sha256"],
            "allow_cloud": False,
            "max_tier": "local",
        })
        assert queued.status_code == 200
        job_id = queued.json()["job_id"]
        for _ in range(100):
            status = client.get(f"/api/jobs/{job_id}").json()
            if status["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)

    assert status["state"] == "completed", status
    assert captured["request"].startswith("Implement the selected Nix Workshop feature catalog entry")
    assert "Do not change the health endpoint." in captured["request"]
    selection = captured["metadata"]["feature_selection"]
    assert selection["id"] == "NW-F010"
    assert selection["user_command"] == "Build NW-F010"
    assert selection["spec_sha256"] == preview["spec_sha256"]
    assert selection["spec"]["acceptance_criteria"][1] == "A regression test covers the endpoint."
    assert saved["run"]["metadata"]["feature_selection"] == selection


def test_feature_command_must_match_selected_id(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={
            "request": "Build NW-F011",
            "feature_id": "NW-F010",
            "feature_spec_sha256": "0" * 64,
        })

    assert response.status_code == 400
    assert "must match" in response.json()["detail"]


def test_free_form_build_request_keeps_existing_request_path(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    captured = {}

    async def fake_build(root, runs_root, request, local_model, call, metadata=None, on_stage=None):
        captured["request"] = request
        captured["metadata"] = metadata
        return {
            "id": "freeform-run", "status": "rejected", "changed_files": [],
            "verification": {"passed": False}, "review": {"approve": False},
            "metadata": metadata, "prompt_trace": [],
        }

    monkeypatch.setattr(app.hive, "run_build", fake_build)
    with TestClient(app.app) as client:
        queued = client.post("/api/hive/build", json={"request": "Add a small status card."})
        assert queued.status_code == 200
        job_id = queued.json()["job_id"]
        for _ in range(100):
            status = client.get(f"/api/jobs/{job_id}").json()
            if status["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)

    assert status["state"] == "completed", status
    assert captured["request"] == "Add a small status card."
    assert captured["metadata"]["feature_selection"] is None


def test_frontend_previews_and_confirms_exact_feature_spec():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert "/api/hive/features/" in source
    assert "Feature ${feature.id} — ${feature.title}" in source
    assert "if(!confirm(details))return;" in source
    assert "featureSpecSha256=preview.spec_sha256" in source
