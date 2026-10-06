import asyncio
import json

from workshop import hive


def test_source_manifest_is_byte_stable_and_change_sensitive(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    path = root / "app.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    first_manifest, first_hash = hive._source_manifest(root)
    path.touch()
    second_manifest, second_hash = hive._source_manifest(root)
    assert first_manifest == second_manifest
    assert first_hash == second_hash
    path.write_text("VALUE = 2\n", encoding="utf-8")
    _, changed_hash = hive._source_manifest(root)
    assert changed_hash != first_hash


def test_run_records_experiment_provenance_and_ordered_call_ids(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    plan = {
        "summary": "No-op experiment fixture",
        "ui_goal": "no change needed", "backend_goal": "no change needed", "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": [], "tests": []},
        "acceptance": [], "worker_acceptance": {"ui": [], "backend": [], "tests": []},
    }
    experiment = {
        "study_id": "HWR-001", "condition_id": "hive", "task_id": "task-001",
        "replicate_index": 0, "trial_id": "HWR-001/hive/task-001/r0",
        "condition_spec_sha256": "a" * 64,
    }

    async def call(role, prompt):
        if role == "planner":
            return json.dumps(plan)
        return json.dumps({"approve": False, "summary": "no patch", "issues": [], "confidence": 1.0})

    run = asyncio.run(hive.run_build(
        root, tmp_path / "runs", "No-op", "model@digest", call,
        metadata={"experiment": experiment},
    ))

    provenance = run["provenance"]
    assert provenance["schema_version"] == 1
    assert provenance["experiment"] == experiment
    assert len(provenance["source_manifest_sha256"]) == 64
    assert provenance["model_policy"]["local_model"] == "model@digest"
    assert provenance["finished_at"] >= provenance["started_at"]
    ids = [item["call_id"] for item in run["prompt_trace"]]
    assert ids == [f"{run['id']}:call:0001", f"{run['id']}:call:0002"]
    assert all(item["wall_seconds"] >= 0 for item in run["prompt_trace"])
