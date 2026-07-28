"""Persistent, lease-aware command runner for Hive workers.

Only the operator-supplied command is executed. Assignment fields are rendered
as text and sent over stdin; they are never interpreted as shell syntax.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Sequence

from worker_bridge import (
    DEFAULT_COCKPIT_URL,
    Assignment,
    BridgeError,
    HiveWorkerClient,
    WorkerState,
    _write_packet,
)


MAX_CAPTURE_CHARS = 20_000


class WorkerRunner:
    def __init__(
        self,
        client: HiveWorkerClient,
        command: Sequence[str],
        *,
        capabilities: Sequence[str],
        state: WorkerState,
        packet_path: str | Path = ".hive/assignment.md",
        cwd: str | Path | None = None,
        heartbeat_seconds: float = 30,
        poll_seconds: float = 10,
        retry_failures: bool = False,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not command:
            raise ValueError("worker command is required")
        if heartbeat_seconds <= 0 or poll_seconds < 0:
            raise ValueError("runner intervals must be non-negative")
        self.client = client
        self.command = list(command)
        self.capabilities = list(capabilities)
        self.state = state
        self.packet_path = Path(packet_path)
        self.cwd = str(cwd) if cwd else None
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self.retry_failures = retry_failures
        self.popen = popen
        self.sleep = sleep

    def start(self, *, once: bool = False) -> list[dict[str, Any]]:
        self.client.register(self.capabilities, max_concurrency=1, metadata={
            "runner": "worker_runner",
            "command": self.command[0],
        })
        results = []
        while True:
            result = self.run_once()
            if result is not None:
                results.append(result)
            if once:
                return results
            self.sleep(self.poll_seconds)

    def run_once(self) -> dict[str, Any] | None:
        self.client.heartbeat(status="online")
        assignment = self.client.claim()
        if assignment is None:
            return None

        self.client.acknowledge(assignment, accepted=True)
        self.state.save(assignment)
        _write_packet(self.packet_path, assignment)
        prompt = self.packet_path.read_text(encoding="utf-8")
        started = time.monotonic()

        try:
            completed = self._execute(assignment, prompt)
            duration = round(time.monotonic() - started, 3)
            outcome = {
                "status": "succeeded" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
                "duration_seconds": duration,
                "stdout": _bounded(completed.stdout),
                "stderr": _bounded(completed.stderr),
                "command": self.command[0],
            }
            if completed.returncode == 0:
                self.client.complete(assignment, outcome)
            else:
                self.client.fail(
                    assignment,
                    error=f"worker command exited with {completed.returncode}",
                    outcome=outcome,
                    retryable=self.retry_failures,
                )
            return {"assignment": assignment.to_dict(), "outcome": outcome}
        except Exception as exc:
            outcome = {
                "status": "failed",
                "duration_seconds": round(time.monotonic() - started, 3),
                "error_type": type(exc).__name__,
            }
            try:
                self.client.fail(
                    assignment,
                    error=str(exc),
                    outcome=outcome,
                    retryable=self.retry_failures,
                )
            except BridgeError:
                pass
            raise
        finally:
            self.state.clear()

    def _execute(
        self,
        assignment: Assignment,
        prompt: str,
    ) -> subprocess.CompletedProcess[str]:
        process = self.popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        first_wait = True
        while True:
            try:
                stdout, stderr = process.communicate(
                    input=prompt if first_wait else None,
                    timeout=self.heartbeat_seconds,
                )
                return subprocess.CompletedProcess(
                    self.command,
                    process.returncode,
                    stdout,
                    stderr,
                )
            except subprocess.TimeoutExpired:
                first_wait = False
                self.client.heartbeat(
                    status="working",
                    project_id=assignment.project_id,
                    current_task_id=assignment.task_id,
                )
                self.client.renew(assignment)
                self.state.save(assignment)


def _bounded(value: str | None) -> str:
    value = value or ""
    if len(value) <= MAX_CAPTURE_CHARS:
        return value
    return value[:MAX_CAPTURE_CHARS] + "\n[output truncated by Hive]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a persistent command-backed Hive worker"
    )
    parser.add_argument("--worker", required=True)
    parser.add_argument("--cockpit", default=DEFAULT_COCKPIT_URL)
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--state", default=".hive/worker_assignment.json")
    parser.add_argument("--packet", default=".hive/assignment.md")
    parser.add_argument("--cwd")
    parser.add_argument("--heartbeat-seconds", type=float, default=30)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Explicit worker command after --, for example: -- codex exec -",
    )
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    runner = WorkerRunner(
        HiveWorkerClient(args.worker, cockpit_url=args.cockpit),
        command,
        capabilities=args.capability,
        state=WorkerState(args.state),
        packet_path=args.packet,
        cwd=args.cwd,
        heartbeat_seconds=args.heartbeat_seconds,
        poll_seconds=args.poll_seconds,
        retry_failures=args.retry_failures,
    )
    print(json.dumps(runner.start(once=args.once), indent=2))


if __name__ == "__main__":
    main()
