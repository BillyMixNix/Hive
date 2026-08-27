"""Deterministic attention ranking for Hive's Steward realm.

The Steward does not invent work or silently change priorities. It derives an
explainable briefing from the orchestration snapshot already recorded by Hive.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from orchestration import OrchestrationLedger


ACTIVE_TASK_STATES = {"queued", "ready", "assigned", "running", "blocked", "review"}
STEWARD_ACTIONS = {"approve", "defer", "reprioritize", "context", "reject"}


def build_steward_brief(
    snapshot: dict[str, Any],
    *,
    limit: int = 8,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
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
        if _is_deferred(task, now):
            continue
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
        if _is_deferred(project, now):
            continue
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
        elif (
            project.get("blocked")
            and (
                project.get("status") == "blocked"
                or any(
                    task.get("status") == "blocked" and not _is_deferred(task, now)
                    for task in project.get("tasks", [])
                )
            )
            and not any(
            item.get("project_id") == project_id and item["kind"] == "blocker"
            for item in recommendations
            )
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


class StewardController:
    """Record a user judgment and let the next snapshot recompute the brief."""

    def __init__(self, ledger: OrchestrationLedger):
        self.ledger = ledger

    def act(
        self,
        action: str,
        *,
        task_id: str | None = None,
        project_id: str | None = None,
        value: Any = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        action = str(action or "").strip().lower()
        if action not in STEWARD_ACTIONS:
            raise ValueError(f"Unsupported Steward action: {action}")
        if bool(task_id) == bool(project_id):
            raise ValueError("Provide exactly one task_id or project_id")

        with self.ledger.lock:
            snapshot = self.ledger.snapshot()
            if task_id:
                record = next(
                    (task for task in snapshot["tasks"] if task["task_id"] == task_id),
                    None,
                )
                subject_id = task_id
                event_type = "task.steward_decision"
            else:
                record = next(
                    (
                        project for project in snapshot["projects"]
                        if project["project_id"] == project_id
                    ),
                    None,
                )
                subject_id = project_id
                event_type = "project.steward_decision"
            if not record:
                raise ValueError("Steward recommendation target was not found")

            now = self.ledger.now_fn()
            payload = {
                "steward_action": action,
                "steward_note": str(note or "").strip() or None,
                "steward_decided_at": now.isoformat(),
            }
            if action == "approve":
                payload.update(self._approve_payload(record, task=bool(task_id)))
            elif action == "defer":
                seconds = int(value if value is not None else 24 * 60 * 60)
                if seconds < 60 or seconds > 30 * 24 * 60 * 60:
                    raise ValueError("defer seconds must be between 60 and 2592000")
                payload["deferred_until"] = (
                    now + timedelta(seconds=seconds)
                ).isoformat()
            elif action == "reprioritize":
                priority = int(value)
                if priority < -100 or priority > 100:
                    raise ValueError("priority must be between -100 and 100")
                payload["priority"] = priority
            elif action == "context":
                supplied = str(value or note or "").strip()
                if not supplied:
                    raise ValueError("context cannot be empty")
                context = dict(record.get("context") or {})
                context["user_supplied"] = supplied
                payload.update({
                    "context": context,
                    "context_supplied": True,
                })
            else:
                payload.update(self._reject_payload(
                    record,
                    task=bool(task_id),
                    note=note,
                    now=now,
                ))

            return self.ledger.append(
                event_type,
                str(subject_id),
                payload,
                source="steward:user",
                occurred_at=now,
            )

    @staticmethod
    def _approve_payload(record: dict[str, Any], *, task: bool) -> dict[str, Any]:
        if task and _is_review_ready(record):
            return {
                "status": "completed",
                "review_status": "approved",
                "approved_for_dispatch": False,
                "deferred_until": None,
            }
        return {
            "steward_status": "approved",
            "approved_for_dispatch": bool(task),
            "deferred_until": None,
        }

    @staticmethod
    def _reject_payload(
        record: dict[str, Any],
        *,
        task: bool,
        note: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        payload = {
            "steward_status": "rejected",
            "rejection_reason": str(note or "").strip() or "Rejected by user",
            "deferred_until": (now + timedelta(days=1)).isoformat(),
        }
        if task and _is_review_ready(record):
            payload.update({
                "status": "queued",
                "review_status": "changes_requested",
                "assigned_worker_id": None,
                "lease_id": None,
                "lease_expires_at": None,
            })
        return payload


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


def _is_deferred(record: dict[str, Any], now: datetime) -> bool:
    value = record.get("deferred_until")
    if not value:
        return False
    try:
        deferred_until = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if deferred_until.tzinfo is None:
        deferred_until = deferred_until.replace(tzinfo=timezone.utc)
    return deferred_until > now


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
