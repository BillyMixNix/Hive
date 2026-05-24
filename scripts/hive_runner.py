#!/usr/bin/env python3
"""
Autonomous Hive runner. Reads tasks from hive_queue.jsonl and runs the
full pipeline (store → plan → code → validate → apply) without a human
pilot in the loop. Executor validation still runs — only the human
approval gate is skipped.

Queue format (one JSON object per line):
  {"note": "Fix the bug in executor.py where ...", "target_file": "executor.py"}

Status values written back: "pending" → "running" → "done" | "failed"
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _bootstrap_api_key():
    """Load ANTHROPIC_API_KEY from Claude settings if not already in environment."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    for settings_path in (
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.local.json",
    ):
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            key = (data.get("env") or {}).get("ANTHROPIC_API_KEY")
            if key:
                os.environ["ANTHROPIC_API_KEY"] = key
                print(f"  [runner] Loaded ANTHROPIC_API_KEY from {settings_path}")
                return
        except Exception:
            pass


_bootstrap_api_key()

from router import Router
from reflector import Reflector
from scripts.metrics import RunMetrics
from HiveMemoryAgent import HiveMemoryAgent
from HiveLessonMemory import LessonMemory
from HiveStateManager import HiveStateManager
from repo_map import RepoMap
from main import (
    make_dummy_vector,
    build_anchor_from_text,
    enrich_task_anchor_for_planning,
    find_plan_for_task,
    find_patch_entry,
    require_patch_metadata,
    update_patch_entry,
    update_last_patch_snapshot,
    update_current_snapshot,
    _get_first_ready_child_task,
    _initialize_child_task_statuses,
    _resolve_code_task_anchor,
    _store_code_task_result,
    _complete_child_task,
    build_pilot_review_packet,
    list_pending_pilot_review_patches,
    sync_lessons_observability,
    record_failure_observability,
)

QUEUE_PATH = Path(__file__).parent.parent / "hive_queue.jsonl"
MAX_CODE_CYCLES = 3  # max child tasks per parent before giving up


def load_queue():
    if not QUEUE_PATH.exists():
        return []
    entries = []
    for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def save_queue(entries):
    QUEUE_PATH.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def setup_components():
    memory = HiveMemoryAgent(device="cpu")
    state = HiveStateManager(repo_root=".")
    state.load_snapshot()
    repo_map = RepoMap(root=".")
    state.set_repo_map(repo_map.build())
    router = Router()
    router.planner = router.planner.__class__(state_manager=state)
    router.coder = router.coder.__class__(
        memory=memory,
        state_manager=state,
        executor=router.executor,
    )
    reflector = Reflector()
    lesson_memory = LessonMemory()
    sync_lessons_observability(state, lesson_memory)
    return memory, state, router, reflector, lesson_memory


def store_task(entry, memory, state):
    note = entry.get("note", "").strip()
    if not note:
        raise ValueError("Queue entry missing 'note' field.")
    anchor = build_anchor_from_text(note, state_manager=state)
    memory.store(
        make_dummy_vector(),
        tag=entry.get("tag", "task"),
        note=note,
        status="active",
        metadata={
            "target_file": entry.get("target_file") or anchor.get("target_file"),
            "target_symbol": entry.get("target_symbol") or anchor.get("target_symbol"),
            "anchor": anchor,
        },
    )
    task_id = memory.ptr  # ptr was incremented by store(); stored item is at ptr-1, id = ptr
    print(f"  Stored task {task_id}: {note[:80]}")
    return task_id


