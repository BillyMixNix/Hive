"""Mechanically create proposed FREEZE-002 once; no model or API requests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HISTORICAL = HERE.parent / "HIVE-ASTRA-001"
APPROVED_WORKSHOP = HERE.parent / "Nix-Workshop-v0.11.1-persistent-agents" / "Nix_Workshop_v0_11_1"
WORKSHOP = HERE / "workshop"
SEED_HEX = "bf42a21793d50c68e419cc07f2a5d1e0"
HISTORICAL_LOCK = "2d33ce88af66ed3e1f0c1e73ce3a1de62ffe36cd355a21554cc7306fddb6d291"
SOURCE_EXCLUDES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                   ".mypy_cache", ".ruff_cache", "data", "media", "reports", "snapshots",
                   "workspace", "hive_runs", "self_snapshots", "logs", "build", "dist",
                   "outputs", "releases", "artifacts", ".codex", ".agents"}
sys.path.insert(0, str(WORKSHOP))
from workshop import external_root, hive_jvm, hive_verifier  # noqa: E402
from verification import prime_gradle_cache  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(root)
        name = path.name
        if (any(part in SOURCE_EXCLUDES for part in rel.parts) or name.startswith(".env")
                or path.suffix == ".pyc" or re.search(
                    r"(?i)(^credentials|^secrets|\.key$|\.pem$|\.p12$|\.pfx$|\.log$)", name)):
            continue
        rows.append({"path": rel.as_posix(), "sha256": sha(path), "size": path.stat().st_size})
    return rows


def group(name: str, root: Path, doc: str, folder: str, prefix: str) -> dict:
    spec = root / doc
    matches = re.findall(r"(?ms)^## ([TN]\d{3}) — [^\n]+\n\n(.*?)\n\nFrozen test: `([^`]+)`\.",
                         spec.read_text(encoding="utf-8"))
    if [item[0] for item in matches] != [f"{prefix}{index:03d}" for index in range(1, 9)]:
        raise ValueError(f"{name} task parser did not find eight ordered prompts")
    historical = None
    if name == "replication":
        previous = json.loads((HISTORICAL / "FREEZE-v2.json").read_text(encoding="utf-8"))
        historical = previous["task_freeze"]
        if historical["task_spec_sha256"] != sha(spec):
            raise ValueError("historical task specification does not match Freeze-v2")
    tasks = []
    for task_id, request, filename in matches:
        test_path = root / folder / filename
        if not test_path.is_file():
            raise FileNotFoundError(test_path)
        source = test_path.read_text(encoding="utf-8")
        package = re.search(r"(?m)^package\s+([\w.]+)\s*;", source)
        cases = len(re.findall(r"(?m)^\s*@Test\b", source))
        if not package or not cases:
            raise ValueError(f"frozen JUnit has no package or test: {test_path}")
        if historical and (historical["acceptance_tests"].get(f"{folder}/{filename}") != sha(test_path)
                           or historical["expected_cases"].get(f"{folder}/{filename}") != cases):
            raise ValueError(f"historical frozen JUnit differs from Freeze-v2: {test_path}")
        baseline_rel = "src/test/java/" + package.group(1).replace(".", "/") + "/" + filename
        tasks.append({
            "id": task_id, "request": request, "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
            "test_path": f"{folder}/{filename}", "test_sha256": sha(test_path),
            "baseline_test_path": baseline_rel, "expected_cases": cases,
        })
    return {"task_spec_path": doc, "task_spec_sha256": sha(spec), "tasks": tasks}


def main() -> None:
    freeze_path = HERE / "FREEZE-002.json"
    lock_path = HERE / "FREEZE-002.sha256"
    if freeze_path.exists() or lock_path.exists() or (HERE / "execution-002").exists():
        raise RuntimeError("Proposed freeze or execution evidence already exists; refusing overwrite")
    if sha(HISTORICAL / "FREEZE-v2.json") != HISTORICAL_LOCK:
        raise RuntimeError("historical freeze-v2 lock changed")
    old = json.loads((HISTORICAL / "FREEZE-v2.json").read_text(encoding="utf-8"))
    baseline = Path(old["baseline"]["root"])
    if external_root.tree_sha256(baseline) != old["baseline"]["tree_sha256"]:
        raise RuntimeError("immutable baseline changed")
    image = subprocess.run(["docker", "image", "inspect", hive_verifier.DEFAULT_IMAGE,
                            "--format", "{{.Id}}"], capture_output=True, text=True, timeout=15)
    if image.returncode or image.stdout.strip() != old["verifier"]["image_id"]:
        raise RuntimeError("approved verifier image is unavailable or changed")
    cache_id = old["approved_cache"]["run_id"]
    cache = APPROVED_WORKSHOP / "hive_runs" / "approved-gradle-caches" / cache_id
    evidence = APPROVED_WORKSHOP / "hive_runs" / cache_id
    checks = {
        "gradle_artifact_manifest_sha256": cache / ".hive-priming-provenance" / cache_id / "artifacts.manifest.json",
        "gradle_priming_provenance_sha256": cache / ".hive-priming-provenance" / cache_id / "provenance.json",
        "external_build_inputs_manifest_sha256": evidence / "external-build-inputs.manifest.json",
        "external_build_inputs_provenance_sha256": evidence / "external-build-inputs.provenance.json",
        "frozen_junit_manifest_sha256": evidence / "frozen-junit-manifest.json",
    }
    if any(sha(path) != old["approved_cache"][key] for key, path in checks.items()):
        raise RuntimeError("approved cache provenance or manifest changed")
    inventory = json.loads(checks["gradle_artifact_manifest_sha256"].read_text(encoding="utf-8"))
    if prime_gradle_cache._inventory_cache(cache) != inventory.get("artifacts"):
        raise RuntimeError("approved Gradle artifact inventory changed")
    profile = hive_jvm.inspect_gradle_project(baseline)
    os.environ["GRADLE_USER_HOME"] = str(cache.resolve(strict=True))
    hive_jvm.gradle_cache_locations(profile)
    hive_jvm.external_build_input_locations(profile, baseline_sha256=old["baseline"]["tree_sha256"],
                                             container_image_id=image.stdout.strip())
    stress = []
    for index in range(1, 4):
        path = HERE / "diagnostics" / f"candidate-448-{index:02d}.json"
        run = json.loads(path.read_text(encoding="utf-8"))
        checks_by_name = {check["name"]: check for check in run["checks"]}
        if (not run["passed"] or run["pids_limit"] != 448 or run["network"] != "none"
                or run["image_id"] != old["verifier"]["image_id"]
                or run["baseline_sha256"] != old["baseline"]["tree_sha256"]
                or run["sampled_pids_events_last"] != "max 0"
                or checks_by_name["frozen_junit_acceptance"]["test_cases"] != 1
                or checks_by_name["full_gradle_check"]["test_cases"] < 152):
            raise RuntimeError(f"finite-envelope stress result invalid: {path}")
        stress.append({"path": path.relative_to(HERE).as_posix(), "sha256": sha(path),
                       "wall_seconds": run["wall_seconds"], "sampled_pids_peak": run["sampled_pids_peak"],
                       "frozen_junit_cases": 1,
                       "full_junit_cases": checks_by_name["full_gradle_check"]["test_cases"]})
    task_groups = {
        "replication": group("replication", HISTORICAL, "TASKS.md", "frozen-tests", "T"),
        "novel": group("novel", HERE, "NOVEL-TASKS.md", "novel-frozen-tests", "N"),
    }
    order = {}
    for item in task_groups["replication"]["tasks"] + task_groups["novel"]["tasks"]:
        task_id = item["id"]
        bit = hashlib.sha256(bytes.fromhex(SEED_HEX) + task_id.encode("ascii")).digest()[0] & 1
        order[task_id] = "direct-first" if bit else "hive-first"
    controls = ["APPARATUS-POLICY.md", "direct_context.py", "control_request.py", "outcomes.py",
                "executor.py", "diagnose_verifier.py", "validate_novel_tests.py", "make_freeze.py",
                "test_direct_context.py", "test_control_request.py", "test_outcomes.py",
                "test_freeze_apparatus.py"]
    frozen = {
        "benchmark": "HIVE-ASTRA-002", "schema_version": 1, "status": "proposed_not_executed",
        "relationship_to_001": {
            "freeze_v2_lock_sha256": HISTORICAL_LOCK,
            "raw_results_sha256": sha(HISTORICAL / "execution-v2" / "raw_results.json"),
            "event_log_sha256": sha(HISTORICAL / "execution-v2" / "events.ndjson"),
            "historical_results_preserved": True,
            "direct_001_trials_are_apparatus_invalid_not_model_failures": True,
        },
        "workshop": {"version": "0.11.1", "source_root": str(WORKSHOP),
                     "source_manifest": manifest(WORKSHOP),
                     "fingerprint_excludes_secrets_runtime_caches": True},
        "control_apparatus": {"files": {name: sha(HERE / name) for name in controls},
                              "context_policy": "deterministic-path-symbol-lexical-v1",
                              "context_char_budget": 320_000,
                              "individual_input_text_field_max_chars": 400_000,
                              "frozen_acceptance_in_model_context": False,
                              "provider_validation_only_request": "unavailable_without_model_turn"},
        "task_groups": task_groups,
        "novel_acceptance_red_gate": {
            "report_path": "diagnostics/novel-test-red-gate/report.json",
            "report_sha256": sha(HERE / "diagnostics/novel-test-red-gate/report.json"),
            "expected_state": "fails on missing task APIs before implementation; not a pass",
        },
        "paired_evaluation": {"within_pair_order_seed_hex": SEED_HEX,
                              "within_pair_order_algorithm": "sha256(seed_bytes || ASCII task_id)[0] & 1; 1=direct-first",
                              "within_pair_order": order,
                              "same_verifier_and_baseline_for_both_conditions": True,
                              "direct_model_turns": 1, "direct_repairs": 0,
                              "hive_repair_limits": "unchanged copied Workshop policy",
                              "promotion": False},
        "provider": old["provider"] | {"model_calls_before_freeze": 0,
                                      "002_provider_usage_before_freeze": "unknown_not_queried",
                                      "future_execution_requires_separate_authorization_and_provider_cap": True},
        "baseline": old["baseline"],
        "verifier": old["verifier"] | {"limits": dict(hive_verifier.JVM_CONTAINER_LIMITS),
                                       "resource_change_from_001": "host-controlled PID cap 384 -> 448 only",
                                       "stress": stress},
        "approved_cache": old["approved_cache"],
        "outcome_classes": [name for name in (
            "VERIFIED_SUCCESS", "MODEL_TASK_FAILURE", "VERIFIER_INFRA_FAILURE",
            "PROVIDER_INFRA_FAILURE", "HARNESS_FAILURE", "FALSE_ACCEPTANCE", "INVALID")],
        "integrity_and_execution": {"no_002_model_calls_or_results": True,
                                    "external_root_promotion_prohibited": True,
                                    "sealed_verifier_network": "none",
                                    "source_and_caches_read_only": True,
                                    "private_tmpfs_stage": True,
                                    "preflight_before_each_pair": True,
                                    "executor_requires_separate_exact_lock_authorization": True},
    }
    data = (json.dumps(frozen, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    lock = hashlib.sha256(data).hexdigest()
    freeze_path.write_bytes(data)
    lock_path.write_text(lock + "\n", encoding="utf-8")
    print(json.dumps({"proposed_lock_sha256": lock, "tasks": sum(len(g["tasks"]) for g in task_groups.values()),
                      "workshop_source_files": len(frozen["workshop"]["source_manifest"]),
                      "novel_tests": len(task_groups["novel"]["tasks"]),
                      "file": str(freeze_path)}), flush=True)


if __name__ == "__main__":
    main()
