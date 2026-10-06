from __future__ import annotations

import json
from pathlib import Path

RUNTIME_EXCLUDES = {".git", ".pytest_cache", "__pycache__", "data", "media", "snapshots", "self_snapshots", "hive_runs", "logs"}
MAX_CONTEXT_CHARS = 12000


def _bounded(value, limit=1200):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _safe_repo_summary(root: Path) -> dict:
    files = []
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().casefold()):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in RUNTIME_EXCLUDES or part.startswith(".") for part in rel.parts):
            continue
        if path.suffix in {".pyc", ".zip"}:
            continue
        files.append(rel.as_posix())
    return {
        "project_name": root.name,
        "workspace_path": str(root),
        "file_count": len(files),
        "sample_files": files[:80],
    }


def _run_summary(run: dict) -> dict:
    verification = run.get("verification") or {}
    review = run.get("review") or {}
    errors = run.get("errors") or []
    plan_attempts = run.get("plan_attempts") or []
    rejected_plan_attempts = []
    for attempt in plan_attempts[-3:]:
        if not isinstance(attempt, dict) or attempt.get("status") != "rejected":
            continue
        failure = attempt.get("failure") or {}
        rejected_plan_attempts.append({
            "attempt": attempt.get("attempt"),
            "stage": failure.get("stage"),
            "exception_type": failure.get("exception_type"),
            "exception_message": _bounded(failure.get("exception_message", ""), 900),
        })
    return {
        "id": run.get("id"),
        "request": run.get("request"),
        "status": run.get("status"),
        "applied": bool(run.get("applied")),
        "changed_files": run.get("changed_files") or [],
        "verification_passed": verification.get("passed"),
        "review_approved": review.get("approve"),
        "review_summary": review.get("summary"),
        "error_count": len(errors),
        "planner_rejections": rejected_plan_attempts,
        "errors": [
            {
                "role": e.get("role"),
                "stage": e.get("stage"),
                "exception_type": e.get("exception_type"),
                "exception_message": _bounded(e.get("exception_message", ""), 700),
            }
            for e in errors[:8] if isinstance(e, dict)
        ],
    }


def _recent_runs(runs_root: Path, limit=3) -> list[dict]:
    found = []
    if not runs_root.exists():
        return found
    candidates = []
    for run_file in runs_root.glob("*/run.json"):
        try:
            candidates.append((run_file.stat().st_mtime, run_file))
        except OSError:
            continue
    for _, run_file in sorted(candidates, reverse=True)[:limit]:
        try:
            run = json.loads(run_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(run, dict):
            found.append(_run_summary(run))
    return found


def _latest_run_digest(runs: list[dict]) -> str:
    if not runs:
        return "LATEST HIVE RUN: none found in this Workshop runtime."
    latest = runs[0]
    lines = [
        f"LATEST HIVE RUN: id={latest.get('id')} status={latest.get('status')} applied={latest.get('applied')}",
        f"Request: {latest.get('request') or '(not recorded)'}",
        f"Verification passed: {latest.get('verification_passed')}",
        f"Reviewer approved: {latest.get('review_approved')}",
    ]
    if latest.get("review_summary"):
        lines.append("Review: " + str(latest["review_summary"]))
    for item in latest.get("planner_rejections") or []:
        lines.append(
            "Planner rejection: "
            + str(item.get("exception_type") or "error")
            + ": "
            + str(item.get("exception_message") or "")
        )
    for item in latest.get("errors") or []:
        lines.append(
            "Run error: "
            + "/".join(str(item.get(k) or "") for k in ("role", "stage", "exception_type"))
            + ": "
            + str(item.get("exception_message") or "")
        )
    return "\n".join(lines)


def render(root: Path, runs_root: Path, query: str = "") -> str:
    """Render bounded, read-only Workshop state for ordinary chat turns.

    Recent Hive state is deliberately placed before repository inventory so failure
    diagnostics cannot be displaced by a large file listing.
    """
    runs = _recent_runs(runs_root)
    payload = {
        "recent_hive_runs": runs,
        "repository": _safe_repo_summary(root),
    }
    text = _latest_run_digest(runs) + "\n\nWORKSHOP STATE JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS] + "\n...[Workshop context truncated]"
    return text
