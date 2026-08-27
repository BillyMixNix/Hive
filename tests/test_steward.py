from datetime import datetime, timezone

import pytest

from orchestration import OrchestrationLedger
from steward import StewardController, build_steward_brief


NOW = datetime(2026, 7, 28, 23, 0, tzinfo=timezone.utc)


def task(task_id, project_id, status, **extra):
    return {
        "task_id": task_id,
        "project_id": project_id,
        "status": status,
        **extra,
    }


def project(project_id, **extra):
    return {
        "project_id": project_id,
        "name": extra.pop("name", project_id.replace("-", " ").title()),
        "status": "running",
        "tasks": [],
        "workers": [],
        **extra,
    }


def test_steward_surfaces_blocker_reviews_and_highest_leverage():
    tasks = [
        task(
            "fulcrum-lore",
            "fulcrum",
            "blocked",
            title="Resolve lore boundary",
            blocked_reason="waiting on lore",
        ),
        task(
            "inventory-api",
            "endless-fusion",
            "ready",
            title="Implement inventory API",
            priority=8,
        ),
        task("fusion-ui", "endless-fusion", "queued", depends_on=["inventory-api"]),
        task("loot-save", "endless-fusion", "queued", depends_on=["inventory-api"]),
        task("combat-loadout", "endless-fusion", "queued", depends_on=["inventory-api"]),
        task("world-drops", "endless-fusion", "queued", depends_on=["loot-save"]),
        task(
            "review-1",
            "endless-fusion",
            "completed",
            title="Fusion recipes",
            outcome={"tests": "passed"},
        ),
        task(
            "review-2",
            "endless-fusion",
            "completed",
            title="Inventory persistence",
            outcome={"tests": "passed"},
        ),
        task(
            "review-3",
            "endless-fusion",
            "review",
            title="Monster drops",
        ),
    ]
    snapshot = {
        "projects": [
            project("fulcrum", name="Fulcrum"),
            project("endless-fusion", name="Endless Fusion"),
        ],
        "tasks": tasks,
    }

    brief = build_steward_brief(snapshot)

    assert brief["primary_attention"]["task_id"] == "fulcrum-lore"
    assert "waiting on lore" in brief["primary_attention"]["message"]
    assert brief["summary"]["review_count"] == 3
    assert brief["highest_leverage"]["task_id"] == "inventory-api"
    assert brief["highest_leverage"]["evidence"]["downstream_count"] == 4


def test_steward_uses_transitive_dependencies_for_leverage():
    snapshot = {
        "projects": [project("hive")],
        "tasks": [
            task("foundation", "hive", "ready"),
            task("middle", "hive", "queued", depends_on=["foundation"]),
            task("leaf", "hive", "queued", depends_on=["middle"]),
        ],
    }
    brief = build_steward_brief(snapshot)
    assert brief["highest_leverage"]["task_id"] == "foundation"
    assert brief["highest_leverage"]["evidence"]["downstream_tasks"] == [
        "leaf",
        "middle",
    ]


def test_steward_detects_stalled_project_without_inventing_cause():
    snapshot = {
        "projects": [
            project(
                "fulcrum",
                stalled=True,
                workers=[{"worker_id": "codex-fulcrum", "stale": True}],
            )
        ],
        "tasks": [],
    }
    brief = build_steward_brief(snapshot)
    item = brief["primary_attention"]
    assert item["kind"] == "stalled"
    assert item["evidence"]["worker_ids"] == ["codex-fulcrum"]
    assert "restart" in item["recommended_action"].lower()


def test_steward_returns_calm_brief_when_nothing_needs_attention():
    brief = build_steward_brief({
        "projects": [project("hive", status="completed")],
        "tasks": [task("done", "hive", "completed", review_status="approved")],
    })
    assert brief["attention"] == []
    assert brief["primary_attention"] is None
    assert "No intervention" in brief["briefing"]


def test_review_approval_removes_item_from_review_queue():
    snapshot = {
        "projects": [project("hive")],
        "tasks": [
            task(
                "done",
                "hive",
                "completed",
                outcome={"tests": "passed"},
                review_status="approved",
            )
        ],
    }
    assert build_steward_brief(snapshot)["summary"]["review_count"] == 0


def decision_ledger(tmp_path, task_payload):
    ledger = OrchestrationLedger(
        tmp_path / "events.jsonl",
        now_fn=lambda: NOW,
    )
    ledger.append(
        "project.registered",
        task_payload["project_id"],
        {"name": "Hive", "status": "running"},
    )
    ledger.append("task.created", task_payload["task_id"], task_payload)
    return ledger


def test_approve_review_closes_review_loop(tmp_path):
    ledger = decision_ledger(tmp_path, task(
        "review-me",
        "hive",
        "completed",
        outcome={"tests": "passed"},
    ))
    controller = StewardController(ledger)
    event = controller.act("approve", task_id="review-me")

    assert event["event_type"] == "task.steward_decision"
    reviewed = ledger.snapshot()["tasks"][0]
    assert reviewed["review_status"] == "approved"
    assert build_steward_brief(ledger.snapshot(), now=NOW)["attention"] == []


def test_reject_review_returns_work_with_feedback(tmp_path):
    ledger = decision_ledger(tmp_path, task(
        "review-me",
        "hive",
        "review",
        outcome={"tests": "failed"},
    ))
    StewardController(ledger).act(
        "reject",
        task_id="review-me",
        note="The save migration is incomplete.",
    )
    rejected = ledger.snapshot()["tasks"][0]
    assert rejected["status"] == "queued"
    assert rejected["review_status"] == "changes_requested"
    assert rejected["rejection_reason"] == "The save migration is incomplete."


def test_defer_temporarily_removes_recommendation(tmp_path):
    ledger = decision_ledger(tmp_path, task(
        "later",
        "hive",
        "blocked",
        blocked_reason="waiting for user",
    ))
    StewardController(ledger).act(
        "defer",
        task_id="later",
        value=3600,
    )
    assert build_steward_brief(ledger.snapshot(), now=NOW)["attention"] == []


def test_reprioritize_changes_leverage_order(tmp_path):
    ledger = decision_ledger(tmp_path, task("first", "hive", "ready", priority=1))
    ledger.append("task.created", "second", task(
        "second", "hive", "ready", priority=2
    ))
    controller = StewardController(ledger)
    controller.act("reprioritize", task_id="first", value=50)
    brief = build_steward_brief(ledger.snapshot(), now=NOW)
    assert brief["highest_leverage"]["task_id"] == "first"


def test_supplied_context_is_merged_and_audited(tmp_path):
    ledger = decision_ledger(tmp_path, task(
        "blocked",
        "hive",
        "blocked",
        context={"worker": "known"},
    ))
    StewardController(ledger).act(
        "context",
        task_id="blocked",
        value="Use the permanent-inventory design law.",
    )
    updated = ledger.snapshot()["tasks"][0]
    assert updated["context"] == {
        "worker": "known",
        "user_supplied": "Use the permanent-inventory design law.",
    }
    assert updated["context_supplied"] is True


def test_invalid_steward_actions_fail_closed(tmp_path):
    ledger = decision_ledger(tmp_path, task("one", "hive", "ready"))
    controller = StewardController(ledger)
    with pytest.raises(ValueError, match="Unsupported"):
        controller.act("destroy", task_id="one")
    with pytest.raises(ValueError, match="exactly one"):
        controller.act("approve", task_id="one", project_id="hive")
    with pytest.raises(ValueError, match="between -100 and 100"):
        controller.act("reprioritize", task_id="one", value=1000)