def plan_task(task_id, memory, state, router):
    task = memory.get_task_by_id(task_id)
    if not task:
        raise RuntimeError(f"Task {task_id} not found after store.")
    task = enrich_task_anchor_for_planning(task, memory=memory, state_manager=state)
    result = router.planner.plan_task(task)
    if result.get("status") == "blocked":
        error = result.get("llm_error", "planner blocked")
        memory.update_task_status(task_id, "blocked")
        raise RuntimeError(f"Planner blocked: {error}")
    result = _initialize_child_task_statuses(result)
    anchor = (task.get("metadata") or {}).get("anchor") or build_anchor_from_text(task.get("note"), state_manager=state)
    memory.update_task_status(task_id, "planned")
    memory.store(
        make_dummy_vector(), tag="plan",
        note=f"Task {task_id} planned | {result['goal']} | next: {result['next_action']}",
        status="planned",
        metadata={"task_id": task_id, "plan_id": f"plan-{task_id}", "plan": result, "anchor": anchor},
    )
    update_current_snapshot(state, task=task, plan=result,
                            child=_get_first_ready_child_task(result), status="planned")
    print(f"  Planned: {result['goal']}")
    print(f"  Child tasks: {len(result.get('tasks', []))}")
    return result


def auto_accept_patch(patch_id, memory, state, lesson_memory):
    patch_entry, error = find_patch_entry(memory, patch_id)
    if error or patch_entry is None:
        raise RuntimeError(error or f"Patch {patch_id} not found.")
    meta, error = require_patch_metadata(patch_entry, patch_id)
    if error or meta is None:
        raise RuntimeError(error or f"Patch {patch_id} has no metadata.")
    meta = dict(meta)
    meta["pilot_verdict"] = "accept"
    meta["pilot_reason"] = "Auto-accepted by hive_runner (autonomous mode)."
    meta["pilot_guidance"] = None
    meta["location_correct"] = True
    meta["task_alignment"] = True
    meta["plan_step_alignment"] = True
    update_patch_entry(memory, patch_id, metadata=meta, status="approved")
    update_last_patch_snapshot(state, meta, patch_id=patch_id, patch_status="approved",
                               pilot_verdict="accept", pilot_reason=meta["pilot_reason"],
                               pilot_guidance=None)
    sync_lessons_observability(state, lesson_memory)
    print(f"  Auto-accepted patch {patch_id}")


def apply_patch(patch_id, memory, state, router, lesson_memory):
    patch_entry, error = find_patch_entry(memory, patch_id)
    if error or patch_entry is None:
        raise RuntimeError(error or f"Patch {patch_id} not found.")
    meta, error = require_patch_metadata(patch_entry, patch_id)
    if error:
        raise RuntimeError(error)
    meta = dict(meta)
    target_file = meta["target_file"]
    patch_text = meta["patch"]
    patch_reason = meta.get("reason", "")
    file_text = state.get_effective_file_text(target_file)

    verification = router.executor.verify_patch_context(patch_text, target_file, file_text=file_text)
    if not verification["verified"]:
        raise RuntimeError(f"Patch failed verification: {verification['checks']}")

    router.executor.backup_file(target_file)
    router.executor.apply_patch(patch_text, target_file, patch_reason=patch_reason, file_text=file_text)
    memory.update_task_status(patch_id, "applied")
    updated_text = Path(target_file).read_text(encoding="utf-8")
    state.record_patch_apply(target_file, patch_id, updated_text)
    state.rebuild_repo_map()
    state.save_snapshot()
    print(f"  Applied patch {patch_id} → {target_file}")

    child_task_id = meta.get("child_task_id")
    parent_task_id = meta.get("task_id")
    if child_task_id and parent_task_id:
        plan = find_plan_for_task(memory, parent_task_id)
        if plan:
            updated_plan = _complete_child_task(plan, child_task_id)
            memory.store(
                make_dummy_vector(), tag="plan",
                note=f"Task {parent_task_id} plan updated | {updated_plan['goal']}",
                status="planned",
                metadata={"task_id": parent_task_id, "plan_id": f"plan-{parent_task_id}", "plan": updated_plan},
            )


