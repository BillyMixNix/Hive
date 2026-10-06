"""No-model validation of four frozen test inputs against an untouched candidate."""

from __future__ import annotations

import json
from pathlib import Path

import runner


def main() -> int:
    runner.prior.no_cloud_key()
    reference = runner.prior.reference_freeze()
    approved = runner.prior.approved_environment(reference)
    root = runner.HERE / "preflight-evidence"
    if root.exists():
        raise RuntimeError("preflight evidence already exists; refusing overwrite")
    runs = root / "runs"
    candidate_info = runner.external_root.prepare_candidate(
        reference["baseline"]["root"], runs / "external_candidates" / "preflight",
        runner.prior.WORKSHOP, runs,
    )
    candidate = Path(candidate_info["candidate_root"])
    profile = runner.hive_jvm.inspect_gradle_project(candidate)
    results = []
    for task in runner.task_specs():
        source = (runner.HERE / "hidden-tests" / task["test_filename"]).read_text(encoding="utf-8")
        frozen = runner.hive_jvm.freeze_junit_tests(candidate, [{
            "path": task["test_path"], "class_name": task["test_class"],
            "expected_cases": task["test_cases"], "source": source,
        }])
        items = runner.hive_jvm.store_frozen_junit_tests(frozen, runs / task["id"])
        report = runner.prior.hive_verifier.targeted_verify_isolated(
            candidate, [], external_root=True, frozen_junit_tests=items,
            expected_jvm_profile=profile,
            expected_external_baseline_sha256=approved["baseline_sha256"],
        )
        if runner.external_root.tree_sha256(candidate) != approved["baseline_sha256"]:
            raise RuntimeError("preflight verifier mutated candidate")
        result = {"task_id": task["id"], "passed": report.get("passed"), "report": report}
        results.append(result)
        runner.save_json(root / "baseline_red.json", results)
        print(task["id"], "passed=" + str(report.get("passed")), flush=True)
        if report.get("passed") is not False:
            raise RuntimeError(f"{task['id']} baseline was not red")
    if runner.external_root.tree_sha256(Path(candidate_info["baseline_root"])) != approved["baseline_sha256"]:
        raise RuntimeError("immutable baseline changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
