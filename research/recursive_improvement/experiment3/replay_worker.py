"""Evaluation-only scratch-CWD repair; original scoring and inputs stay fixed."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile


def scratch_view(subject):
    work = Path(tempfile.mkdtemp(prefix="hive-planner-replay-"))
    for path in Path(subject).iterdir():
        if path.name != "hive_lessons.jsonl":
            (work / path.name).symlink_to(path.resolve())
    return work


def main():
    mode = sys.argv[1]
    if mode not in ("plan", "plan_probe"):
        sys.path.insert(0, "/harness")
        from subject_worker import main as existing_main
        return existing_main()
    payload = json.load(sys.stdin)
    sys.path.insert(0, "/subject")
    if mode == "plan_probe":
        os.chdir("/subject")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                import planner
                planner.PlannerAgent()
            result = {"initialized": True}
        except OSError as exc:
            result = {"initialized": False, "error": type(exc).__name__, "errno": exc.errno,
                      "filename": exc.filename, "message": str(exc)[:400]}
        print(json.dumps(result), flush=True)
        return
    os.chdir(scratch_view("/subject"))
    with contextlib.redirect_stdout(io.StringIO()):
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
            rows.append({"id": item["id"], "error": type(exc).__name__, "message": str(exc)[:400]})
    print(json.dumps(rows, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