def run_task(entry, memory, state, router, reflector, lesson_memory):
    print(f"\n{'='*60}")
    print(f"Task: {entry.get('note', '')[:80]}")
    print(f"{'='*60}")

    # Stub creation: if the target file doesn't exist, create a minimal
    # placeholder so the planner can anchor to it properly.
    target_file = entry.get("target_file", "")
    if target_file and not Path(target_file).exists():
        stub_path = Path(target_file)
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(
            f'"""{entry.get("note", "").strip()[:200]}"""\n',
            encoding="utf-8",
        )
        state.rebuild_repo_map()
        print(f"  Created stub: {target_file}")

    task_id = store_task(entry, memory, state)

    plan = plan_task(task_id, memory, state, router)
    child_count = len(plan.get("tasks", []))

    # Planner anchor drift detection: if every child task targets a different
    # file than what was requested, record a lesson and abort early.
    requested_file = (entry.get("target_file") or "").strip()
    if requested_file:
        child_files = {(c.get("target_file") or "").strip() for c in plan.get("tasks", [])}
        child_files.discard("")
        if child_files and not any(
            requested_file in f or f in requested_file for f in child_files
        ):
            drift_note = (
                f"Planner anchor drift: task requested {requested_file} "
                f"but plan targets {child_files}. "
                f"Ensure target_file exists before planning."
            )
            print(f"  WARNING: {drift_note}")
            lesson_memory.add_lesson(
                file=requested_file,
                change_type="diff_patch",
                failure_reason="planner_anchor_drift",
                failure_pattern=drift_note,
                retry_instruction=(
                    "Create a stub of the target file before planning so the planner "
                    "can anchor to the correct file instead of drifting to an existing one."
                ),
                source="hive_runner",
                severity="high",
            )

    for cycle in range(MAX_CODE_CYCLES):
        ready_child = _get_first_ready_child_task(plan)
        if not ready_child:
            print(f"  All child tasks complete after {cycle} cycle(s).")
            break

        print(f"  Cycle {cycle+1}/{child_count}: {ready_child.get('title', '')[:60]}")

        task = memory.get_task_by_id(task_id)
        task_metadata = (task or {}).get("metadata") or {}
        coder_task, effective_plan, anchor, _, child_target_symbol = (
            _resolve_code_task_anchor(task, ready_child, plan, state, task_metadata)
        )

        result = router.coder.generate_patch_with_revisions(coder_task, effective_plan, reflector)

        _store_code_task_result(
            result, task_id, task, ready_child, anchor, child_target_symbol,
            task_metadata, memory, state, lesson_memory, make_dummy_vector,
            build_pilot_review_packet,
            lambda *a, **kw: None,  # update_last_patch_snapshot handled in apply
            record_failure_observability,
            sync_lessons_observability,
        )

        if result.get("status") == "rejected" or result.get("status") == "failed":
            print(f"  Coder failed on child task: {result.get('reason') or result.get('status')}")
            break

        # Find the patch that was just stored as pending_pilot_review
        pending = list_pending_pilot_review_patches(memory, limit=1)
        if not pending:
            print("  No patch pending review — child task may already be complete.")
            plan = find_plan_for_task(memory, task_id) or plan
            continue

        patch_id = pending[0].get("id")
        auto_accept_patch(patch_id, memory, state, lesson_memory)
        try:
            apply_patch(patch_id, memory, state, router, lesson_memory)
        except RuntimeError as e:
            print(f"  Apply failed: {e}")
            break

        # Reload plan after child task completed
        plan = find_plan_for_task(memory, task_id) or plan

    memory.update_task_status(task_id, "done")
    print(f"  Task {task_id} complete.")


