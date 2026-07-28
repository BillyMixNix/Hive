from datetime import datetime, timedelta, timezone

from orchestration import Dispatcher, OrchestrationLedger, derive_snapshot


NOW = datetime(2026, 7, 28, 22, 0, tzinfo=timezone.utc)


def event(event_type, subject_id, payload=None, minutes_ago=0, event_id=None):
    return {
        "event_id": event_id or f"{event_type}:{subject_id}:{minutes_ago}",
        "event_type": event_type,
        "subject_id": subject_id,
        "source": "test",
        "occurred_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
        "payload": payload or {},
    }


def test_snapshot_joins_projects_tasks_and_workers():
    snapshot = derive_snapshot(
        [
            event("project.registered", "endless-fusion", {
                "name": "Endless Fusion",
                "status": "running",
                "started_at": (NOW - timedelta(hours=2)).isoformat(),
            }),
            event("task.updated", "ef-1", {
                "project_id": "endless-fusion",
                "title": "Persistent inventory",
                "status": "completed",
            }),
            event("task.updated", "ef-2", {
                "project_id": "endless-fusion",
                "title": "World exploration",
                "status": "running",
            }),
            event("worker.heartbeat", "codex-ef", {
                "project_id": "endless-fusion",
                "current_task_id": "ef-2",
            }),
        ],
        now=NOW,
    )

    project = snapshot["projects"][0]
    assert project["progress"] == {"completed": 1, "total": 2, "fraction": 0.5}
    assert project["eta"]["basis"] == "observed_throughput"
    assert project["eta"]["low_seconds"] == 5400
    assert project["eta"]["high_seconds"] == 10800
    assert project["confidence"] == "high"
    assert project["stalled"] is False
    assert snapshot["summary"]["active_workers"] == 1


def test_stale_worker_marks_active_project_stalled():
    snapshot = derive_snapshot(
        [
            event("project.registered", "fulcrum", {"status": "running"}),
            event(
                "worker.heartbeat",
                "codex-fulcrum",
                {"project_id": "fulcrum", "status": "working"},
                minutes_ago=31,
            ),
        ],
        now=NOW,
        stale_after_seconds=30 * 60,
    )

    assert snapshot["workers"][0]["status"] == "stalled"
    assert snapshot["projects"][0]["stalled"] is True
    assert snapshot["summary"]["stalled_projects"] == 1


def test_eta_refuses_to_invent_precision_without_evidence():
    snapshot = derive_snapshot(
        [event("project.registered", "hive", {"status": "running"})],
        now=NOW,
    )

    assert snapshot["projects"][0]["eta"] == {
        "low_seconds": None,
        "high_seconds": None,
        "basis": "insufficient_evidence",
    }
    assert snapshot["projects"][0]["confidence"] == "low"


def test_explicit_eta_is_preserved_as_a_range():
    snapshot = derive_snapshot(
        [
            event("project.updated", "hive", {
                "status": "running",
                "eta_low_seconds": 1200,
                "eta_high_seconds": 3600,
            })
        ],
        now=NOW,
    )

    assert snapshot["projects"][0]["eta"] == {
        "low_seconds": 1200,
        "high_seconds": 3600,
        "basis": "worker_estimate",
    }


def test_ledger_is_append_only_and_deduplicates_event_ids(tmp_path):
    clock = lambda: NOW
    ledger = OrchestrationLedger(tmp_path / "events.jsonl", now_fn=clock)
    ledger.append(
        "project.registered",
        "hive",
        {"status": "running"},
        event_id="same-event",
    )
    ledger.append(
        "project.updated",
        "hive",
        {"status": "completed"},
        event_id="same-event",
    )

    snapshot = ledger.snapshot()
    assert snapshot["summary"]["event_count"] == 1
    assert snapshot["projects"][0]["status"] == "running"


def build_dispatch_ledger(tmp_path, events):
    ledger = OrchestrationLedger(tmp_path / "events.jsonl", now_fn=lambda: NOW)
    for item in events:
        ledger.append(
            item["event_type"],
            item["subject_id"],
            item.get("payload"),
            event_id=item["event_id"],
            occurred_at=item["occurred_at"],
            source="test",
        )
    return ledger


def test_dispatch_matches_capability_and_priority(tmp_path):
    ledger = build_dispatch_ledger(tmp_path, [
        event("project.registered", "low", {"status": "running", "priority": 1}),
        event("project.registered", "high", {"status": "running", "priority": 10}),
        event("worker.heartbeat", "coder", {
            "status": "online",
            "capabilities": ["python", "tests"],
        }),
        event("task.created", "wrong-skill", {
            "project_id": "high",
            "status": "queued",
            "priority": 99,
            "required_capabilities": ["finance"],
        }),
        event("task.created", "low-project", {
            "project_id": "low",
            "status": "queued",
            "priority": 99,
            "required_capabilities": ["python"],
        }),
        event("task.created", "right-task", {
            "project_id": "high",
            "status": "queued",
            "priority": 2,
            "required_capabilities": ["python", "tests"],
        }),
    ])

    assignment = Dispatcher(ledger, lease_seconds=300).claim("coder")
    assert assignment["task_id"] == "right-task"
    task = next(
        task for task in ledger.snapshot()["tasks"]
        if task["task_id"] == "right-task"
    )
    assert task["status"] == "assigned"
    assert task["assigned_worker_id"] == "coder"


