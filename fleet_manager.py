"""The Marshal: supervise a bounded fleet of persistent Hive workers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Sequence

from worker_bridge import DEFAULT_COCKPIT_URL, HiveWorkerClient


ABSOLUTE_MAX_WORKERS = 3


@dataclass(frozen=True)
class WorkerSpec:
    worker_id: str
    command: tuple[str, ...]
    capabilities: tuple[str, ...] = ()
    cwd: str | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkerSpec":
        worker_id = str(value.get("worker_id") or "").strip()
        command = value.get("command")
        if not worker_id:
            raise ValueError("fleet worker_id is required")
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise ValueError(f"worker {worker_id} requires a non-empty command argv")
        capabilities = value.get("capabilities") or []
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item for item in capabilities
        ):
            raise ValueError(f"worker {worker_id} capabilities must be strings")
        return cls(
            worker_id=worker_id,
            command=tuple(command),
            capabilities=tuple(sorted(set(capabilities))),
            cwd=str(value["cwd"]) if value.get("cwd") else None,
            enabled=bool(value.get("enabled", True)),
        )


@dataclass
class WorkerProcess:
    spec: WorkerSpec
    process: subprocess.Popen[Any] | None = None
    restart_count: int = 0
    next_restart_at: float = 0
    last_exit_code: int | None = None


class FleetSupervisor:
    def __init__(
        self,
        specs: Sequence[WorkerSpec],
        *,
        cockpit_url: str = DEFAULT_COCKPIT_URL,
        max_workers: int = ABSOLUTE_MAX_WORKERS,
        restart_limit: int = 3,
        restart_backoff_seconds: float = 5,
        poll_seconds: float = 2,
        runner_script: str | Path | None = None,
        python_executable: str = sys.executable,
        popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        reporter: Callable[[str, dict[str, Any]], Any] | None = None,
    ):
        if max_workers < 1 or max_workers > ABSOLUTE_MAX_WORKERS:
            raise ValueError(
                f"max_workers must be between 1 and {ABSOLUTE_MAX_WORKERS}"
            )
        enabled = [spec for spec in specs if spec.enabled]
        if len(enabled) > max_workers:
            raise ValueError(
                f"fleet has {len(enabled)} enabled workers but limit is {max_workers}"
            )
        ids = [spec.worker_id for spec in specs]
        if len(ids) != len(set(ids)):
            raise ValueError("fleet worker_id values must be unique")
        if restart_limit < 0 or restart_backoff_seconds < 0 or poll_seconds <= 0:
            raise ValueError("invalid fleet restart or polling policy")

        self.cockpit_url = cockpit_url
        self.max_workers = max_workers
        self.restart_limit = restart_limit
        self.restart_backoff_seconds = restart_backoff_seconds
        self.poll_seconds = poll_seconds
        self.runner_script = str(
            runner_script or Path(__file__).with_name("worker_runner.py")
        )
        self.python_executable = python_executable
        self.popen = popen
        self.clock = clock
        self.sleep = sleep
        self.reporter = reporter or self._default_reporter()
        self.workers = {
            spec.worker_id: WorkerProcess(spec)
            for spec in enabled
        }
        self.stopping = False

    @classmethod
    def from_config(
        cls,
        path: str | Path,
        **kwargs: Any,
    ) -> "FleetSupervisor":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("workers"), list):
            raise ValueError("fleet config must contain a workers list")
        specs = [WorkerSpec.from_dict(item) for item in data["workers"]]
        return cls(
            specs,
            max_workers=int(data.get("max_workers", ABSOLUTE_MAX_WORKERS)),
            restart_limit=int(data.get("restart_limit", 3)),
            restart_backoff_seconds=float(data.get("restart_backoff_seconds", 5)),
            poll_seconds=float(data.get("poll_seconds", 2)),
            **kwargs,
        )

    def start(self) -> None:
        self._report("worker.fleet_started", {
            "status": "online",
            "fleet": self.status(),
        })
        for worker in self.workers.values():
            self._launch(worker)
        try:
            while not self.stopping:
                self.monitor_once()
                self.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def monitor_once(self) -> dict[str, Any]:
        now = self.clock()
        for worker in self.workers.values():
            if worker.process is None:
                if (
                    worker.restart_count <= self.restart_limit
                    and now >= worker.next_restart_at
                    and not self.stopping
                ):
                    self._launch(worker)
                continue
            exit_code = worker.process.poll()
            if exit_code is None:
                continue
            worker.last_exit_code = exit_code
            worker.process = None
            worker.restart_count += 1
            worker.next_restart_at = (
                now + self.restart_backoff_seconds * worker.restart_count
            )
            self._report("worker.runner_exited", {
                "status": "degraded",
                "worker_id": worker.spec.worker_id,
                "exit_code": exit_code,
                "restart_count": worker.restart_count,
                "restart_scheduled": worker.restart_count <= self.restart_limit,
                "fleet": self.status(),
            })
        status = self.status()
        self._report("worker.fleet_status", {
            "status": "online" if status["running"] else "degraded",
            "fleet": status,
        })
        return status

    def stop(self) -> None:
        if self.stopping and not any(
            worker.process is not None for worker in self.workers.values()
        ):
            return
        self.stopping = True
        for worker in self.workers.values():
            process = worker.process
            if process is None or process.poll() is not None:
                worker.process = None
                continue
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            worker.process = None
        self._report("worker.fleet_stopped", {
            "status": "offline",
            "fleet": self.status(),
        })

    def status(self) -> dict[str, Any]:
        entries = []
        for worker in self.workers.values():
            running = worker.process is not None and worker.process.poll() is None
            entries.append({
                "worker_id": worker.spec.worker_id,
                "running": running,
                "restart_count": worker.restart_count,
                "last_exit_code": worker.last_exit_code,
                "capabilities": list(worker.spec.capabilities),
                "cwd": worker.spec.cwd,
            })
        return {
            "limit": self.max_workers,
            "configured": len(entries),
            "running": sum(item["running"] for item in entries),
            "workers": entries,
        }

    def _launch(self, worker: WorkerProcess) -> None:
        argv = self._runner_argv(worker.spec)
        worker.process = self.popen(
            argv,
            cwd=worker.spec.cwd,
            shell=False,
        )
        self._report("worker.runner_started", {
            "status": "online",
            "worker_id": worker.spec.worker_id,
            "restart_count": worker.restart_count,
            "fleet": self.status(),
        })

    def _runner_argv(self, spec: WorkerSpec) -> list[str]:
        worker_root = Path(".hive") / "workers" / spec.worker_id
        argv = [
            self.python_executable,
            self.runner_script,
            "--worker", spec.worker_id,
            "--cockpit", self.cockpit_url,
            "--state", str(worker_root / "assignment.json"),
            "--packet", str(worker_root / "assignment.md"),
        ]
        if spec.cwd:
            argv.extend(["--cwd", spec.cwd])
        for capability in spec.capabilities:
            argv.extend(["--capability", capability])
        argv.append("--")
        argv.extend(spec.command)
        return argv

    def _default_reporter(self) -> Callable[[str, dict[str, Any]], Any]:
        client = HiveWorkerClient(
            "marshal",
            cockpit_url=self.cockpit_url,
        )
        return client.report_event

    def _report(self, event_type: str, payload: dict[str, Any]) -> None:
        self.reporter(event_type, payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supervise up to three persistent Hive workers"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--cockpit", default=DEFAULT_COCKPIT_URL)
    args = parser.parse_args()
    FleetSupervisor.from_config(
        args.config,
        cockpit_url=args.cockpit,
    ).start()


if __name__ == "__main__":
    main()