def main():
    entries = load_queue()
    pending = [e for e in entries if e.get("status", "pending") == "pending"]

    # Auto-refill: if fewer than 2 pending tasks, generate new ones from codebase scan.
    if len(pending) < 2:
        try:
            from scripts.task_generator import generate
            print(f"Queue low ({len(pending)} pending) — running task generator...")
            generate(top=5)
            entries = load_queue()
            pending = [e for e in entries if e.get("status", "pending") == "pending"]
        except Exception as exc:
            print(f"  Task generator failed (continuing): {exc}")

    if not pending:
        print(f"Queue is empty: {QUEUE_PATH}")
        return

    print(f"Hive Runner — {len(pending)} task(s) pending")
    memory, state, router, reflector, lesson_memory = setup_components()

    metrics = RunMetrics()
    metrics.capture_pre_run(lesson_memory)

    patches_applied = 0
    patches_rejected = 0

    for i, entry in enumerate(entries):
        if entry.get("status", "pending") != "pending":
            continue
        entry["status"] = "running"
        save_queue(entries)
        try:
            run_task(entry, memory, state, router, reflector, lesson_memory)
            entry["status"] = "done"
            patches_applied += 1
        except Exception as exc:
            print(f"  FAILED: {exc}")
            entry["status"] = "failed"
            entry["error"] = str(exc)
            patches_rejected += 1
        save_queue(entries)

    done = sum(1 for e in entries if e.get("status") == "done")
    failed = sum(1 for e in entries if e.get("status") == "failed")
    print(f"\nDone: {done}  Failed: {failed}")

    metrics.capture_post_run(
        lesson_memory,
        done=done,
        failed=failed,
        patches_applied=patches_applied,
        patches_rejected=patches_rejected,
    )
    metrics.save()


def loop(max_runs=None, rest_seconds=30, tasks_per_refill=10):
    """
    Run continuously until stopped (Ctrl-C) or max_runs is reached.
    After each run, sleeps briefly then starts the next one.
    The queue auto-refills so Hive always has work.
    """
    import signal

    stop = {"flag": False}

    def _handle_signal(sig, frame):
        print("\n[loop] Stop signal received — finishing current run then exiting.")
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    run_count = 0
    total_done = 0
    total_failed = 0

    print(f"[loop] Starting continuous loop (max_runs={max_runs or '∞'}, "
          f"rest={rest_seconds}s, tasks_per_refill={tasks_per_refill})")

    while not stop["flag"]:
        if max_runs is not None and run_count >= max_runs:
            print(f"[loop] Reached max_runs={max_runs}, stopping.")
            break

        run_count += 1
        print(f"\n[loop] ══════ Run {run_count} ══════")

        # Refill queue before every run
        try:
            from scripts.task_generator import generate
            entries = load_queue()
            pending = [e for e in entries if e.get("status", "pending") == "pending"]
            if len(pending) < tasks_per_refill:
                print(f"[loop] Queue has {len(pending)} pending — refilling to {tasks_per_refill}...")
                generate(top=tasks_per_refill)
        except Exception as exc:
            print(f"[loop] Refill failed (continuing): {exc}")

        try:
            done_before = sum(1 for e in load_queue() if e.get("status") == "done")
            main()
            done_after = sum(1 for e in load_queue() if e.get("status") == "done")
            failed_after = sum(1 for e in load_queue() if e.get("status") == "failed")
            run_done = done_after - done_before
            total_done += run_done
            total_failed = failed_after
        except Exception as exc:
            print(f"[loop] Run {run_count} raised: {exc}")

        print(f"\n[loop] Cumulative: {total_done} done, {total_failed} failed across {run_count} run(s)")

        if stop["flag"]:
            break

        print(f"[loop] Resting {rest_seconds}s before next run...")
        for _ in range(rest_seconds):
            if stop["flag"]:
                break
            time.sleep(1)

    print(f"\n[loop] Loop complete. {run_count} run(s), {total_done} tasks done.")
    print("[loop] Run `python -m scripts.metrics` to see the full report.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hive autonomous runner")
    parser.add_argument("--loop", action="store_true", help="Run continuously until stopped")
    parser.add_argument("--max-runs", type=int, default=None, help="Max loop iterations")
    parser.add_argument("--rest", type=int, default=30, help="Seconds between runs (default 30)")
    parser.add_argument("--tasks", type=int, default=10, help="Tasks to generate per refill (default 10)")
    args = parser.parse_args()

    if args.loop:
        loop(max_runs=args.max_runs, rest_seconds=args.rest, tasks_per_refill=args.tasks)
    else:
        main()
