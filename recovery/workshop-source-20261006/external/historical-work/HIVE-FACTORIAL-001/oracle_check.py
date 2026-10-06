"""No-model solvability check on a disposable reference candidate, never baseline."""

from __future__ import annotations

from pathlib import Path

import runner


def main() -> int:
    runner.prior.no_cloud_key()
    ref = runner.prior.reference_freeze()
    approved = runner.prior.approved_environment(ref)
    root = runner.HERE / "preflight-evidence" / "oracle-runs"
    candidate = root / "external_candidates" / "oracle"
    if not candidate.is_dir():
        raise RuntimeError("disposable oracle candidate missing")
    profile = runner.hive_jvm.inspect_gradle_project(candidate)
    specs = []
    for task in runner.task_specs():
        source_path = runner.HERE / "hidden-tests" / task["test_filename"]
        if runner.sha(source_path) != task["test_sha256"]:
            raise RuntimeError("test changed during oracle check")
        specs.append({"path": task["test_path"], "class_name": task["test_class"],
                      "expected_cases": task["test_cases"],
                      "source": source_path.read_text(encoding="utf-8")})
    frozen = runner.hive_jvm.freeze_junit_tests(candidate, specs)
    stored = runner.hive_jvm.store_frozen_junit_tests(frozen, root / "oracle-frozen")
    source_before = runner.external_root.tree_sha256(candidate)
    targeted = runner.prior.hive_verifier.targeted_verify_isolated(candidate, [],
        external_root=True, frozen_junit_tests=stored, expected_jvm_profile=profile,
        expected_external_baseline_sha256=approved["baseline_sha256"])
    runner.save_json(root / "oracle-targeted.json", targeted)
    if targeted.get("passed") is not True:
        raise RuntimeError("oracle candidate did not pass all hidden targeted tests")
    full = runner.prior.hive_verifier.verify_tree_isolated(candidate,
        external_root=True, frozen_junit_tests=stored, expected_jvm_profile=profile,
        expected_external_baseline_sha256=approved["baseline_sha256"])
    runner.save_json(root / "oracle-full.json", full)
    if full.get("passed") is not True:
        raise RuntimeError("oracle candidate failed complete sealed gate")
    if runner.external_root.tree_sha256(candidate) != source_before:
        raise RuntimeError("oracle verifier modified disposable candidate")
    if runner.external_root.tree_sha256(Path(ref["baseline"]["root"])) != approved["baseline_sha256"]:
        raise RuntimeError("immutable M3.2 baseline changed")
    print("NO_MODEL_ORACLE_PASS", len(stored), "hidden classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
