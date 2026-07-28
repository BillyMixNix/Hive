import subprocess

from worker_bridge import HiveWorkerClient, WorkerState
from worker_runner import WorkerRunner


class RunnerTransport:
    def __init__(self):
        self.calls = []
        self.claimed = False

    def __call__(self, path, payload):
        self.calls.append((path, payload))
        if path == "/api/dispatch/claim":
            if self.claimed:
                return {"ok": True, "assignment": None}
            self.claimed = True
            return {
                "ok": True,
                "assignment": {
                    "task_id": "task-1",
                    "project_id": "hive",
                    "title": "Build the runner",
                    "goal": "Execute one bounded assignment.",
                    "constraints": ["Do not use a shell."],
                    "completion_cues": ["Return exit evidence."],
                    "verification": ["Run tests."],
                    "lease_id": "lease-1",
                    "lease_expires_at": "2026-07-29T00:00:00+00:00",
                },
            }
        if path == "/api/dispatch/renew":
            return {
                "ok": True,
                "event": {
                    "payload": {
                        "lease_expires_at": "2026-07-29T00:20:00+00:00"
                    }
                },
            }
        return {"ok": True, "event": {"payload": payload}}


class ImmediateProcess:
    returncode = 0

    def communicate(self, input=None, timeout=None):
        assert "Execute one bounded assignment." in input
        return "worker output", ""


class RenewingProcess:
    returncode = 7

    def __init__(self):
        self.calls = 0

    def communicate(self, input=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired(["worker"], timeout)
        assert input is None
        return "", "worker error"


def _runner(tmp_path, process, *, retry_failures=False):
    transport = RunnerTransport()
    runner = WorkerRunner(
        HiveWorkerClient("codex-hive", transport=transport),
        ["codex", "exec", "-"],
        capabilities=["python", "tests"],
        state=WorkerState(tmp_path / "state.json"),
        packet_path=tmp_path / "assignment.md",
        heartbeat_seconds=1,
        retry_failures=retry_failures,
        popen=lambda *args, **kwargs: process,
    )
    return runner, transport


def test_runner_executes_explicit_argv_and_completes(tmp_path):
    runner, transport = _runner(tmp_path, ImmediateProcess())
    results = runner.start(once=True)

    assert results[0]["outcome"]["status"] == "succeeded"
    assert results[0]["outcome"]["stdout"] == "worker output"
    assert any(path == "/api/dispatch/complete" for path, _ in transport.calls)
    assert not runner.state.path.exists()


def test_runner_renews_during_long_work_and_reports_failure(tmp_path):
    runner, transport = _runner(tmp_path, RenewingProcess())
    results = runner.start(once=True)

    assert results[0]["outcome"]["exit_code"] == 7
    paths = [path for path, _ in transport.calls]
    assert "/api/dispatch/renew" in paths
    assert "/api/dispatch/fail" in paths
    failure = next(payload for path, payload in transport.calls if path == "/api/dispatch/fail")
    assert failure["retryable"] is False


def test_runner_never_uses_shell(tmp_path):
    captured = {}

    def popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return ImmediateProcess()

    runner, _ = _runner(tmp_path, ImmediateProcess())
    runner.popen = popen
    runner.start(once=True)

    assert captured["command"] == ["codex", "exec", "-"]
    assert captured["shell"] is False
