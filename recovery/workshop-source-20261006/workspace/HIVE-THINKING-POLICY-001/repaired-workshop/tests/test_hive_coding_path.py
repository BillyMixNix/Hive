import asyncio
import json

from workshop import hive


def _plan():
    return {
        "summary": "Add a Project Summary endpoint and Settings display",
        "ui_goal": "Display Project Summary in the existing Settings card",
        "backend_goal": "Implement the Project Summary endpoint",
        "tests_goal": "Add regression coverage for the Project Summary endpoint and display",
        "worker_files": {
            "ui": ["static/index.html"],
            "backend": ["app.py"],
            "tests": ["tests/test_project_summary.py"],
        },
        "acceptance": ["The endpoint, display, and regression coverage work together."],
        "worker_acceptance": {
            "ui": ["The Settings view displays a Project Summary card."],
            "backend": ["The endpoint returns a stable Project Summary schema."],
            "tests": ["Regression coverage checks the endpoint contract and display."],
        },
        "interface_contracts": [{
            "name": "project_summary_endpoint",
            "owner": "backend",
            "consumer_roles": ["ui", "tests"],
            "contract": "GET /api/project/summary returns project summary JSON.",
        }],
    }


def _source(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "static").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "static/index.html").write_text(
        "<section id='view-settings'>\n"
        "  <div class='card'><h3>OpenAI</h3><p>Configured.</p></div>\n"
        "</section>\n"
        "<script>\n"
        "async function refreshStatus(){ return fetch('/api/status'); }\n"
        "</script>\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})
    return root


def test_real_worker_path_has_owned_context_structural_repair_and_telemetry(tmp_path, monkeypatch):
    root = _source(tmp_path, monkeypatch)
    plan = _plan()
    calls = []
    ui_attempts = 0

    async def call(role, prompt):
        nonlocal ui_attempts
        calls.append((role, prompt))
        if role == "planner":
            return json.dumps(plan)
        if role == "ui":
            ui_attempts += 1
            if ui_attempts == 1:
                # The worker's first anchor is deliberately stale.  The
                # originating worker must repair it without gaining scope.
                return json.dumps({
                    "status": "implemented",
                    "summary": "add the settings summary",
                    "edits": [{
                        "path": "static/index.html",
                        "operation": "insert_after_anchor",
                        "anchor": "<!-- Project Summary placeholder -->",
                        "insert": "<div class='card'><h3>Project Summary</h3></div>",
                    }],
                    "risks": [],
                })
            assert prompt.startswith("STRUCTURAL EDIT REPAIR\n")
            assert "anchor_resolution" in prompt
            assert "STRUCTURAL TARGET INDEX" in prompt
            assert "OpenAI" in prompt and "view-settings" in prompt
            return json.dumps({
                "status": "implemented",
                "summary": "add the settings summary",
                "edits": [{
                    "path": "static/index.html",
                    "operation": "insert_after_element",
                    "heading": "OpenAI",
                    "insert": "<div class='card'><h3>Project Summary</h3><p id='project-summary'>Loaded.</p></div>",
                }],
                "risks": [],
            })
        if role == "backend":
            assert "===== OWNED FILE: app.py =====" in prompt
            assert "def health" in prompt
            return json.dumps({
                "status": "implemented",
                "summary": "add the endpoint",
                "edits": [{
                    "path": "app.py",
                    "operation": "insert_after_symbol",
                    "symbol": "health",
                    "insert": "@app.get('/api/project-summary')\ndef project_summary():\n    return {'name': 'demo', 'path': '.', 'files': 1}",
                }],
                "risks": [],
            })
        if role == "tests":
            assert "===== OWNED FILE: tests/test_project_summary.py =====" in prompt
            return json.dumps({
                "status": "implemented",
                "summary": "cover the feature",
                "edits": [{
                    "path": "tests/test_project_summary.py",
                    "operation": "create",
                    "replace": "def test_project_summary_contract():\n    assert True\n",
                }],
                "risks": [],
            })
        return json.dumps({"approve": True, "summary": "reviewed", "issues": [], "confidence": 1.0})

    result = asyncio.run(hive.run_build(root, root.parent / "runs", "Add Project Summary", "local", call))

    assert result["status"] == "ready", result.get("errors")
    assert result["changed_files"] == ["app.py", "static/index.html", "tests/test_project_summary.py"]
    assert result["applied"] is False
    assert calls[0][0] == "planner"
    assert [role for role, _ in calls] == ["planner", "ui", "ui", "backend", "tests", "reviewer"]
    assert result["edit_repairs"][0]["outcome"] == "repaired"
    assert result["edit_repairs"][0]["diagnostic"]["structural"]["code"] == "anchor_resolution"
    assert all("prompt_text" in trace and "response_text" in trace for trace in result["prompt_trace"])
    assert any("STRUCTURAL TARGET INDEX" in trace["prompt_text"] for trace in result["prompt_trace"] if trace["role"] == "ui")
    assert [event["stage"] for event in result["stage_events"]] == [
        "planning", "ui", "backend", "tests", "verification", "review", "completed",
    ]
    assert (root / "app.py").read_text(encoding="utf-8").endswith("return {'ok': True}\n")
    staged = root.parent / "runs" / result["id"] / "stage"
    assert "project_summary" in (staged / "app.py").read_text(encoding="utf-8")
    assert "Project Summary" in (staged / "static/index.html").read_text(encoding="utf-8")
