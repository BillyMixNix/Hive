"""Deterministic attention ranking for Hive's Steward realm.

The Steward does not invent work or silently change priorities. It derives an
explainable briefing from the orchestration snapshot already recorded by Hive.
"""

from __future__ import annotations

from typing import Any


ACTIVE_TASK_STATES = {"queued", "ready", "assigned", "running", "blocked", "review"}


def build_steward_brief(snapshot: dict[str, Any], *, limit: int = 8) -> dict[str, Any]:
    tasks = {
        task["task_id"]: task
        for task in snapshot.get("tasks", [])
        if task.get("task_id")
    }
    projects = {
        project["project_id"]: project
        for project in snapshot.get("projects", [])
        if project.get("project_id")
    }
    downstream = {
        task_id: _downstream_ids(task_id, tasks)
        for task_id in tasks
    }
    completed = {
        task_id for task_id, task in tasks.items()
        if task.get("status") == "completed"
    }
    recommendations: list[dict[str, Any]] = []

    for task_id, task in tasks.items():
        status = task.get("status")
        project = projects.get(task.get("project_id"), {})
        project_name = project.get("name") or task.get("project_id") or "Unassigned"
        impact = len(downstream[task_id])
        base_evidence = {
            "task_id": task_id,
            "project_id": task.get("project_id"),
            "downstream_tasks": sorted(downstream[task_id]),
            "downstream_count": impact,
        }

        if status == "blocked":
            reason = (
                task.get("blocked_reason")
                or task.get("failure_error")
                or task.get("reason")
                or "No blocker reason has been reported."
            )
            recommendations.append({
                "kind": "blocker",
                "score": 1_000 + impact * 100 + _priority(task, project),
                "project_id": task.get("project_id"),
                "task_id": task_id,
                "title": f"Unblock {task.get('title') or task_id}",
                "message": f"{project_name} is blocked: {reason}",
                "recommended_action": task.get("unblock_action") or "Resolve or clarify the blocker.",
                "evidence": {**base_evidence, "reason": reason},
            })
            continue

        if _is_review_ready(task):
            recommendations.append({
                "kind": "review",
                "score": 800 + impact * 100 + _priority(task, project),
                "project_id": task.get("project_id"),
                "task_id": task_id,
                "title": f"Review {task.get('title') or task_id}",
                "message": f"{project_name} has completed work ready for review.",
                "recommended_action": "Review the worker outcome and approve or return it.",
                "evidence": {
                    **base_evidence,
                    "outcome": task.get("outcome") or {},
                },
            })
            continue

        dependencies = set(task.get("depends_on") or [])
        ready = status in {"queued", "ready"} and dependencies.issubset(completed)
        if ready:
            recommendations.append({
                "kind": "leverage",
                "score": 600 + impact * 100 + _priority(task, project),
                "project_id": task.get("project_id"),
                "task_id": task_id,
                "title": f"Advance {task.get('title') or task_id}",
                "message": (
                    f"{project_name}: this ready task unlocks {impact} downstream "
                    f"{'task' if impact == 1 else 'tasks'}."
                ),
                "recommended_action": "Dispatch this task to a capable worker.",
                "evidence": base_evidence,
            })

    for project_id, project in projects.items():
        if project.get("stalled"):
            recommendations.append({
                "kind": "stalled",
                "score": 950 + int(project.get("priority", 0) or 0),
                "project_id": project_id,
                "task_id": None,
                "title": f"Recover {project.get('name') or project_id}",
                "message": "All reported workers for this active project are stale.",
                "recommended_action": "Inspect or restart the project's workers.",
                "evidence": {
                    "project_id": project_id,
                    "worker_ids": [
                        worker.get("worker_id")
                        for worker in project.get("workers", [])
                    ],
                },
            })
        elif project.get("blocked") and not any(
            item.get("project_id") == project_id and item["kind"] == "blocker"
            for item in recommendations
        ):
            recommendations.append({
                "kind": "blocker",
                "score": 975 + int(project.get("priority", 0) or 0),
                "project_id": project_id,
                "task_id": None,
                "title": f"Clarify {project.get('name') or project_id}",
                "message": "The project is blocked without a task-level blocker.",
                "recommended_action": "Record the blocking task and required decision.",
                "evidence": {"project_id": project_id},
            })

    recommendations.sort(
        key=lambda item: (
            {
                "blocker": 0,
                "stalled": 1,
                "review": 2,
                "leverage": 3,
            }.get(item["kind"], 9),
            -item["score"],
            item.get("project_id") or "",
            item.get("task_id") or "",
        )
    )
    attention = recommendations[:max(1, limit)]
    leverage = [item for item in recommendations if item["kind"] == "leverage"]
    review_count = sum(item["kind"] == "review" for item in recommendations)
    blocker_count = sum(item["kind"] in {"blocker", "stalled"} for item in recommendations)
    primary = attention[0] if attention else None
    return {
        "realm": "steward",
        "primary_attention": primary,
        "highest_leverage": leverage[0] if leverage else None,
        "attention": attention,
        "summary": {
            "attention_count": len(recommendations),
            "blocker_count": blocker_count,
            "review_count": review_count,
            "leverage_count": len(leverage),
        },
        "briefing": (
            primary["message"]
            if primary
            else "No intervention is required from the current evidence."
        ),
    }


def _priority(task: dict[str, Any], project: dict[str, Any]) -> int:
    return (
        int(project.get("priority", 0) or 0) * 10
        + int(task.get("priority", 0) or 0)
    )


def _is_review_ready(task: dict[str, Any]) -> bool:
    if task.get("status") == "review":
        return True
    if task.get("status") != "completed":
        return False
    if task.get("review_status") in {"approved", "accepted", "not_required"}:
        return False
    return bool(task.get("requires_review") or task.get("outcome"))


def _downstream_ids(
    task_id: str,
    tasks: dict[str, dict[str, Any]],
) -> set[str]:
    direct = {
        candidate_id
        for candidate_id, candidate in tasks.items()
        if task_id in set(candidate.get("depends_on") or [])
        and candidate.get("status") in ACTIVE_TASK_STATES
    }
    found = set(direct)
    frontier = list(direct)
    while frontier:
        current = frontier.pop()
        for candidate_id, candidate in tasks.items():
            if candidate_id in found or candidate_id == task_id:
                continue
            if current in set(candidate.get("depends_on") or []):
                found.add(candidate_id)
                frontier.append(candidate_id)
    return found
