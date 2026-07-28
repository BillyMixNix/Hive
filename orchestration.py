"""Durable, evidence-first project and worker observation for Hive.

The orchestration ledger is deliberately append-only.  Connectors report facts as
events; the cockpit derives its current view from those facts.  This keeps a
useful audit trail and prevents a worker from silently rewriting project history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
from typing import Any, Iterable
from uuid import uuid4


ACTIVE_STATES = {"queued", "running", "blocked", "review"}
TERMINAL_STATES = {"completed", "cancelled", "failed"}
DISPATCHABLE_STATES = {"queued", "ready"}
ASSIGNED_STATES = {"assigned", "running"}
_LEDGER_LOCKS: dict[str, threading.RLock] = {}
_LEDGER_LOCKS_GUARD = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class OrchestrationEvent:
    event_type: str
    subject_id: str
    payload: dict[str, Any]
    occurred_at: str
    event_id: str
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "subject_id": self.subject_id,
            "source": self.source,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }


class OrchestrationLedger:
    """Append observations and derive a multi-project cockpit snapshot."""

    def __init__(
        self,
        path: str | Path,
        *,
        stale_after_seconds: int = 15 * 60,
        now_fn=_utc_now,
    ):
        self.path = Path(path)
        self.stale_after_seconds = stale_after_seconds
        self.now_fn = now_fn
        lock_key = str(self.path.resolve())
        with _LEDGER_LOCKS_GUARD:
            self.lock = _LEDGER_LOCKS.setdefault(lock_key, threading.RLock())

    def append(
        self,
        event_type: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
        *,
        source: str = "unknown",
        occurred_at: datetime | str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        if not event_type or not subject_id:
            raise ValueError("event_type and subject_id are required")
        when = _parse_time(occurred_at) or self.now_fn()
        event = OrchestrationEvent(
            event_type=str(event_type),
            subject_id=str(subject_id),
            payload=dict(payload or {}),
            occurred_at=_iso(when),
            event_id=event_id or str(uuid4()),
            source=str(source or "unknown"),
        )
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return event.to_dict()

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        seen = set()
        with self.lock:
            with self.path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"Invalid orchestration event at line {line_number}"
                        ) from exc
                    event_id = event.get("event_id")
                    if event_id and event_id in seen:
                        continue
                    if event_id:
                        seen.add(event_id)
                    events.append(event)
        return events

    def snapshot(self) -> dict[str, Any]:
        return derive_snapshot(
            self.read_events(),
            now=self.now_fn(),
            stale_after_seconds=self.stale_after_seconds,
        )


class Dispatcher:
    """Match ready work to a worker and protect it with an expiring lease."""

    def __init__(
        self,
        ledger: OrchestrationLedger,
        *,
        lease_seconds: int = 20 * 60,
    ):
        if lease_seconds < 30:
            raise ValueError("lease_seconds must be at least 30")
        self.ledger = ledger
        self.lease_seconds = lease_seconds

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        if not worker_id:
            raise ValueError("worker_id is required")
        with self.ledger.lock:
            snapshot = self.ledger.snapshot()
            workers = {worker["worker_id"]: worker for worker in snapshot["workers"]}
            worker = workers.get(worker_id)
            if not worker:
                raise ValueError(f"Unknown worker: {worker_id}")
            if worker.get("stale"):
                raise ValueError(f"Worker is stale: {worker_id}")
            if worker.get("status") in {"offline", "disabled", "failed"}:
                raise ValueError(f"Worker is unavailable: {worker_id}")

            active = [
                task for task in snapshot["tasks"]
                if task.get("assigned_worker_id") == worker_id
                and task.get("status") in ASSIGNED_STATES
                and not task.get("lease_expired")
            ]
            capacity = max(1, int(worker.get("max_concurrency", 1) or 1))
            if len(active) >= capacity:
                return None

            projects = {
                project["project_id"]: project for project in snapshot["projects"]
            }
            candidates = [
                task for task in snapshot["tasks"]
                if self._is_ready(task, snapshot["tasks"])
                and self._worker_can_run(worker, task)
                and not projects.get(task.get("project_id"), {}).get("blocked")
            ]
            if not candidates:
                return None

            candidates.sort(
                key=lambda task: self._rank_key(task, projects),
            )
            task = candidates[0]
            lease_id = str(uuid4())
            now = self.ledger.now_fn()
            expires = now + timedelta(seconds=self.lease_seconds)
            event = self.ledger.append(
                "task.assigned",
                task["task_id"],
                {
                    "status": "assigned",
                    "assigned_worker_id": worker_id,
                    "lease_id": lease_id,
                    "lease_expires_at": _iso(expires),
                    "assigned_at": _iso(now),
                },
                source="dispatcher",
                occurred_at=now,
            )
            return {
                "task_id": task["task_id"],
                "project_id": task.get("project_id"),
                "title": task.get("title"),
                "description": task.get("description"),
                "goal": task.get("goal"),
                "target": task.get("target"),
                "constraints": list(task.get("constraints") or []),
                "completion_cues": list(task.get("completion_cues") or []),
                "verification": list(task.get("verification") or []),
                "context": dict(task.get("context") or {}),
                "lease_id": lease_id,
                "lease_expires_at": _iso(expires),
                "assignment_event_id": event["event_id"],
            }

    def acknowledge(
        self,
        worker_id: str,
        task_id: str,
        lease_id: str,
        *,
        accepted: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        with self.ledger.lock:
            task = self._leased_task(worker_id, task_id, lease_id)
            payload = {
                "status": "running" if accepted else "queued",
                "acknowledged_at": _iso(self.ledger.now_fn()),
            }
            if not accepted:
                payload.update({
                    "assigned_worker_id": None,
                    "lease_id": None,
                    "lease_expires_at": None,
                    "rejection_reason": reason or "worker_rejected",
                })
            return self.ledger.append(
                "task.acknowledged",
                task["task_id"],
                payload,
                source=worker_id,
            )

    def complete(
        self,
        worker_id: str,
        task_id: str,
        lease_id: str,
        *,
        outcome: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.ledger.lock:
            task = self._leased_task(worker_id, task_id, lease_id)
            return self.ledger.append(
                "task.completed",
                task["task_id"],
                {
                    "status": "completed",
                    "completed_at": _iso(self.ledger.now_fn()),
                    "outcome": dict(outcome or {}),
                },
                source=worker_id,
            )

    def _leased_task(
        self,
        worker_id: str,
        task_id: str,
        lease_id: str,
    ) -> dict[str, Any]:
        snapshot = self.ledger.snapshot()
        task = next(
            (item for item in snapshot["tasks"] if item["task_id"] == task_id),
            None,
        )
        if not task:
            raise ValueError(f"Unknown task: {task_id}")
        if task.get("assigned_worker_id") != worker_id:
            raise ValueError("Task is assigned to a different worker")
        if task.get("lease_id") != lease_id:
            raise ValueError("Lease does not match")
        if task.get("lease_expired"):
            raise ValueError("Lease has expired")
        return task

    @staticmethod
    def _worker_can_run(worker: dict[str, Any], task: dict[str, Any]) -> bool:
        required = set(task.get("required_capabilities") or [])
        available = set(worker.get("capabilities") or [])
        return required.issubset(available)

    @staticmethod
    def _is_ready(task: dict[str, Any], all_tasks: list[dict[str, Any]]) -> bool:
        if task.get("status") not in DISPATCHABLE_STATES:
            return False
        completed = {
            candidate["task_id"]
            for candidate in all_tasks
            if candidate.get("status") == "completed"
        }
        dependencies = set(task.get("depends_on") or [])
        return dependencies.issubset(completed)

    @staticmethod
    def _rank_key(
        task: dict[str, Any],
        projects: dict[str, dict[str, Any]],
    ) -> tuple[Any, ...]:
        project = projects.get(task.get("project_id"), {})
        project_priority = int(project.get("priority", 0) or 0)
        task_priority = int(task.get("priority", 0) or 0)
        created = _parse_time(task.get("created_at"))
        created_key = created.timestamp() if created else float("inf")
        return (-project_priority, -task_priority, created_key, task["task_id"])


def derive_snapshot(
    events: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 15 * 60,
) -> dict[str, Any]:
    """Fold ledger events into the cockpit's current source of truth."""
    now = now or _utc_now()
    projects: dict[str, dict[str, Any]] = {}
    workers: dict[str, dict[str, Any]] = {}
    tasks: dict[str, dict[str, Any]] = {}
    event_count = 0

    # Ledger position is the authoritative sequence. Timestamps describe when an
    # observation occurred, but are not safe ordering keys: multiple events may
    # share a timestamp and remote clocks may disagree.
    for event in events:
        event_count += 1
        event_type = str(event.get("event_type") or "")
        subject_id = str(event.get("subject_id") or "")
        payload = dict(event.get("payload") or {})
        observed_at = event.get("occurred_at")

        if event_type.startswith("project."):
            record = projects.setdefault(
                subject_id,
                {"project_id": subject_id, "status": "queued", "progress": {}},
            )
            record.update(payload)
            record["last_observed_at"] = observed_at
        elif event_type.startswith("worker."):
            record = workers.setdefault(
                subject_id,
                {"worker_id": subject_id, "status": "unknown"},
            )
            record.update(payload)
            record["last_observed_at"] = observed_at
            if event_type == "worker.heartbeat" and "status" not in payload:
                record["status"] = "running"
        elif event_type.startswith("task."):
            record = tasks.setdefault(
                subject_id,
                {"task_id": subject_id, "status": "queued"},
            )
            record.update(payload)
            record["last_observed_at"] = observed_at

    for worker in workers.values():
        observed = _parse_time(worker.get("last_observed_at"))
        age = (now - observed).total_seconds() if observed else None
        worker["heartbeat_age_seconds"] = max(0, int(age)) if age is not None else None
        worker["stale"] = age is None or age > stale_after_seconds
        if worker["stale"] and worker.get("status") in {"running", "working", "online"}:
            worker["status"] = "stalled"

    for task in tasks.values():
        expires = _parse_time(task.get("lease_expires_at"))
        task["lease_expired"] = bool(
            task.get("status") in ASSIGNED_STATES
            and expires
            and expires <= now
        )
        if task["lease_expired"]:
            task["status"] = "queued"
            task["assigned_worker_id"] = None
            task["lease_id"] = None

    task_lists: dict[str, list[dict[str, Any]]] = {}
    worker_lists: dict[str, list[dict[str, Any]]] = {}
    for task in tasks.values():
        project_id = task.get("project_id")
        if project_id:
            task_lists.setdefault(str(project_id), []).append(task)
    for worker in workers.values():
        project_id = worker.get("project_id")
        if project_id:
            worker_lists.setdefault(str(project_id), []).append(worker)

    for project_id, project in projects.items():
        project_tasks = task_lists.get(project_id, [])
        project_workers = worker_lists.get(project_id, [])
        project["tasks"] = sorted(project_tasks, key=lambda task: task["task_id"])
        project["workers"] = sorted(project_workers, key=lambda worker: worker["worker_id"])
        project["progress"] = _calculate_progress(project, project_tasks)
        project["eta"] = _calculate_eta(project, now)
        project["blocked"] = (
            project.get("status") == "blocked"
            or any(task.get("status") == "blocked" for task in project_tasks)
        )
        project["stalled"] = (
            project.get("status") in ACTIVE_STATES
            and bool(project_workers)
            and all(worker.get("stale") for worker in project_workers)
        )
        project["confidence"] = _status_confidence(project, project_workers)

    project_values = sorted(projects.values(), key=lambda project: project["project_id"])
    task_values = sorted(tasks.values(), key=lambda task: task["task_id"])
    return {
        "projects": project_values,
        "workers": sorted(workers.values(), key=lambda worker: worker["worker_id"]),
        "tasks": task_values,
        "summary": {
            "project_count": len(project_values),
            "active_projects": sum(
                project.get("status") in ACTIVE_STATES for project in project_values
            ),
            "blocked_projects": sum(project.get("blocked", False) for project in project_values),
            "stalled_projects": sum(project.get("stalled", False) for project in project_values),
            "active_workers": sum(
                worker.get("status") in {"running", "working", "online"}
                and not worker.get("stale")
                for worker in workers.values()
            ),
            "ready_tasks": sum(
                task.get("status") in DISPATCHABLE_STATES
                for task in task_values
            ),
            "assigned_tasks": sum(
                task.get("status") in ASSIGNED_STATES
                and not task.get("lease_expired")
                for task in task_values
            ),
            "event_count": event_count,
        },
        "generated_at": _iso(now),
    }


