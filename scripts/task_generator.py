#!/usr/bin/env python3
"""
Generates and queues self-improvement tasks for Hive.

Pipeline: scan_repo → rank → deduplicate → write to hive_queue.jsonl

Usage:
  python -m scripts.task_generator           # add top 5 tasks to queue
  python -m scripts.task_generator --dry-run # print without writing
  python -m scripts.task_generator --top 10  # add top 10 tasks
"""
import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
QUEUE_PATH = REPO_ROOT / "hive_queue.jsonl"


def load_queue():
    if not QUEUE_PATH.exists():
        return []
    entries = []
    for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return entries


def _queue_key(entry):
    return (entry.get("target_file") or "", entry.get("target_symbol") or "")


def generate(top=5, dry_run=False):
    from scripts.task_scanner import scan_repo
    from scripts.task_ranker import rank

    existing = load_queue()
    done_keys = {_queue_key(e) for e in existing if e.get("status") in ("done", "pending", "running")}

    candidates = scan_repo()
    ranked = rank(candidates)

    new_tasks = []
    for candidate in ranked:
        key = _queue_key(candidate)
        if key in done_keys:
            continue
        task = {
            "note": candidate["note"],
            "target_file": candidate.get("target_file"),
            "target_symbol": candidate.get("target_symbol"),
            "tag": candidate.get("tag", "self-improvement"),
            "status": "pending",
        }
        new_tasks.append(task)
        done_keys.add(key)
        if len(new_tasks) >= top:
            break

    if dry_run:
        print(f"[dry-run] Would add {len(new_tasks)} task(s):")
        for t in new_tasks:
            print(f"  {t['target_file']}:{t.get('target_symbol','')} — {t['note'][:70]}")
        return new_tasks

    all_entries = existing + new_tasks
    QUEUE_PATH.write_text(
        "\n".join(json.dumps(e) for e in all_entries) + "\n",
        encoding="utf-8",
    )
    print(f"Added {len(new_tasks)} task(s) to {QUEUE_PATH.name}")
    return new_tasks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()
    generate(top=args.top, dry_run=args.dry_run)
