import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from workshop import chat_context, db

client = TestClient(app_module.app)


def test_chat_context_reports_repository_and_recent_run(tmp_path):
    root = tmp_path / "DemoProject"
    root.mkdir()
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    runs = tmp_path / "runs"
    run_dir = runs / "abcdef123456"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "id": "abcdef123456",
        "request": "Add Project Summary",
        "status": "rejected",
        "applied": False,
        "changed_files": [],
        "verification": {"passed": True},
        "review": {"approve": False, "summary": "No valid edits."},
        "errors": [{"role": "planner", "stage": "plan_validation", "exception_type": "PlanValidationError", "exception_message": "consumer_roles missing"}],
    }), encoding="utf-8")

    rendered = chat_context.render(root, runs)
    assert '"project_name": "DemoProject"' in rendered
    assert '"file_count": 1' in rendered
    assert '"id": "abcdef123456"' in rendered
    assert "consumer_roles missing" in rendered
    assert '"applied": false' in rendered
    assert "LATEST HIVE RUN: id=abcdef123456 status=rejected applied=False" in rendered


def test_chat_receives_read_only_workshop_state(monkeypatch):
    chat = db.create_chat()
    captured = {}

    async def fake_status():
        return True, ["qwen2.5-coder:14b"]

    async def fake_chat(model, messages, instructions, image_data_url=None, **kwargs):
        captured["instructions"] = instructions
        return {"text": "I can see the Workshop state.", "input_tokens": 10, "output_tokens": 8}

    monkeypatch.setattr(app_module.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app_module.providers, "ollama_chat", fake_chat)

    response = client.post("/api/chat", json={
        "chat_id": chat["id"],
        "text": "Why did the last build fail?",
        "mode": "local",
        "local_model": "qwen2.5-coder:14b",
    })
    assert response.status_code == 200
    instructions = captured["instructions"]
    assert "Bounded read-only Workshop state:" in instructions
    assert '"repository"' in instructions
    assert '"recent_hive_runs"' in instructions
    assert "no write authority" in instructions.lower()


def test_chat_context_excludes_runtime_and_hidden_files(tmp_path):
    root = tmp_path / "Demo"
    root.mkdir()
    (root / "visible.py").write_text("x=1", encoding="utf-8")
    (root / ".secret").write_text("nope", encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "private.db").write_text("nope", encoding="utf-8")

    rendered = chat_context.render(root, tmp_path / "runs")
    assert "visible.py" in rendered
    assert ".secret" not in rendered
    assert "private.db" not in rendered


def test_chat_context_surfaces_planner_failure_in_latest_digest(tmp_path):
    root = tmp_path / "DemoProject"
    root.mkdir()
    (root / "app.py").write_text("x=1\n", encoding="utf-8")
    runs = tmp_path / "hive_runs"
    run_dir = runs / "123456abcdef"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "id": "123456abcdef",
        "request": "Add Project Summary",
        "status": "failed",
        "applied": False,
        "plan_attempts": [{
            "attempt": 2,
            "status": "rejected",
            "failure": {
                "stage": "plan_validation",
                "exception_type": "PlanValidationError",
                "exception_message": "consumer_roles must contain known roles",
            },
        }],
        "errors": [{
            "role": "run",
            "stage": "agent_call",
            "exception_type": "PlanValidationError",
            "exception_message": "Planner correction budget exhausted",
        }],
    }), encoding="utf-8")

    rendered = chat_context.render(root, runs, "what caused the last hive failure")
    assert rendered.startswith("LATEST HIVE RUN: id=123456abcdef status=failed applied=False")
    assert "Planner rejection: PlanValidationError: consumer_roles must contain known roles" in rendered
    assert "Run error: run/agent_call/PlanValidationError: Planner correction budget exhausted" in rendered