def _calculate_progress(
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = sum(task.get("status") == "completed" for task in tasks)
    total = len(tasks)
    reported = project.get("progress")
    if isinstance(reported, dict):
        completed = int(reported.get("completed", completed) or 0)
        total = int(reported.get("total", total) or 0)
    fraction = min(1.0, completed / total) if total else None
    return {"completed": completed, "total": total, "fraction": fraction}


def _calculate_eta(project: dict[str, Any], now: datetime) -> dict[str, Any]:
    progress = project.get("progress") or {}
    completed = progress.get("completed") or 0
    total = progress.get("total") or 0
    explicit_low = project.get("eta_low_seconds")
    explicit_high = project.get("eta_high_seconds")
    if explicit_low is not None and explicit_high is not None:
        return {
            "low_seconds": max(0, int(explicit_low)),
            "high_seconds": max(0, int(explicit_high)),
            "basis": "worker_estimate",
        }

    started = _parse_time(project.get("started_at"))
    if not started or completed <= 0 or total <= completed:
        return {"low_seconds": None, "high_seconds": None, "basis": "insufficient_evidence"}

    elapsed = max(1.0, (now - started).total_seconds())
    remaining = total - completed
    expected = elapsed / completed * remaining
    return {
        "low_seconds": int(expected * 0.75),
        "high_seconds": int(expected * 1.5),
        "basis": "observed_throughput",
    }


def _status_confidence(
    project: dict[str, Any],
    workers: list[dict[str, Any]],
) -> str:
    has_progress = (project.get("progress") or {}).get("total", 0) > 0
    fresh_workers = [worker for worker in workers if not worker.get("stale")]
    if has_progress and fresh_workers:
        return "high"
    if has_progress or fresh_workers:
        return "medium"
    return "low"