def test_dispatch_waits_for_dependencies(tmp_path):
    ledger = build_dispatch_ledger(tmp_path, [
        event("project.registered", "hive", {"status": "running"}),
        event("worker.heartbeat", "coder", {"status": "online"}),
        event("task.created", "foundation", {
            "project_id": "hive",
            "status": "running",
        }),
        event("task.created", "command", {
            "project_id": "hive",
            "status": "queued",
            "depends_on": ["foundation"],
        }),
    ])

    assert Dispatcher(ledger).claim("coder") is None
    ledger.append("task.completed", "foundation", {"status": "completed"})
    assert Dispatcher(ledger).claim("coder")["task_id"] == "command"


def test_dispatch_respects_capacity_and_reclaims_expired_lease(tmp_path):
    ledger = build_dispatch_ledger(tmp_path, [
        event("project.registered", "hive", {"status": "running"}),
        event("worker.heartbeat", "coder", {
            "status": "online",
            "max_concurrency": 1,
        }),
        event("task.created", "first", {
            "project_id": "hive",
            "status": "assigned",
            "assigned_worker_id": "coder",
            "lease_id": "old",
            "lease_expires_at": (NOW - timedelta(seconds=1)).isoformat(),
        }),
        event("task.created", "second", {
            "project_id": "hive",
            "status": "queued",
        }),
    ])

    snapshot = ledger.snapshot()
    first = next(task for task in snapshot["tasks"] if task["task_id"] == "first")
    assert first["lease_expired"] is True
    assert first["status"] == "queued"
    assignment = Dispatcher(ledger).claim("coder")
    assert assignment["task_id"] == "first"


def test_acknowledge_and_complete_require_matching_lease(tmp_path):
    ledger = build_dispatch_ledger(tmp_path, [
        event("project.registered", "hive", {"status": "running"}),
        event("worker.heartbeat", "coder", {"status": "online"}),
        event("task.created", "command", {
            "project_id": "hive",
            "status": "queued",
        }),
    ])
    dispatcher = Dispatcher(ledger, lease_seconds=300)
    assignment = dispatcher.claim("coder")

    try:
        dispatcher.acknowledge("coder", "command", "wrong", accepted=True)
    except ValueError as exc:
        assert "Lease does not match" in str(exc)
    else:
        raise AssertionError("mismatched lease was accepted")

    dispatcher.acknowledge(
        "coder", "command", assignment["lease_id"], accepted=True
    )
    dispatcher.complete(
        "coder",
        "command",
        assignment["lease_id"],
        outcome={"tests": "passed"},
    )
    task = ledger.snapshot()["tasks"][0]
    assert task["status"] == "completed"
    assert task["outcome"] == {"tests": "passed"}


def test_renew_extends_lease_and_failure_releases_worker(tmp_path):
    ledger = build_dispatch_ledger(tmp_path, [
        event("project.registered", "hive", {"status": "running"}),
        event("worker.heartbeat", "coder", {"status": "online"}),
        event("task.created", "command", {
            "project_id": "hive",
            "status": "queued",
        }),
    ])
    dispatcher = Dispatcher(ledger, lease_seconds=300)
    assignment = dispatcher.claim("coder")
    dispatcher.acknowledge(
        "coder", "command", assignment["lease_id"], accepted=True
    )
    renewed = dispatcher.renew("coder", "command", assignment["lease_id"])
    assert renewed["event_type"] == "task.lease_renewed"
    assert renewed["payload"]["lease_expires_at"] == assignment["lease_expires_at"]

    dispatcher.fail(
        "coder",
        "command",
        assignment["lease_id"],
        error="command exited with 2",
        outcome={"exit_code": 2},
    )
    task = ledger.snapshot()["tasks"][0]
    assert task["status"] == "blocked"
    assert task["assigned_worker_id"] is None
    assert task["failure_error"] == "command exited with 2"


def test_retryable_failure_returns_task_to_queue(tmp_path):
    ledger = build_dispatch_ledger(tmp_path, [
        event("project.registered", "hive", {"status": "running"}),
        event("worker.heartbeat", "coder", {"status": "online"}),
        event("task.created", "command", {
            "project_id": "hive",
            "status": "queued",
        }),
    ])
    dispatcher = Dispatcher(ledger)
    assignment = dispatcher.claim("coder")
    dispatcher.fail(
        "coder",
        "command",
        assignment["lease_id"],
        error="temporary failure",
        retryable=True,
    )
    assert ledger.snapshot()["tasks"][0]["status"] == "queued"
