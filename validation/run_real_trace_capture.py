"""Drive one real Hive plan+code session and capture exact model-boundary traces.

This is intentionally not a synthetic Raw/Hive benchmark. It runs the normal
Hive interactive path against a clean runtime state, stops before pilot approval
or patch application, and summarizes whatever model calls actually occurred.
"""

from __future__ import annotations

import builtins
import json
import os
import traceback
from pathlib import Path


RUNTIME_FILES = (
    "hive_lessons.jsonl",
    "hive_metrics.jsonl",
    "hive_queue.jsonl",
    "hive_state_snapshot.json",
    "code_lessons.jsonl",
    "math_lessons.jsonl",
    "hive_memory.db",
    "hive_memory.json",
    "success_memory.jsonl",
)


def _clean_runtime() -> None:
    for name in RUNTIME_FILES:
        path = Path(name)
        if path.exists() and path.is_file():
            path.unlink()


def _load_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def main() -> int:
    task = os.environ.get("HIVE_REAL_TASK", "").strip()
    run_id = os.environ.get("HIVE_TRACE_RUN_ID", "real-trace").strip() or "real-trace"
    trace_dir = Path(os.environ.get("HIVE_TRACE_DIR", "real_traces"))
    summary_dir = Path(os.environ.get("HIVE_TRACE_SUMMARY_DIR", "real_trace_summaries"))
    if not task:
        raise SystemExit("HIVE_REAL_TASK is required")

    _clean_runtime()
    trace_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{run_id}.jsonl"
    trace_path.unlink(missing_ok=True)

    # A clean HiveMemoryAgent starts at id=1. We deliberately exercise the
    # public interactive path rather than calling planner/coder internals.
    commands = iter((task, "plan task 1", "code task 1"))
    original_input = builtins.input
    session_error: BaseException | None = None

    def scripted_input(prompt: str = "") -> str:
        try:
            command = next(commands)
        except StopIteration as exc:
            raise EOFError from exc
        print(f"{prompt}{command}")
        return command

    builtins.input = scripted_input
    try:
        import main as hive_main
        hive_main.main()
    except EOFError:
        pass
    except BaseException as exc:  # preserve the real failure in the artifact
        session_error = exc
        traceback.print_exc()
    finally:
        builtins.input = original_input

    records = _load_trace(trace_path)
    successful = [record for record in records if record.get("success")]
    by_role: dict[str, int] = {}
    prompt_tokens = 0
    output_tokens = 0
    elapsed = 0.0
    for record in records:
        role = str(record.get("role") or "default")
        by_role[role] = by_role.get(role, 0) + 1
        usage = record.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_eval_count") or usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("eval_count") or usage.get("output_tokens") or 0)
        elapsed += float(record.get("elapsed_seconds") or 0.0)

    summary = {
        "benchmark": "hive-real-coding-trace-v1",
        "run_id": run_id,
        "task": task,
        "commands": [task, "plan task 1", "code task 1"],
        "model": os.environ.get("HIVE_DEFAULT_MODEL", "qwen2.5-coder:7b"),
        "trace_path": str(trace_path),
        "model_calls": len(records),
        "successful_model_calls": len(successful),
        "calls_by_role": by_role,
        "reported_input_tokens": prompt_tokens,
        "reported_output_tokens": output_tokens,
        "model_elapsed_seconds": round(elapsed, 3),
        "session_error": None if session_error is None else {
            "type": type(session_error).__name__,
            "message": str(session_error),
        },
    }
    summary_path = summary_dir / f"{run_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

    if not records:
        return 2
    return 1 if session_error is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
