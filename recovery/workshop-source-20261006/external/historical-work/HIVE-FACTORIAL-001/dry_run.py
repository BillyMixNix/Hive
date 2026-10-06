"""No-model exercise of the shared external-root/single-agent host path."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import runner


def main() -> int:
    runner.prior.no_cloud_key()
    ref = runner.prior.reference_freeze()
    runner.prior.approved_environment(ref)
    root = runner.HERE / "preflight-evidence" / "dry-run-runs"
    if root.exists():
        raise RuntimeError("dry-run evidence already exists; refusing overwrite")
    task = runner.task_specs()[0]
    run_id = uuid.uuid4().hex[:12]
    ext = runner.external_root.prepare_candidate(ref["baseline"]["root"],
        root / "external_candidates" / run_id, runner.prior.WORKSHOP, root)
    candidate = Path(ext["candidate_root"])
    ext["jvm_profile"] = runner.hive_jvm.inspect_gradle_project(candidate)
    frozen = runner.hive_jvm.freeze_junit_tests(candidate, [{
        "path": task["test_path"], "class_name": task["test_class"],
        "expected_cases": task["test_cases"],
        "source": (runner.HERE / "hidden-tests" / task["test_filename"]).read_text(encoding="utf-8"),
    }])
    ext["frozen_junit_tests"] = runner.hive_jvm.store_frozen_junit_tests(frozen, root / run_id)
    calls = []
    async def fake_call(role: str, prompt: str) -> str:
        calls.append(role)
        if role == "planner":
            return json.dumps(runner.single_plan(task))
        if role == "backend":
            return json.dumps({"status": "implemented", "summary": "dry-run no-op", "edits": []})
        if role == "reviewer":
            return json.dumps({"approve": False, "summary": "no proposal", "issues": [], "confidence": 0.0})
        raise RuntimeError("unexpected role " + role)
    run = asyncio.run(runner.hive.run_build(candidate, root, task["request"],
        "no-model", fake_call, metadata={"external_root": ext, "agent_calls": []},
        run_id=run_id, external_root_mode=True))
    runner.hive.save_run(root, run)
    assert run["plan_attempts"][0]["status"] == "accepted", run["plan_attempts"]
    assert "backend" in calls and "reviewer" in calls, calls
    assert run["verification"]["full_gate_skipped"] is True
    assert run["status"] == "rejected" and run["applied"] is False
    assert runner.external_root.tree_sha256(candidate) == ref["baseline"]["tree_sha256"]
    print("NO_MODEL_DRY_RUN_PASS", run_id, calls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
