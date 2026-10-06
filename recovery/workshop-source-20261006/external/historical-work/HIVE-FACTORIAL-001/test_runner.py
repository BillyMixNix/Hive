from collections import Counter
import json

import runner


def test_balanced_fixed_order():
    order = runner.trial_order()
    assert len(order) == 32
    assert Counter((row["task_id"], row["replicate"], row["model"], row["controller"])
                   for row in order) == Counter({
        (task, repeat, model, controller): 1
        for task in runner.TASK_IDS for repeat in (1, 2)
        for model in runner.MODEL_NAMES for controller in runner.CONDITIONS
    })


def test_single_agent_plan_is_exact_and_valid():
    token = runner.hive._ACTIVE_AGENT_SCOPES.set(runner.hive.EXTERNAL_AGENT_SCOPES)
    mode = runner.hive._EXTERNAL_ROOT_MODE.set(True)
    try:
        for task in runner.task_specs():
            plan, warnings = runner.hive._normalize_plan(runner.single_plan(task))
            assert not warnings
            assert plan["worker_files"]["backend"] == task["files"]
            assert plan["worker_files"]["ui"] == []
            assert plan["worker_files"]["tests"] == []
            for path in task["files"]:
                assert runner.hive.validate_edit("backend", {
                    "path": path, "operation": "replace", "find": "observed", "replace": "new",
                }, task["files"])[0]
            assert not runner.hive.validate_edit("backend", {
                "path": "src/main/java/unrelated/Other.java", "operation": "create", "replace": "class Other {}",
            }, task["files"])[0]
    finally:
        runner.hive._EXTERNAL_ROOT_MODE.reset(mode)
        runner.hive._ACTIVE_AGENT_SCOPES.reset(token)


def test_hidden_acceptance_not_in_model_task_text():
    for task in runner.task_specs():
        assert task["test_filename"] not in task["request"]
        assert task["test_class"] not in task["request"]
        assert "@Test" not in task["request"]


def test_outer_authority_rejects_planner_scope_expansion_before_workers():
    task = runner.task_specs()[0]
    plan = runner.single_plan(task)
    assert runner.unauthorized_plan_files(json.dumps(plan), task["files"]) == []
    plan["worker_files"]["tests"] = ["src/test/java/Unapproved.java"]
    assert runner.unauthorized_plan_files(json.dumps(plan), task["files"]) == ["src/test/java/Unapproved.java"]
    assert runner.unauthorized_plan_files("not json", task["files"]) == []
