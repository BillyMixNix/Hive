"""Continue HIVE-FACTORIAL-001 after its disk-space stop without rerunning trial 1.

This is a post-stop continuation, not an uninterrupted preregistered run. The
frozen runner, lock, tasks, tests, and original evidence remain untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "HIVE-FACTORIAL-001"
ORIGINAL = SOURCE / "evidence"
CONTINUATION = HERE / "evidence"
sys.path.insert(0, str(SOURCE))
import runner  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preflight() -> tuple[dict, list[dict]]:
    if CONTINUATION.exists():
        raise runner.StudyStop("continuation evidence already exists")
    lock = json.loads(runner.LOCK_PATH.read_text(encoding="utf-8"))
    runner.check_lock(lock)
    event_path = ORIGINAL / "events.jsonl"
    result_path = ORIGINAL / "raw_results.json"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    expected_events = [
        ("started", None),
        ("trial_started", 1),
        ("trial_finished", 1),
        ("stopped", 2),
    ]
    if [(event["kind"], event.get("ordinal")) for event in events] != expected_events:
        raise runner.StudyStop("original event trajectory changed")
    if events[-1].get("reason") != "less than eight GiB free":
        raise runner.StudyStop("original stop reason changed")
    results = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(results, list) or len(results) != 1:
        raise runner.StudyStop("expected exactly one preserved trial result")
    first = results[0]
    if first.get("ordinal") != 1 or any(
        first.get(key) != lock["order"][0][key]
        for key in ("task_id", "replicate", "model", "controller")
    ):
        raise runner.StudyStop("first result does not match frozen order")
    if first.get("applied") is not False:
        raise runner.StudyStop("original result crossed promotion boundary")
    if len(lock["order"]) != 32:
        raise runner.StudyStop("frozen order is not 32 trials")
    return lock, results


def main() -> int:
    lock, results = _preflight()
    CONTINUATION.mkdir(parents=True, exist_ok=False)
    runner.EVIDENCE = CONTINUATION
    runner.RUNS = CONTINUATION / "runs"
    runner.save_json(CONTINUATION / "provenance.json", {
        "kind": "post_stop_continuation",
        "original_evidence": str(ORIGINAL),
        "original_events_sha256": _sha256(ORIGINAL / "events.jsonl"),
        "original_results_sha256": _sha256(ORIGINAL / "raw_results.json"),
        "frozen_lock_sha256": _sha256(runner.LOCK_PATH),
        "first_preserved_ordinal": 1,
        "first_new_ordinal": 2,
    })
    runner.save_json(CONTINUATION / "raw_results.json", results)
    runner.append_event("continuation_started", first_new_ordinal=2,
                        lock_sha256=_sha256(runner.LOCK_PATH))
    tasks = {task["id"]: task for task in lock["tasks"]}
    for ordinal, cell in enumerate(lock["order"], 1):
        if ordinal == 1:
            continue
        try:
            runner.check_lock(lock)
            runner.append_event("trial_started", ordinal=ordinal, **cell)
            outcome = asyncio.run(runner.run_one(cell, lock, tasks[cell["task_id"]], ordinal))
            results.append(outcome)
            runner.save_json(CONTINUATION / "raw_results.json", results)
            runner.append_event("trial_finished", ordinal=ordinal,
                                classification=outcome["classification"], status=outcome["status"])
            if outcome["classification"] in {"FALSE_ACCEPTANCE", "INVALID"}:
                raise runner.StudyStop(f"required safety stop after trial {ordinal}")
        except runner.StudyStop as exc:
            runner.append_event("stopped", ordinal=ordinal, reason=str(exc))
            return 2
    runner.append_event("completed", trials=len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
