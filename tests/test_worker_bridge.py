import json

from worker_bridge import Assignment, HiveWorkerClient, WorkerState, _write_packet


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.assignment = {
            "task_id": "hive-command",
            "project_id": "hive",
            "title": "Build command layer",
            "goal": "Connect Hive to a worker.",
            "constraints": ["Preserve audit history."],
            "completion_cues": ["Worker reports evidence."],
            "verification": ["Run focused tests."],
            "lease_id": "lease-1",
            "lease_expires_at": "2026-07-28T23:00:00+00:00",
            "assignment_event_id": "event-1",
        }

    def __call__(self, path, payload):
        self.calls.append((path, payload))
        if path == "/api/dispatch/claim":
            return {"ok": True, "assignment": self.assignment}
        return {"ok": True, "event": {"payload": payload}}


def test_worker_lifecycle_uses_same_identity_and_lease():
    transport = FakeTransport()
    client = HiveWorkerClient("codex-hive", transport=transport)
    client.register(["python", "tests"])
    assignment = client.claim()
    client.acknowledge(assignment, accepted=True)
    client.heartbeat(
        status="working",
        project_id=assignment.project_id,
        current_task_id=assignment.task_id,
    )
    client.complete(assignment, {"tests": "passed"})

    assert transport.calls[0][1]["subject_id"] == "codex-hive"
    assert transport.calls[1] == (
        "/api/dispatch/claim",
        {"worker_id": "codex-hive"},
    )
    for path, payload in (transport.calls[2], transport.calls[4]):
        assert payload["worker_id"] == "codex-hive"
        assert payload["task_id"] == "hive-command"
        assert payload["lease_id"] == "lease-1"


def test_worker_state_round_trip_and_clear(tmp_path):
    assignment = Assignment.from_response(FakeTransport().assignment)
    state = WorkerState(tmp_path / "worker.json")
    state.save(assignment)
    loaded = state.load()
    assert loaded.to_dict() == assignment.to_dict()
    state.clear()
    assert not state.path.exists()


def test_packet_materializes_worker_contract(tmp_path):
    assignment = Assignment.from_response(FakeTransport().assignment)
    target = tmp_path / "assignment.md"
    _write_packet(target, assignment)
    text = target.read_text(encoding="utf-8")
    assert "Connect Hive to a worker." in text
    assert "Preserve audit history." in text
    assert "Worker reports evidence." in text
    assert "Run focused tests." in text


def test_registration_normalizes_capabilities():
    transport = FakeTransport()
    client = HiveWorkerClient("codex", transport=transport)
    client.register(["tests", "python", "tests"], max_concurrency=2)
    payload = transport.calls[0][1]["payload"]
    assert payload["capabilities"] == ["python", "tests"]
    assert payload["max_concurrency"] == 2


def test_renew_updates_assignment_expiry_and_failure_reports_lease():
    transport = FakeTransport()
    original = transport.__call__

    def with_renewal(path, payload):
        if path == "/api/dispatch/renew":
            transport.calls.append((path, payload))
            return {
                "ok": True,
                "event": {
                    "payload": {
                        "lease_expires_at": "2026-07-29T00:00:00+00:00"
                    }
                },
            }
        return original(path, payload)

    client = HiveWorkerClient("codex", transport=with_renewal)
    assignment = client.claim()
    client.renew(assignment)
    client.fail(
        assignment,
        error="worker failed",
        outcome={"exit_code": 1},
        retryable=False,
    )

    assert assignment.lease_expires_at == "2026-07-29T00:00:00+00:00"
    failure_path, failure_payload = transport.calls[-1]
    assert failure_path == "/api/dispatch/fail"
    assert failure_payload["lease_id"] == "lease-1"
    assert failure_payload["retryable"] is False


def test_report_event_is_limited_to_worker_namespace():
    transport = FakeTransport()
    client = HiveWorkerClient("marshal", transport=transport)
    client.report_event("worker.fleet_status", {"status": "online"})
    assert transport.calls[-1][1]["event_type"] == "worker.fleet_status"

    try:
        client.report_event("task.created", {})
    except ValueError as exc:
        assert "worker event type" in str(exc)
    else:
        raise AssertionError("non-worker event was accepted")
