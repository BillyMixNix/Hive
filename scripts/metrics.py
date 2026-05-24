#!/usr/bin/env python3
"""
Hive run metrics — captures hard numbers before and after each autonomous run.

Recorded per run:
  - timestamp, run_id
  - tasks: attempted, succeeded, failed
  - patches: applied, rejected
  - lessons: total, trusted, added this run, promoted this run
  - code quality: pylint score, cyclomatic complexity for critical path files
  - patch success rate (rolling)
  - failure pattern counts by family

Usage:
  from scripts.metrics import RunMetrics
  m = RunMetrics()
  m.capture_pre_run(lesson_memory)
  # ... run tasks ...
  m.capture_post_run(lesson_memory, done=6, failed=3, patches_applied=2, patches_rejected=1)
  m.save()
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
METRICS_PATH = REPO_ROOT / "hive_metrics.jsonl"
CRITICAL_PATH = ["planner.py", "coder.py", "executor.py", "router.py", "main.py"]


def _pylint_score(filepath):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pylint", str(filepath),
             "--score=yes", "--output-format=text", "--disable=all",
             "--enable=E,W"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines():
            if "Your code has been rated at" in line:
                score_str = line.split("at")[1].split("/")[0].strip()
                return float(score_str)
    except Exception:
        pass
    return None


def _cyclomatic_complexity(filepath):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "radon", "cc", str(filepath), "-a", "-s"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines():
            if "Average complexity" in line:
                val = line.split("(")[1].rstrip(")")
                return float(val)
    except Exception:
        pass
    return None


def _maintainability_index(filepath):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "radon", "mi", str(filepath), "-s"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    return float(parts[-1].strip("()ABCDEFabcdef "))
                except ValueError:
                    pass
    except Exception:
        pass
    return None


def _code_quality_snapshot():
    snapshot = {}
    for filename in CRITICAL_PATH:
        path = REPO_ROOT / filename
        if not path.exists():
            continue
        snapshot[filename] = {
            "pylint_score": _pylint_score(path),
            "cyclomatic_complexity": _cyclomatic_complexity(path),
            "maintainability_index": _maintainability_index(path),
            "line_count": len(path.read_text(encoding="utf-8").splitlines()),
        }
    return snapshot


def _lesson_snapshot(lesson_memory):
    try:
        lessons = lesson_memory.lessons if hasattr(lesson_memory, "lessons") else []
        if not lessons:
            lessons_path = REPO_ROOT / "hive_lessons.jsonl"
            if lessons_path.exists():
                lessons = [
                    json.loads(l) for l in lessons_path.read_text().splitlines() if l.strip()
                ]
        total = len(lessons)
        trusted = sum(1 for l in lessons if l.get("promotion_state") == "trusted")
        by_family = {}
        for l in lessons:
            fam = (l.get("failure_family") or l.get("code") or "unknown").split("/")[0]
            by_family[fam] = by_family.get(fam, 0) + 1
        return {"total": total, "trusted": trusted, "by_family": by_family}
    except Exception:
        return {"total": 0, "trusted": 0, "by_family": {}}


def _patch_success_rate():
    memory_path = REPO_ROOT / "hive_memory.json"
    try:
        data = json.loads(memory_path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", [])
        patches = [i for i in items if (i.get("tag") or i.get("type")) == "patch"]
        if not patches:
            return None
        applied = sum(1 for p in patches if (p.get("status") or "") == "applied")
        return round(applied / len(patches), 3)
    except Exception:
        return None


class RunMetrics:
    def __init__(self):
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.started_at = time.time()
        self.pre = {}
        self.post = {}

    def capture_pre_run(self, lesson_memory=None):
        print("[metrics] Capturing pre-run snapshot...")
        self.pre = {
            "code_quality": _code_quality_snapshot(),
            "lessons": _lesson_snapshot(lesson_memory) if lesson_memory else {},
            "patch_success_rate": _patch_success_rate(),
        }
        print(f"[metrics] Pre-run: {self.pre['lessons'].get('total', 0)} lessons, "
              f"{self.pre['lessons'].get('trusted', 0)} trusted")

    def capture_post_run(self, lesson_memory=None, done=0, failed=0,
                         patches_applied=0, patches_rejected=0):
        print("[metrics] Capturing post-run snapshot...")
        post_lessons = _lesson_snapshot(lesson_memory) if lesson_memory else {}
        self.post = {
            "code_quality": _code_quality_snapshot(),
            "lessons": post_lessons,
            "patch_success_rate": _patch_success_rate(),
            "tasks_done": done,
            "tasks_failed": failed,
            "patches_applied": patches_applied,
            "patches_rejected": patches_rejected,
            "task_success_rate": round(done / (done + failed), 3) if (done + failed) > 0 else 0,
        }

        pre_lessons = self.pre.get("lessons", {})
        lessons_added = post_lessons.get("total", 0) - pre_lessons.get("total", 0)
        lessons_promoted = post_lessons.get("trusted", 0) - pre_lessons.get("trusted", 0)
        self.post["lessons_added"] = lessons_added
        self.post["lessons_promoted"] = lessons_promoted

        print(f"[metrics] Post-run: tasks {done}/{done+failed}, "
              f"patches applied={patches_applied} rejected={patches_rejected}, "
              f"lessons +{lessons_added} promoted +{lessons_promoted}")

    def save(self):
        record = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "elapsed_seconds": round(time.time() - self.started_at, 1),
            "pre": self.pre,
            "post": self.post,
        }
        with open(METRICS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[metrics] Saved run {self.run_id} → {METRICS_PATH.name}")
        return record


def report(n=10):
    """Print a human-readable improvement report from the last N runs."""
    if not METRICS_PATH.exists():
        print("No metrics recorded yet.")
        return

    runs = []
    for line in METRICS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            runs.append(json.loads(line))
        except Exception:
            pass

    runs = runs[-n:]
    if not runs:
        print("No runs found.")
        return

    print(f"\n{'='*70}")
    print(f"HIVE METRICS REPORT — last {len(runs)} run(s)")
    print(f"{'='*70}")

    for r in runs:
        post = r.get("post", {})
        pre = r.get("pre", {})
        print(f"\nRun {r['run_id']}  ({round(r.get('elapsed_seconds',0)/60, 1)} min)")
        print(f"  Tasks:    {post.get('tasks_done',0)} done / "
              f"{post.get('tasks_failed',0)} failed  "
              f"(success rate: {post.get('task_success_rate', 0)*100:.0f}%)")
        print(f"  Patches:  {post.get('patches_applied',0)} applied, "
              f"{post.get('patches_rejected',0)} rejected")
        print(f"  Lessons:  {post.get('lessons', {}).get('total',0)} total, "
              f"{post.get('lessons', {}).get('trusted',0)} trusted  "
              f"(+{post.get('lessons_added',0)} added, "
              f"+{post.get('lessons_promoted',0)} promoted)")

        pre_rate = pre.get("patch_success_rate")
        post_rate = post.get("patch_success_rate")
        if pre_rate is not None and post_rate is not None:
            delta = round((post_rate - pre_rate) * 100, 1)
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            print(f"  Patch success rate: {pre_rate*100:.1f}% → {post_rate*100:.1f}%  {arrow}{abs(delta)}%")

        for fname in CRITICAL_PATH:
            pre_q = (pre.get("code_quality") or {}).get(fname, {})
            post_q = (post.get("code_quality") or {}).get(fname, {})
            if not pre_q or not post_q:
                continue
            pre_cc = pre_q.get("cyclomatic_complexity")
            post_cc = post_q.get("cyclomatic_complexity")
            pre_mi = pre_q.get("maintainability_index")
            post_mi = post_q.get("maintainability_index")
            if pre_cc and post_cc and pre_cc != post_cc:
                arrow = "↓" if post_cc < pre_cc else "↑"
                print(f"  {fname}: complexity {pre_cc:.1f} → {post_cc:.1f} {arrow}  "
                      f"maintainability {pre_mi:.1f} → {post_mi:.1f}")

    if len(runs) >= 2:
        first, last = runs[0], runs[-1]
        print(f"\n{'─'*70}")
        print(f"TREND across {len(runs)} runs:")
        first_rate = first.get("post", {}).get("task_success_rate", 0)
        last_rate = last.get("post", {}).get("task_success_rate", 0)
        delta = round((last_rate - first_rate) * 100, 1)
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        print(f"  Task success rate: {first_rate*100:.0f}% → {last_rate*100:.0f}%  {arrow}{abs(delta)}%")
        first_trusted = first.get("post", {}).get("lessons", {}).get("trusted", 0)
        last_trusted = last.get("post", {}).get("lessons", {}).get("trusted", 0)
        print(f"  Trusted lessons:  {first_trusted} → {last_trusted}  (+{last_trusted - first_trusted})")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    report()
