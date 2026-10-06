"""One-off, no-model sealed verification of the submitted J001 candidate.

This is independent evidence, not a HIVE-FACTORIAL-001 trial.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
STUDY = WORK / "HIVE-FACTORIAL-001"
CONTINUATION = WORK / "HIVE-FACTORIAL-001-CONTINUATION" / "evidence"
CANDIDATE = HERE / "HIVE-ASTRA-J001" / "candidate"
EVIDENCE = HERE / "sealed-evidence"
EXPECTED_CANDIDATE = "ecb294b3b7b9a0bd87e365e9f30d2b07ca083f65734abe0a433f1b69b700d4a6"
EXPECTED_IMAGE = "sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26"

# This process must never have cloud credentials or call a model.
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, str(WORK / "HIVE-JAVA-EDIT-001"))
import local_harness as prior  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name: str, value: object) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    if path.exists():
        raise RuntimeError(f"independent evidence already exists: {path}")
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def observed(report: dict, check_name: str, test_class: str, count: int) -> bool:
    checks = [check for check in report.get("checks", []) if check.get("name") == check_name]
    if len(checks) != 1 or not checks[0].get("passed"):
        return False
    detail = checks[0].get("detail") or {}
    if not isinstance(detail, dict):
        return False
    return any(
        item.get("class_name") == test_class
        and item.get("tests") == count
        and item.get("failures") == 0
        and item.get("errors") == 0
        and item.get("skipped") == 0
        for item in detail.get("tests", [])
    )


def main() -> None:
    events = [json.loads(line) for line in (CONTINUATION / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    if not events or events[-1] != {"time": events[-1]["time"], "kind": "completed", "trials": 32}:
        raise RuntimeError("the factorial continuation is not completed")
    results = json.loads((CONTINUATION / "raw_results.json").read_text(encoding="utf-8"))
    if len(results) != 32 or any(row.get("applied") or row.get("classification") == "FALSE_ACCEPTANCE" for row in results):
        raise RuntimeError("study outcome or promotion safety preflight failed")
    lock_path = STUDY / "FREEZE.json"
    if digest(lock_path) != (STUDY / "LOCK.sha256").read_text(encoding="ascii").strip():
        raise RuntimeError("factorial lock changed")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    task = next(item for item in lock["tasks"] if item["id"] == "J001")
    source_path = STUDY / "hidden-tests" / task["test_filename"]
    if digest(source_path) != task["test_sha256"]:
        raise RuntimeError("frozen J001 acceptance source changed")

    approved = prior.approved_environment(prior.reference_freeze())
    if approved["verifier_image_id"] != EXPECTED_IMAGE or approved["baseline_sha256"] != lock["baseline"]["sha256"]:
        raise RuntimeError("frozen verifier or baseline changed")
    if prior.disk_free_bytes() < prior.MIN_FREE_BYTES:
        raise RuntimeError("less than eight GiB free for isolated verification")
    candidate_hash = prior.external_root.tree_sha256(CANDIDATE)
    if candidate_hash != EXPECTED_CANDIDATE:
        raise RuntimeError("submitted candidate changed")
    profile = prior.hive_jvm.inspect_gradle_project(CANDIDATE)
    if profile != approved["jvm_profile"]:
        raise RuntimeError("candidate Gradle profile differs from frozen baseline")
    save("preflight.json", {
        "study_lock_sha256": digest(lock_path), "baseline_sha256": approved["baseline_sha256"],
        "candidate_sha256": candidate_hash, "verifier_image_id": approved["verifier_image_id"],
        "approved_cache_run_id": approved["approved_cache_run_id"],
        "frozen_test_sha256": task["test_sha256"], "frozen_test_class": task["test_class"],
        "frozen_test_cases": task["test_cases"], "mode": "independent_no_model_no_promotion",
    })

    frozen = prior.hive_jvm.freeze_junit_tests(CANDIDATE, [{
        "path": task["test_path"], "class_name": task["test_class"],
        "expected_cases": task["test_cases"], "source": source_path.read_text(encoding="utf-8"),
    }])
    artifacts = prior.hive_jvm.store_frozen_junit_tests(frozen, EVIDENCE)
    if not prior.hive_jvm.verify_frozen_artifacts(artifacts, EVIDENCE):
        raise RuntimeError("frozen acceptance artifact integrity failed")
    common = dict(external_root=True, frozen_junit_tests=artifacts,
                  expected_jvm_profile=profile,
                  expected_external_baseline_sha256=approved["baseline_sha256"])
    targeted = prior.hive_verifier.targeted_verify_isolated(CANDIDATE, [task["test_path"]], **common)
    save("targeted.json", targeted)
    targeted_observed = observed(targeted, "frozen_junit_acceptance", task["test_class"], task["test_cases"])
    if not targeted.get("passed") or not targeted_observed:
        save("summary.json", {"disposition": "TARGETED_FAILED", "targeted_passed": bool(targeted.get("passed")),
                              "targeted_test_observed": targeted_observed, "full_gate_run": False})
        return

    full = prior.hive_verifier.verify_tree_isolated(CANDIDATE, **common)
    save("full.json", full)
    full_observed = observed(full, "frozen_junit_acceptance", task["test_class"], task["test_cases"])
    full_checks = {check.get("name"): bool(check.get("passed")) for check in full.get("checks", [])}
    post_candidate = prior.external_root.tree_sha256(CANDIDATE)
    post_baseline = prior.external_root.tree_sha256(Path(lock["baseline"]["root"]))
    intact = post_candidate == candidate_hash and post_baseline == approved["baseline_sha256"]
    passed = bool(full.get("passed")) and full_observed and full_checks.get("full_gradle_check") and intact
    save("summary.json", {"disposition": "SEALED_PASS" if passed else "SEALED_FAIL",
                          "targeted_passed": True, "targeted_test_observed": True,
                          "full_gate_run": True, "full_passed": bool(full.get("passed")),
                          "full_test_observed": full_observed, "full_checks": full_checks,
                          "candidate_sha256_after": post_candidate, "baseline_sha256_after": post_baseline,
                          "baseline_candidate_intact": intact, "applied": False})


if __name__ == "__main__":
    main()
