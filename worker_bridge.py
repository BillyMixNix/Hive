"""CLI bridge between Hive's cockpit and an external worker instance.

This module does not execute arbitrary task text. It transports a bounded work
packet, records worker presence, and returns evidence under a valid assignment
lease. The worker remains responsible for deciding how to perform the work.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import platform
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_COCKPIT_URL = "http://127.0.0.1:8765"


class BridgeError(RuntimeError):
    pass


@dataclass
class Assignment:
    task_id: str
    project_id: str | None
    lease_id: str
    lease_expires_at: str
    packet: dict[str, Any]

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "Assignment":
        return cls(
            task_id=payload["task_id"],
            project_id=payload.get("project_id"),
            lease_id=payload["lease_id"],
            lease_expires_at=payload["lease_expires_at"],
            packet=dict(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "lease_id": self.lease_id,
            "lease_expires_at": self.lease_expires_at,
            "packet": self.packet,
        }


class HiveWorkerClient:
    """Small dependency-free client for Hive's worker protocol."""

    def __init__(
        self,
        worker_id: str,
        *,
        cockpit_url: str = DEFAULT_COCKPIT_URL,
        timeout: float = 10,
        transport: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ):
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        self.worker_id = worker_id.strip()
        self.cockpit_url = cockpit_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or self._post

    def register(
        self,
        capabilities: list[str],
        *,
        max_concurrency: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        payload = {
            "status": "online",
            "capabilities": sorted(set(capabilities)),
            "max_concurrency": max_concurrency,
            "runtime": {
                "system": platform.system(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "metadata": dict(metadata or {}),
        }
        return self._event("worker.registered", payload)

    def heartbeat(
        self,
        *,
        status: str = "online",
        project_id: str | None = None,
        current_task_id: str | None = None,
    ) -> dict[str, Any]:
        return self._event(
            "worker.heartbeat",
            {
                "status": status,
                "project_id": project_id,
                "current_task_id": current_task_id,
            },
        )

    def claim(self) -> Assignment | None:
        result = self.transport(
            "/api/dispatch/claim",
            {"worker_id": self.worker_id},
        )
        payload = result.get("assignment")
        return Assignment.from_response(payload) if payload else None

    def acknowledge(
        self,
        assignment: Assignment,
        *,
        accepted: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self.transport(
            "/api/dispatch/acknowledge",
            {
                "worker_id": self.worker_id,
                "task_id": assignment.task_id,
                "lease_id": assignment.lease_id,
                "accepted": accepted,
                "reason": reason,
            },
        )

    def complete(
        self,
        assignment: Assignment,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        return self.transport(
            "/api/dispatch/complete",
            {
                "worker_id": self.worker_id,
                "task_id": assignment.task_id,
                "lease_id": assignment.lease_id,
                "outcome": outcome,
            },
        )

    def renew(self, assignment: Assignment) -> dict[str, Any]:
        result = self.transport(
            "/api/dispatch/renew",
            {
                "worker_id": self.worker_id,
                "task_id": assignment.task_id,
                "lease_id": assignment.lease_id,
            },
        )
        event_payload = ((result.get("event") or {}).get("payload") or {})
        if event_payload.get("lease_expires_at"):
            assignment.lease_expires_at = event_payload["lease_expires_at"]
            assignment.packet["lease_expires_at"] = assignment.lease_expires_at
        return result

    def fail(
        self,
        assignment: Assignment,
        *,
        error: str,
        outcome: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return self.transport(
            "/api/dispatch/fail",
            {
                "worker_id": self.worker_id,
                "task_id": assignment.task_id,
                "lease_id": assignment.lease_id,
                "error": error,
                "outcome": dict(outcome or {}),
                "retryable": retryable,
            },
        )

    def _event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.transport(
            "/api/orchestration/events",
            {
                "event_type": event_type,
                "subject_id": self.worker_id,
                "source": f"worker_bridge:{self.worker_id}",
                "payload": payload,
            },
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.cockpit_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except Exception:
                detail = str(exc)
            raise BridgeError(detail or str(exc)) from exc
        except URLError as exc:
            raise BridgeError(
                f"Cannot reach Hive cockpit at {self.cockpit_url}"
            ) from exc
        if not result.get("ok", False):
            raise BridgeError(result.get("error") or "Hive rejected the request")
        return result


class WorkerState:
    """Persist the currently held lease without storing credentials."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, assignment: Assignment) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(assignment.to_dict(), indent=2),
            encoding="utf-8",
        )

    def load(self) -> Assignment:
        if not self.path.exists():
            raise BridgeError(f"No assignment state at {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return Assignment(
            task_id=data["task_id"],
            project_id=data.get("project_id"),
            lease_id=data["lease_id"],
            lease_expires_at=data["lease_expires_at"],
            packet=dict(data.get("packet") or {}),
        )

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def _write_packet(path: Path, assignment: Assignment) -> None:
    packet = assignment.packet
    lines = [
        f"# Hive Assignment: {packet.get('title') or assignment.task_id}",
        "",
        f"- Task: `{assignment.task_id}`",
        f"- Project: `{assignment.project_id or 'unassigned'}`",
        f"- Lease expires: `{assignment.lease_expires_at}`",
        "",
        "## Goal",
        "",
        str(packet.get("goal") or packet.get("description") or "No goal supplied."),
        "",
        "## Constraints",
        "",
    ]
    constraints = packet.get("constraints") or []
    lines.extend(f"- {item}" for item in constraints)
    if not constraints:
        lines.append("- None reported.")
    lines.extend(["", "## Completion cues", ""])
    cues = packet.get("completion_cues") or []
    lines.extend(f"- {item}" for item in cues)
    if not cues:
        lines.append("- Worker must return concrete evidence of completion.")
    lines.extend(["", "## Verification", ""])
    checks = packet.get("verification") or []
    lines.extend(f"- {item}" for item in checks)
    if not checks:
        lines.append("- Report the checks actually performed.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect a worker to Hive")
    parser.add_argument("--worker", required=True, help="Stable worker identifier")
    parser.add_argument("--cockpit", default=DEFAULT_COCKPIT_URL)
    parser.add_argument(
        "--state",
        default=".hive/worker_assignment.json",
        help="Local file holding the active assignment lease",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register")
    register.add_argument("--capability", action="append", default=[])
    register.add_argument("--max-concurrency", type=int, default=1)

    subparsers.add_parser("heartbeat")
    claim = subparsers.add_parser("claim")
    claim.add_argument("--packet", default=".hive/assignment.md")

    reject = subparsers.add_parser("reject")
    reject.add_argument("--reason", required=True)

    complete = subparsers.add_parser("complete")
    complete.add_argument("--outcome", required=True, help="JSON outcome object or file")

    args = parser.parse_args()
    client = HiveWorkerClient(args.worker, cockpit_url=args.cockpit)
    state = WorkerState(args.state)

    if args.command == "register":
        result = client.register(
            args.capability,
            max_concurrency=args.max_concurrency,
        )
    elif args.command == "heartbeat":
        try:
            assignment = state.load()
        except BridgeError:
            assignment = None
        result = client.heartbeat(
            status="working" if assignment else "online",
            project_id=assignment.project_id if assignment else None,
            current_task_id=assignment.task_id if assignment else None,
        )
    elif args.command == "claim":
        assignment = client.claim()
        if assignment is None:
            result = {"ok": True, "assignment": None}
        else:
            client.acknowledge(assignment, accepted=True)
            state.save(assignment)
            packet_path = Path(args.packet)
            _write_packet(packet_path, assignment)
            result = {
                "ok": True,
                "assignment": assignment.to_dict(),
                "packet_path": str(packet_path),
            }
    elif args.command == "reject":
        assignment = state.load()
        result = client.acknowledge(
            assignment,
            accepted=False,
            reason=args.reason,
        )
        state.clear()
    else:
        assignment = state.load()
        outcome_path = Path(args.outcome)
        if outcome_path.exists():
            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        else:
            outcome = json.loads(args.outcome)
        if not isinstance(outcome, dict):
            raise BridgeError("outcome must be a JSON object")
        result = client.complete(assignment, outcome)
        state.clear()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
