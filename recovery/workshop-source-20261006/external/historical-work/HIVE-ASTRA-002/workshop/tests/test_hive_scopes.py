
from pathlib import Path
import pytest
from workshop import hive

def test_ui_agent_cannot_touch_backend():
    ok, why = hive.validate_edit("ui", {
        "path":"app.py",
        "operation":"replace",
        "find":"x",
        "replace":"y",
    })
    assert not ok
    assert "may not edit" in why

def test_backend_agent_can_touch_provider():
    ok, why = hive.validate_edit("backend", {
        "path":"workshop/providers.py",
        "operation":"replace",
        "find":"x",
        "replace":"y",
    })
    assert ok, why

def test_test_agent_can_create_test(tmp_path):
    stage = tmp_path / "stage"
    (stage / "tests").mkdir(parents=True)
    changed = hive.apply_agent_edits(stage, "tests", {
        "edits":[{
            "path":"tests/test_new.py",
            "operation":"create",
            "replace":"def test_ok():\n    assert True\n"
        }]
    })
    assert changed == ["tests/test_new.py"]
    assert (stage / "tests" / "test_new.py").exists()

def test_replace_must_be_unique(tmp_path):
    stage = tmp_path / "stage"
    (stage / "static").mkdir(parents=True)
    (stage / "static" / "index.html").write_text("x x", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly once"):
        hive.apply_agent_edits(stage, "ui", {
            "edits":[{
                "path":"static/index.html",
                "operation":"replace",
                "find":"x",
                "replace":"y"
            }]
        })

def test_plan_assigns_exact_files_to_each_role():
    plan, warnings = hive._normalize_plan({
        "summary": "Add an endpoint and tests",
        "ui_goal": "no change needed",
        "backend_goal": "add endpoint",
        "tests_goal": "add coverage",
        "worker_files": {
            "ui": [],
            "backend": ["app.py"],
            "tests": ["tests/test_context_preview.py"],
        },
        "acceptance": ["Endpoint and regression test pass"],
        "worker_acceptance": {"ui": [], "backend": ["Endpoint works"], "tests": ["Regression test covers endpoint"]},
        "interface_contracts": [{
            "name": "endpoint_test_contract",
            "owner": "backend",
            "consumer_roles": ["tests"],
            "contract": "The backend endpoint returns the schema covered by the regression test.",
        }],
    })
    assert plan["worker_files"]["ui"] == []
    assert plan["worker_files"]["backend"] == ["app.py"]
    assert plan["worker_files"]["tests"] == ["tests/test_context_preview.py"]
    assert warnings == []


def test_invalid_planner_assignment_is_rejected_not_normalized():
    with pytest.raises(hive.PlanValidationError, match="outside backend scope"):
        hive._normalize_plan({
            "summary": "bad contract", "ui_goal": "no change needed",
            "backend_goal": "add endpoint", "tests_goal": "no change needed",
            "worker_files": {"ui": [], "backend": ["app.py", "tests/test_app.py"], "tests": []},
            "acceptance": ["Endpoint works"],
            "worker_acceptance": {"ui": [], "backend": ["Endpoint works"], "tests": []},
        })

def test_unplanned_edit_is_rejected_atomically(tmp_path):
    stage = tmp_path / "stage"
    (stage / "tests").mkdir(parents=True)
    (stage / "app.py").write_text("x=1\n", encoding="utf-8")
    with pytest.raises(hive.EditValidationError, match="unplanned file"):
        hive.apply_agent_edits(stage, "backend", {
            "edits": [
                {"path": "app.py", "operation": "replace", "find": "x=1", "replace": "x=2"},
                {"path": "tests/test_app.py", "operation": "create", "replace": "def test_x():\n    pass\n"},
            ]
        }, planned_files=["app.py"])
    assert (stage / "app.py").read_text(encoding="utf-8") == "x=1\n"
    assert not (stage / "tests" / "test_app.py").exists()

def test_executor_prompt_contains_plan_not_original_request():
    prompt = hive._worker_prompt(
        "backend", "Add the endpoint", ["app.py"], "app source",
        ["app.py includes the endpoint", "response has the required keys"],
    )
    assert "A read-only planner already made the design" in prompt
    assert "YOUR FILES (exact write ownership):\n- app.py" in prompt
    assert "YOUR ACCEPTANCE CRITERIA (only your responsibility):" in prompt
    assert "response has the required keys" in prompt
    assert "OVERALL USER REQUEST" not in prompt
