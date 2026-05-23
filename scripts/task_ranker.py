#!/usr/bin/env python3
"""
Ranks candidate task dicts from task_scanner by priority score.

Scoring dimensions:
  - impact:          how many files reference the target symbol
  - pattern_urgency: whether hive_lessons.jsonl has trusted lessons for this pattern
  - structural_risk: whether the target is in the critical execution path
  - priority_hint:   explicit hint from scanner ("high" / "medium" / "low")
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

CRITICAL_PATH = {"planner.py", "coder.py", "executor.py", "router.py", "main.py"}

PRIORITY_SCORES = {"high": 30, "medium": 15, "low": 5}


def _score_impact(candidate, py_files):
    """Count files that reference the target symbol."""
    symbol = candidate.get("target_symbol") or ""
    if not symbol:
        return 0
    count = 0
    pattern = re.compile(r'\b' + re.escape(symbol) + r'\b')
    for f in py_files:
        try:
            if pattern.search(f.read_text(encoding="utf-8")):
                count += 1
        except Exception:
            pass
    return min(count * 5, 40)


def _score_pattern_urgency(candidate, lessons):
    """Score based on trusted lessons that match this failure pattern."""
    symbol = (candidate.get("target_symbol") or "").lower()
    filename = (candidate.get("target_file") or "").lower()
    trusted = [l for l in lessons if l.get("promotion_state") == "trusted"]
    for lesson in trusted:
        pattern = (lesson.get("failure_pattern") or "").lower()
        if symbol and symbol in pattern:
            return 25
        if filename and filename in pattern:
            return 15
    return 0


def _score_structural_risk(candidate):
    """Higher score if the target is in the critical execution path."""
    filename = candidate.get("target_file") or ""
    return 20 if filename in CRITICAL_PATH else 0


def _score_priority_hint(candidate):
    hint = (candidate.get("priority_hint") or "medium").lower()
    return PRIORITY_SCORES.get(hint, 15)


def rank(candidates, repo_root=None, lessons_path=None):
    """Return candidates sorted by score descending."""
    repo_root = Path(repo_root or REPO_ROOT)
    lessons_path = Path(lessons_path or REPO_ROOT / "hive_lessons.jsonl")

    py_files = list(repo_root.rglob("*.py"))

    lessons = []
    if lessons_path.exists():
        for line in lessons_path.read_text(encoding="utf-8").splitlines():
            try:
                lessons.append(json.loads(line))
            except Exception:
                pass

    scored = []
    for candidate in candidates:
        score = (
            _score_priority_hint(candidate)
            + _score_structural_risk(candidate)
            + _score_pattern_urgency(candidate, lessons)
            + _score_impact(candidate, py_files)
        )
        scored.append({**candidate, "_score": score})

    return sorted(scored, key=lambda x: x["_score"], reverse=True)


if __name__ == "__main__":
    from scripts.task_scanner import scan_repo
    candidates = scan_repo()
    ranked = rank(candidates)
    print(f"Ranked {len(ranked)} candidates. Top 5:")
    for r in ranked[:5]:
        print(f"  [{r['_score']}] {r['target_file']}:{r.get('target_symbol','')} — {r['note'][:60]}")
