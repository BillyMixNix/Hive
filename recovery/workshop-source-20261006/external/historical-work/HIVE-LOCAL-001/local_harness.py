"""Read-only integrity and outcome rules for HIVE-LOCAL-001.

No OpenAI code path is imported or called by this module. Ollama HTTP calls
are local-only inventory requests; generation is performed by Workshop.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
WORKSHOP = HERE / "workshop"
ASTRA_002 = HERE.parent / "HIVE-ASTRA-002"
ASTRA_LOCK = "4a408406e1f73d4a30edc2269255a82e99023a39dfd8f37101adb7663afa5c58"
REFERENCE = ASTRA_002 / "FREEZE-002.json"
MODEL = "qwen2.5-coder:14b"
OLLAMA = "http://127.0.0.1:11434"
PORT = 8766
MIN_FREE_BYTES = 8 * 1024**3
TASK_ORDER = [f"T{i:03d}" for i in range(1, 9)] + [f"N{i:03d}" for i in range(1, 9)]
SOURCE_EXCLUDES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "data", "media", "reports", "snapshots",
    "workspace", "hive_runs", "self_snapshots", "logs", "build", "dist",
    "outputs", "releases", "artifacts", ".codex", ".agents",
}

sys.path.insert(0, str(WORKSHOP))
from workshop import external_root, hive, hive_jvm, hive_verifier, providers  # noqa: E402
from verification import prime_gradle_cache  # noqa: E402


class PreflightFailure(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_freeze() -> dict:
    if not REFERENCE.is_file() or sha(REFERENCE) != ASTRA_LOCK:
        raise PreflightFailure("Astra-002 reference lock changed")
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def source_manifest() -> list[dict]:
    rows = []
    for path in sorted(WORKSHOP.rglob("*"), key=lambda p: p.relative_to(WORKSHOP).as_posix()):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(WORKSHOP)
        name = path.name
        if (any(part in SOURCE_EXCLUDES for part in rel.parts) or name.startswith(".env")
                or path.suffix == ".pyc" or re.search(
                    r"(?i)(^credentials|^secrets|\.key$|\.pem$|\.p12$|\.pfx$|\.log$)", name)):
            continue
        rows.append({"path": rel.as_posix(), "sha256": sha(path), "size": path.stat().st_size})
    return rows


def task_specs(reference: dict) -> list[dict]:
    specs = []
    for group_name in ("replication", "novel"):
        group = reference["task_groups"][group_name]
        doc = HERE / ("TASKS.md" if group_name == "replication" else "NOVEL-TASKS.md")
        if sha(doc) != group["task_spec_sha256"]:
            raise PreflightFailure(f"{group_name} task document differs from frozen reference")
        matches = re.findall(
            r"(?ms)^## ([TN]\d{3}) — [^\n]+\n\n(.*?)\n\nFrozen test: `([^`]+)`\.",
            doc.read_text(encoding="utf-8"),
        )
        if len(matches) != 8:
            raise PreflightFailure(f"{group_name} task parser did not find eight tasks")
        for (task_id, request, filename), expected in zip(matches, group["tasks"]):
            test = HERE / "frozen-tests" / filename
            if (task_id != expected["id"] or request != expected["request"]
                    or filename != Path(expected["test_path"]).name
                    or sha(test) != expected["test_sha256"]):
                raise PreflightFailure(f"Frozen task or test differs: {task_id}")
            specs.append({
                "id": task_id, "group": group_name, "request": request,
                "request_sha256": expected["request_sha256"],
                "test_path": expected["baseline_test_path"],
                "test_sha256": expected["test_sha256"],
                "class_name": re.search(r"(?m)^package\s+([\w.]+)\s*;",
                                        test.read_text(encoding="utf-8")).group(1)
                              + "." + test.stem,
                "expected_cases": expected["expected_cases"],
                "test_source": test.read_text(encoding="utf-8"),
            })
    if [spec["id"] for spec in specs] != TASK_ORDER:
        raise PreflightFailure("Local characterization task order changed")
    return specs


def model_inventory() -> dict:
    try:
        tags = httpx.get(f"{OLLAMA}/api/tags", timeout=10).json()["models"]
        entry = next(item for item in tags if item["name"] == MODEL)
        show = httpx.post(f"{OLLAMA}/api/show", json={"model": MODEL}, timeout=10).json()
        version = subprocess.run(["ollama", "--version"], capture_output=True,
                                 text=True, timeout=10, check=True).stdout.strip()
    except (OSError, KeyError, StopIteration, httpx.HTTPError, subprocess.SubprocessError) as exc:
        raise PreflightFailure(f"Local Ollama model unavailable: {type(exc).__name__}: {exc}") from exc
    return {
        "tag": MODEL, "digest": entry["digest"], "size_bytes": entry["size"],
        "quantization": entry["details"]["quantization_level"],
        "parameters": show["details"]["parameter_size"],
        "model_context_limit": show["model_info"]["qwen2.context_length"],
        "ollama_version": version,
    }


def approved_environment(reference: dict) -> dict:
    """Validate exact sealed image, baseline and approved offline inputs."""
    baseline = Path(reference["baseline"]["root"])
    baseline_hash = external_root.tree_sha256(baseline)
    if baseline_hash != reference["baseline"]["tree_sha256"]:
        raise PreflightFailure("Immutable M3.2 baseline hash mismatch")
    docker = shutil.which("docker")
    if not docker:
        raise PreflightFailure("Docker CLI unavailable")
    image = hive_verifier.DEFAULT_IMAGE
    if image != reference["verifier"]["image"]:
        raise PreflightFailure("Hive-selected verifier tag changed")
    try:
        inspected = subprocess.run(
            [docker, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=15, check=True,
        ).stdout.strip()
        subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"],
                       capture_output=True, text=True, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightFailure(f"Docker verifier unavailable: {type(exc).__name__}: {exc}") from exc
    if inspected != reference["verifier"]["image_id"]:
        raise PreflightFailure("Approved verifier image ID changed")
    if hive_verifier.JVM_CONTAINER_LIMITS != reference["verifier"]["limits"]:
        raise PreflightFailure("Frozen finite verifier envelope changed")

    original = ASTRA_002.parent / "Nix-Workshop-v0.11.1-persistent-agents" / "Nix_Workshop_v0_11_1"
    run_id = reference["approved_cache"]["run_id"]
    cache = original / "hive_runs" / "approved-gradle-caches" / run_id
    evidence = original / "hive_runs" / run_id
    provenance = cache / ".hive-priming-provenance" / run_id
    files = {
        "gradle_artifact_manifest_sha256": provenance / "artifacts.manifest.json",
        "gradle_priming_provenance_sha256": provenance / "provenance.json",
        "external_build_inputs_manifest_sha256": evidence / "external-build-inputs.manifest.json",
        "external_build_inputs_provenance_sha256": evidence / "external-build-inputs.provenance.json",
        "frozen_junit_manifest_sha256": evidence / "frozen-junit-manifest.json",
    }
    for name, path in files.items():
        if not path.is_file() or sha(path) != reference["approved_cache"][name]:
            raise PreflightFailure(f"Approved offline cache evidence changed: {name}")
    inventory = json.loads(files["gradle_artifact_manifest_sha256"].read_text(encoding="utf-8"))
    if prime_gradle_cache._inventory_cache(cache) != inventory.get("artifacts"):
        raise PreflightFailure("Approved Gradle dependency inventory changed")
    os.environ["GRADLE_USER_HOME"] = str(cache.resolve(strict=True))
    profile = hive_jvm.inspect_gradle_project(baseline)
    if not profile or profile["version"] != reference["verifier"]["gradle_wrapper_version"]:
        raise PreflightFailure("Checked-in Gradle wrapper profile changed")
    hive_jvm.gradle_cache_locations(profile)
    hive_jvm.external_build_input_locations(
        profile, baseline_sha256=baseline_hash, container_image_id=inspected)
    frozen_manifest = json.loads(files["frozen_junit_manifest_sha256"].read_text(encoding="utf-8"))
    if not hive_jvm.verify_frozen_artifacts(frozen_manifest, evidence):
        raise PreflightFailure("Approved frozen-JUnit manifest changed")
    return {"baseline_sha256": baseline_hash, "verifier_image_id": inspected,
            "approved_cache_run_id": run_id, "approved_cache_root": str(cache),
            "jvm_profile": profile}


def disk_free_bytes() -> int:
    return shutil.disk_usage(HERE).free


def no_cloud_key() -> None:
    if providers.openai_key() or os.environ.get("OPENAI_API_KEY"):
        raise PreflightFailure("Cloud credential present in local experiment process")
    if (WORKSHOP / ".env.local").exists() or (WORKSHOP / ".env").exists():
        raise PreflightFailure("Local Workshop checkout contains an environment file")


def service_preflight() -> dict:
    try:
        health = httpx.get(f"http://127.0.0.1:{PORT}/api/health", timeout=10).json()
        state = httpx.get(f"http://127.0.0.1:{PORT}/api/preflight", timeout=15).json()
    except httpx.HTTPError as exc:
        raise PreflightFailure(f"Local Workshop service unavailable: {exc}") from exc
    apparatus = health.get("apparatus") or {}
    if (not health.get("ok") or apparatus.get("study") != "HIVE-LOCAL-001"
            or apparatus.get("jvm_verifier_pids") != 448
            or apparatus.get("jvm_verifier_image") != hive_verifier.DEFAULT_IMAGE
            or state.get("openai_key_loaded") is not False
            or (health.get("jobs") or {}).get("active_jobs") != 0):
        raise PreflightFailure("Serving Workshop is not the keyless frozen local apparatus")
    return {"version": health["version"], "key_loaded": False,
            "active_jobs": health["jobs"]["active_jobs"]}


def build_request(task: dict, frozen: dict, trial_id: str) -> dict:
    return {
        "request": task["request"], "local_model": frozen["local_model"]["tag"],
        "allow_cloud": False, "max_tier": "local", "max_cost": 0.0,
        "agent_backend": "classic", "external_source_root": frozen["baseline"]["root"],
        "allow_external_root": True,
        "frozen_junit_tests": [{
            "path": task["test_path"], "class_name": task["class_name"],
            "expected_cases": task["expected_cases"], "source": task["test_source"],
        }],
        "experiment": {
            "study_id": "HIVE-LOCAL-001", "condition_id": "hive_local",
            "task_id": task["id"], "replicate_index": 1, "trial_id": trial_id,
            "condition_spec_sha256": frozen["lock_sha256"],
        },
    }


OUTCOME_CLASSES = (
    "VERIFIED_SUCCESS", "MODEL_TASK_FAILURE", "VERIFIER_INFRA_FAILURE",
    "LOCAL_RUNTIME_FAILURE", "HARNESS_FAILURE", "FALSE_ACCEPTANCE", "INVALID",
)
VERIFIER_INFRA_MARKERS = (
    "pthread_create failed", "unable to create native thread", "eagain",
    "docker is unavailable", "verifier image", "gradle timeout",
    "approved cache", "dependency cache", "network_access_attempt",
    "missing dependency", "external build-input cache",
)
LOCAL_RUNTIME_MARKERS = (
    "local model", "ollama", "connecterror", "connection attempts failed",
    "generation timed out", "total generation timeout", "provider failure",
    "local planner agent failed", "local backend agent failed",
)
CONTAINMENT_MARKERS = ("external_integrity", "source_immutability", "cache_integrity")


def _text(run: dict) -> str:
    parts = [str(run.get("errors") or "")]
    verification = run.get("verification") or {}
    for check in verification.get("checks") or []:
        if check.get("passed") is False:
            parts.append(str(check.get("name") or ""))
            parts.append(str(check.get("detail") or ""))
    return "\n".join(parts).casefold()


def classify(run: dict) -> str:
    if not isinstance(run, dict):
        return "INVALID"
    verification = run.get("verification") or {}
    checks = {check.get("name"): check for check in verification.get("checks") or []}
    acceptance = checks.get("frozen_junit_acceptance") or {}
    full = checks.get("full_gradle_check") or {}
    if run.get("status") == "ready" and not (
            verification.get("passed") is True and acceptance.get("passed") is True
            and full.get("passed") is True):
        return "FALSE_ACCEPTANCE"
    integrity = run.get("external_baseline_integrity") or {}
    if (run.get("applied") or integrity.get("baseline_unchanged") is False
            or integrity.get("candidate_unchanged") is False
            or (run.get("metadata") or {}).get("cloud_spend", 0) not in (None, 0, 0.0)):
        return "INVALID"
    for call in (run.get("metadata") or {}).get("agent_calls") or []:
        if call.get("provider") != "ollama":
            return "INVALID"
    evidence = _text(run)
    if any(marker in evidence for marker in CONTAINMENT_MARKERS):
        return "INVALID"
    if run.get("status") == "ready":
        return "VERIFIED_SUCCESS"
    if any(marker in evidence for marker in VERIFIER_INFRA_MARKERS):
        return "VERIFIER_INFRA_FAILURE"
    if any(call.get("status") == "failed" and call.get("provider") == "ollama"
           for call in (run.get("metadata") or {}).get("agent_calls") or []):
        return "LOCAL_RUNTIME_FAILURE"
    if any(marker in evidence for marker in LOCAL_RUNTIME_MARKERS):
        return "LOCAL_RUNTIME_FAILURE"
    if run.get("status") in {"rejected", "failed"}:
        return "MODEL_TASK_FAILURE"
    return "INVALID"
