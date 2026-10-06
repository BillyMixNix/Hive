from __future__ import annotations

import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

from .executor import execute
from .store import Store


class Supervisor:
    def __init__(self, store: Store):
        self.store = store
        self._health_lock = threading.Lock()
        self._serving = False
        self._consecutive_errors = 0
        self._last_error = None
        self._last_error_at = None
        self._last_activity_at = None
        self._pid = os.getpid()
        self._started_at = self._stamp()
        self._activity = "Starting supervisor"
        self._current_task = None
        self._last_completed_task_id = None
        self._recoveries = 0
        self._last_recovery_at = None

    @staticmethod
    def _stamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def health(self) -> dict:
        with self._health_lock:
            age = None
            if self._last_activity_at:
                age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(self._last_activity_at)).total_seconds())
            return {
                "alive": self._serving,
                "consecutive_errors": self._consecutive_errors,
                "last_error": self._last_error,
                "last_error_at": self._last_error_at,
                "last_activity_at": self._last_activity_at,
                "pid": self._pid,
                "started_at": self._started_at,
                "activity": self._activity,
                "current_task": dict(self._current_task) if self._current_task else None,
                "last_completed_task_id": self._last_completed_task_id,
                "recoveries": self._recoveries,
                "last_recovery_at": self._last_recovery_at,
                "heartbeat_age_seconds": age,
                "heartbeat_stale": bool(self._serving and (age is None or age > 5.0)),
            }

    def _set_activity(self, activity: str, *, current_task=None) -> None:
        with self._health_lock:
            self._activity = activity
            self._current_task = current_task
            self._last_activity_at = self._stamp()

    def _pulse(self) -> None:
        with self._health_lock:
            self._last_activity_at = self._stamp()

    def record_recovery(self, count: int) -> None:
        if count <= 0:
            return
        with self._health_lock:
            self._recoveries += count
            self._last_recovery_at = self._stamp()

    def _record_cycle(self, error: Exception | None = None) -> None:
        with self._health_lock:
            self._last_activity_at = self._stamp()
            if error is None:
                self._consecutive_errors = 0
            else:
                self._consecutive_errors += 1
                self._last_error = f"{type(error).__name__}: {error}"[-4_096:]
                self._last_error_at = self._last_activity_at

    def run_once(self) -> bool:
        ledger_ok, detail = self.store.verify_chain()
        if not ledger_ok:
            self._set_activity(f"Blocked - evidence ledger verification failed: {detail}")
            raise RuntimeError(f"evidence ledger verification failed: {detail}")
        recovered = self.store.recover()
        self.record_recovery(recovered)
        self._set_activity("Checking durable queue")
        task = self.store.claim_ready()
        if not task:
            self._set_activity("Idle - waiting for work")
            return False
        attempt = task["attempts"]
        self._set_activity(
            f"Executing {task['kind']} task {task['id']}",
            current_task={
                "id": task["id"],
                "goal": task["goal"],
                "kind": task["kind"],
                "attempt": attempt,
                "started_at": self._stamp(),
                "status": "RUNNING",
            },
        )
        recorded = False
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=lambda: self._heartbeat_until(heartbeat_stop),
            name=f"jarvis-heartbeat-{task['id']}", daemon=True,
        )
        heartbeat.start()
        try:
            if task["kind"] == "agent":
                task["payload"]["lessons"] = self.store.guidance(task["goal"])
                control_dir = self.store.path.parent / ".codex-control"
                task["_control_dir"] = str(control_dir)
                task["_protected_paths"] = [
                    str(self.store.path),
                    str(Path(__file__).resolve().parent.parent),
                    str(control_dir),
                ]
            result = execute(task)
        except Exception as exc:
            error = str(exc)
            if task["mutating"] and attempt < task["max_attempts"]:
                recorded = self.store.transition(
                    task["id"], "WAITING_APPROVAL", "TASK_REAPPROVAL_REQUIRED",
                    {"error": error, "reason": "mutation outcome may be partial"},
                    expected_status="RUNNING", expected_attempt=attempt,
                    error=error, approval="PENDING_RETRY", lease_until=None,
                    checkpoint={"stage": "retry_requires_approval", "attempt": attempt},
                ) is not None
            elif attempt < task["max_attempts"]:
                recorded = self.store.transition(
                    task["id"], "READY", "TASK_RETRY", {"error": error},
                    expected_status="RUNNING", expected_attempt=attempt,
                    error=error, lease_until=None,
                    checkpoint={"stage": "retry", "attempt": attempt},
                ) is not None
            else:
                recorded = self.store.transition(
                    task["id"], "FAILED", "TASK_FAILED", {"error": error},
                    expected_status="RUNNING", expected_attempt=attempt,
                    error=error, lease_until=None,
                    checkpoint={"stage": "terminal", "attempt": attempt},
                ) is not None
        else:
            recorded = self.store.transition(
                task["id"], "SUCCEEDED", "TASK_SUCCEEDED", result=result,
                expected_status="RUNNING", expected_attempt=attempt,
                error=None, lease_until=None,
                checkpoint={"stage": "terminal", "attempt": attempt},
            ) is not None
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
            with self._health_lock:
                if recorded:
                    self._last_completed_task_id = task["id"]
                    self._activity = f"Recorded outcome for task {task['id']}"
                else:
                    self._activity = f"Task {task['id']} outcome is uncertain; recovery required"
                self._current_task = None
        if not recorded:
            raise RuntimeError(f"task {task['id']} changed state before its outcome could be recorded")
        return True

    def _heartbeat_until(self, stop: threading.Event) -> None:
        while not stop.wait(1.0):
            self._pulse()

    def serve(self, poll_seconds: float = 1.0):
        with self._health_lock:
            self._serving = True
            self._activity = "Supervisor online - checking durable queue"
            self._last_activity_at = self._stamp()
        try:
            while True:
                try:
                    worked = self.run_once()
                    self._record_cycle()
                    if not worked:
                        time.sleep(poll_seconds)
                except Exception as exc:
                    self._record_cycle(exc)
                    delay = min(30.0, max(poll_seconds, poll_seconds * (2 ** min(5, self._consecutive_errors))))
                    time.sleep(delay)
        finally:
            with self._health_lock:
                self._serving = False
