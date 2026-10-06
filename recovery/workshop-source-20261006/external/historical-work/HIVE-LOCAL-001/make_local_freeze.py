"""Create HIVE-LOCAL-001's independent lock after non-model preflight."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from local_harness import (
    HERE, MIN_FREE_BYTES, MODEL, OUTCOME_CLASSES, TASK_ORDER, WORKSHOP,
    PreflightFailure, approved_environment, disk_free_bytes, hive,
    model_inventory, no_cloud_key, reference_freeze, sha, source_manifest,
    task_specs,
)

FREEZE = HERE / "HIVE-LOCAL-001-FREEZE.json"
LOCK_FILE = HERE / "HIVE-LOCAL-001-FREEZE.sha256"
CONTROL_FILES = (
    "local_harness.py", "make_local_freeze.py", "run_local.py",
    "serve_local.py", "test_local_harness.py", "INVENTORY.md",
)


def main() -> None:
    if FREEZE.exists() or LOCK_FILE.exists() or (HERE / "execution").exists():
        raise RuntimeError("Local freeze or execution evidence already exists; refusing overwrite")
    no_cloud_key()
    reference = reference_freeze()
    tasks = task_specs(reference)
    model = model_inventory()
    if model["tag"] != MODEL or model["model_context_limit"] != 32768:
        raise PreflightFailure("Chosen local coding model identity changed")
    approved = approved_environment(reference)
    free = disk_free_bytes()
    if free < MIN_FREE_BYTES:
        raise PreflightFailure("Insufficient disk space for 16 sealed candidates")

    compile_result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "."], cwd=WORKSHOP,
        capture_output=True, text=True, timeout=120,
    )
    test_env = os.environ.copy()
    test_env.pop("PYTEST_ADDOPTS", None)
    with TemporaryDirectory(prefix="freeze-pytest-", dir=HERE) as pytest_temp:
        suite = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "--basetemp", pytest_temp],
            cwd=WORKSHOP, env=test_env,
            capture_output=True, text=True, timeout=180,
        )
    if compile_result.returncode or suite.returncode:
        raise PreflightFailure("Copied Workshop compile or full suite failed: "
                               + (compile_result.stderr + suite.stdout + suite.stderr)[-3000:])

    repairs = {
        "planner_corrections": hive.MAX_PLAN_CORRECTIONS,
        "replans_per_worker": hive.MAX_REPLANS_PER_WORKER,
        "structural_edit_repairs_per_worker": hive.MAX_EDIT_REPAIRS_PER_WORKER,
        "targeted_corrections_per_worker": hive.MAX_TARGETED_CORRECTIONS_PER_WORKER,
        "observations_per_worker": hive.MAX_OBSERVATIONS_PER_WORKER,
    }
    frozen = {
        "study": "HIVE-LOCAL-001", "schema_version": 1,
        "status": "frozen_not_executed", "created_utc": datetime.now(timezone.utc).isoformat(),
        "study_design": "known-task, zero-API-cost local Hive characterization; no direct-control arm",
        "astra_reference": {"freeze_002_sha256": sha(HERE.parent / "HIVE-ASTRA-002" / "FREEZE-002.json"),
                            "source_only_no_rerun": True},
        "task_order": TASK_ORDER,
        "tasks": [{key: task[key] for key in ("id", "request_sha256", "test_sha256", "expected_cases")}
                  for task in tasks],
        "task_documents": {"TASKS.md": sha(HERE / "TASKS.md"),
                           "NOVEL-TASKS.md": sha(HERE / "NOVEL-TASKS.md")},
        "workshop": {"root": str(WORKSHOP), "version": "0.11.1",
                     "source_manifest": source_manifest(),
                     "compileall": "passed", "pytest": suite.stdout.strip().splitlines()[-1]},
        "local_model": {"tag": MODEL, "identity": model,
                        "observed_processor_split": "73% CPU / 27% GPU",
                        "observed_runtime_context": 32768,
                        "generation": {"temperature": hive.LOCAL_TEMPERATURE,
                                       "output_token_limits": {"planner": 2048, "ui": 6000,
                                                               "backend": 6000, "tests": 6000,
                                                               "reviewer": 1536},
                                       "num_ctx_override": None, "seed": None,
                                       "total_timeout_seconds": 900,
                                       "response_format": "Ollama schema-constrained JSON"}},
        "hardware": {"host": "Acer Nitro AN515-54", "logical_cpus": 8,
                     "ram_bytes": 17009004544, "gpu": "NVIDIA GeForce RTX 2060",
                     "gpu_vram_mib": 6144, "gpu_driver": "610.47"},
        "smoke": {"prompt_type": "non-benchmark exact-response smoke",
                  "response": "LOCAL_SMOKE_OK", "http_status": 200,
                  "wall_seconds": 58.835, "model_load_seconds": 55.774},
        "baseline": {"root": reference["baseline"]["root"],
                     "sha256": approved["baseline_sha256"]},
        "verifier": {"image": reference["verifier"]["image"],
                     "image_id": approved["verifier_image_id"],
                     "limits": reference["verifier"]["limits"],
                     "jvm_profile": approved["jvm_profile"],
                     "network": "none", "approved_cache_mount": "read-only",
                     "full_gate_after_frozen_targeted_only": True},
        "approved_cache": reference["approved_cache"],
        "repair_limits": repairs,
        "cloud_policy": {"allow_cloud": False, "max_tier": "local",
                         "agent_backend": "classic", "api_key_required": False,
                         "promotion": False},
        "outcome_classes": OUTCOME_CLASSES,
        "classification_rules_sha256": sha(HERE / "local_harness.py"),
        "control_files": {name: sha(HERE / name) for name in CONTROL_FILES},
        "disk": {"minimum_free_bytes_before_each_task": MIN_FREE_BYTES,
                 "free_bytes_at_freeze": free},
        "execution": {"one_attempt_per_task": True, "task_deadline_seconds": 8 * 3600,
                      "preflight_before_each_task": True,
                      "stop_on": ["FALSE_ACCEPTANCE", "freeze_or_baseline_mutation",
                                  "containment_failure", "cloud_provider_contact"],
                      "no_candidate_apply_or_promotion": True},
    }
    data = (json.dumps(frozen, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    FREEZE.write_bytes(data)
    LOCK_FILE.write_text(digest + "\n", encoding="utf-8")
    print(json.dumps({"freeze_sha256": digest, "tasks": len(tasks),
                      "source_files": len(frozen["workshop"]["source_manifest"]),
                      "pytest": frozen["workshop"]["pytest"], "disk_free_bytes": free}),
          flush=True)


if __name__ == "__main__":
    main()
