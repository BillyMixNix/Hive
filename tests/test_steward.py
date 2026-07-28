from steward import build_steward_brief


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
