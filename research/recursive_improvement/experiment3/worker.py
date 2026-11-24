"""Subject adapter. No expected goals, grading criteria or secrets are mounted."""
import contextlib
import io
import json
import os
import sys


def main():
    if sys.argv[1] != "plan":
        # Reuse the exact frozen subject worker for all existing modes.
        sys.path.insert(0, "/harness")
        from subject_worker import main as existing_main
        return existing_main()
    payload = json.load(sys.stdin)
    os.chdir("/subject")
    sys.path.insert(0, "/subject")
    import planner
    rows = []
    for item in payload["inputs"]:
        planner.ask_hive = lambda *args, **kwargs: item["input"]
        task = {"id": item["id"], "target_file": "planner.py", "target_symbol": "_extract_json_object",
                "task_type": "bugfix", "change_intent": "modify_existing_logic", "expected_operation": "modify_logic",
                "note": "Repair JSON extraction in _extract_json_object in planner.py.",
                "metadata": {"target_file": "planner.py", "target_symbol": "_extract_json_object"}}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                plan = planner.PlannerAgent().plan_task(task)
            rows.append({"id": item["id"], "plan": plan})
        except Exception as exc:
            rows.append({"id": item["id"], "error": type(exc).__name__})
    print(json.dumps(rows, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
