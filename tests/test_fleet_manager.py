import json

import pytest

from fleet_manager import ABSOLUTE_MAX_WORKERS, FleetSupervisor, WorkerSpec


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout=None):
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exit_code = -9


def spec(worker_id, **extra):
    return WorkerSpec(
        worker_id=worker_id,
        command=tuple(extra.pop("command", ["codex", "exec", "-"])),
        capabilities=tuple(extra.pop("capabilities", ["python"])),
        **extra,
    )


def test_fleet_enforces_three_worker_ceiling():
    workers = [spec(f"worker-{index}") for index in range(4)]
    with pytest.raises(ValueError, match="limit is 3"):
        FleetSupervisor(workers, reporter=lambda *_: None)
    with pytest.raises(ValueError, match="between 1 and 3"):
        FleetSupervisor(
            workers[:1],
            max_workers=ABSOLUTE_MAX_WORKERS + 1,
            reporter=lambda *_: None,
        )


def test_fleet_rejects_duplicate_worker_identity():
    with pytest.raises(ValueError, match="unique"):
        FleetSupervisor(
            [spec("codex"), spec("codex")],
            reporter=lambda *_: None,
        )


def test_worker_command_is_explicit_argv_without_shell(tmp_path):
    calls = []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeProcess()

    supervisor = FleetSupervisor(
        [spec(
            "endless-fusion",
            cwd=str(tmp_path),
            capabilities=("game-development", "python"),
        )],
        cockpit_url="http://hive.test",
        runner_script="/repo/worker_runner.py",
        python_executable="/python",
        popen=popen,
        reporter=lambda *_: None,
    )
    supervisor._launch(supervisor.workers["endless-fusion"])

    argv, kwargs = calls[0]
    assert argv[:4] == [
        "/python",
        "/repo/worker_runner.py",
        "--worker",
        "endless-fusion",
    ]
    assert argv[-4:] == ["--", "codex", "exec", "-"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["shell"] is False


def test_monitor_restarts_after_bounded_backoff():
    clock = [100.0]
    launched = []
    reports = []

    def popen(*args, **kwargs):
        process = FakeProcess()
        launched.append(process)
        return process

    supervisor = FleetSupervisor(
        [spec("codex")],
        restart_limit=2,
        restart_backoff_seconds=5,
        popen=popen,
        clock=lambda: clock[0],
        reporter=lambda event, payload: reports.append((event, payload)),
    )
    worker = supervisor.workers["codex"]
    supervisor._launch(worker)
    worker.process.exit_code = 7
    status = supervisor.monitor_once()

    assert status["running"] == 0
    assert worker.restart_count == 1
    assert worker.next_restart_at == 105.0
    assert any(event == "worker.runner_exited" for event, _ in reports)

    clock[0] = 104.0
    supervisor.monitor_once()
    assert len(launched) == 1
    clock[0] = 105.0
    supervisor.monitor_once()
    assert len(launched) == 2
    assert supervisor.status()["running"] == 1


def test_stop_terminates_workers_and_reports_offline():
    reports = []
    process = FakeProcess()
    supervisor = FleetSupervisor(
        [spec("codex")],
        popen=lambda *args, **kwargs: process,
        reporter=lambda event, payload: reports.append((event, payload)),
    )
    supervisor._launch(supervisor.workers["codex"])
    supervisor.stop()

    assert process.terminated is True
    assert reports[-1][0] == "worker.fleet_stopped"
    assert reports[-1][1]["status"] == "offline"


def test_config_loads_disabled_workers_without_consuming_capacity(tmp_path):
    config = tmp_path / "fleet.json"
    config.write_text(json.dumps({
        "max_workers": 1,
        "workers": [
            {
                "worker_id": "active",
                "command": ["codex", "exec", "-"],
                "capabilities": ["python", "python"],
            },
            {
                "worker_id": "parked",
                "command": ["codex", "exec", "-"],
                "enabled": False,
            },
        ],
    }), encoding="utf-8")

    supervisor = FleetSupervisor.from_config(
        config,
        reporter=lambda *_: None,
    )
    assert list(supervisor.workers) == ["active"]
    assert supervisor.workers["active"].spec.capabilities == ("python",)
