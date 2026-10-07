"""Read-only remote inventory. Never converts host-bound attestation to cloud authority."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANCHOR = "63c0281672e130baceafe62b61901e17a73c7fb0"
CORPUS = ROOT / "recovery/workshop-source-20261006"
FREEZE = CORPUS / "workspace/HIVE-FACTORIAL-003R1/FREEZE.json"
BASELINE = CORPUS / "external/m3.2-baseline"
CONTRACT = ROOT / "recovery/rc1-replay/REPLAY_ENVIRONMENT_CONTRACT.json"
SOURCE = ROOT / "recovery/rc1-replay/SOURCE_MANIFEST.json"


class QualificationFailure(RuntimeError):
    pass


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, timeout=30, check=True).stdout.strip()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_checkout(expected_commit: str):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit) or git("rev-parse", "HEAD") != expected_commit:
        raise QualificationFailure("EXACT_COMMIT_REQUIRED")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise QualificationFailure("CLEAN_CHECKOUT_REQUIRED")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", ANCHOR, expected_commit],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)


def controller_identity() -> dict:
    expected = subprocess.run(["git", "-C", str(ROOT), "show", f"{ANCHOR}:recovery/rc1-replay/SOURCE_MANIFEST.json"],
                              capture_output=True, check=True, timeout=30).stdout
    if SOURCE.read_bytes() != expected:
        raise QualificationFailure("RECOVERY_SOURCE_MANIFEST_CHANGED")
    manifest = json.loads(expected)
    paths = {row["path"] for row in manifest["files"]}
    actual = {path.relative_to(ROOT).as_posix() for path in (ROOT / "hive_canonical").rglob("*")
              if path.is_file() and "__pycache__" not in path.parts}
    if paths != actual:
        raise QualificationFailure("SEALED_CONTROLLER_FILE_SET_CHANGED")
    for row in manifest["files"]:
        source = ROOT / row["path"]
        if source.is_symlink() or file_sha(source) != row["sha256"]:
            raise QualificationFailure("SEALED_CONTROLLER_BYTES_CHANGED")
    return {"classification": "EXACTLY_REPRODUCED", "anchor_commit": ANCHOR,
            "manifest_sha256": hashlib.sha256(expected).hexdigest(), "sealed_files": len(paths),
            "controller": "HIVE-FACTORIAL-003R1/RC1/001C"}


def inventory(*, expected_commit: str, environment_root: Path | None = None) -> dict:
    exact_checkout(expected_commit)
    historical_contract = subprocess.run(["git", "-C", str(ROOT), "show",
        f"{ANCHOR}:recovery/rc1-replay/REPLAY_ENVIRONMENT_CONTRACT.json"],
        capture_output=True, timeout=30, check=True).stdout
    if CONTRACT.read_bytes() != historical_contract:
        raise QualificationFailure("HISTORICAL_REPLAY_CONTRACT_CHANGED")
    # Recovery helpers, attestations, evidence and corpora are independently
    # immutable. New code lives entirely outside their tree.
    if git("rev-parse", "HEAD:recovery") != git("rev-parse", f"{ANCHOR}:recovery"):
        raise QualificationFailure("HISTORICAL_RECOVERY_TREE_CHANGED")
    contract = json.loads(CONTRACT.read_bytes())
    controller = controller_identity()
    corpus_tree = git("rev-parse", "HEAD:recovery/workshop-source-20261006")
    baseline_tree = git("rev-parse", "HEAD:recovery/workshop-source-20261006/external/m3.2-baseline")
    if corpus_tree != contract["historical_corpus_tree"] or baseline_tree != contract["baseline_git_tree"]:
        raise QualificationFailure("FROZEN_SOURCE_CHANGED")
    freeze = json.loads(FREEZE.read_bytes())
    task = next(item for item in freeze["tasks"] if item["id"] == "J001")
    hidden = CORPUS / "external/historical-work/HIVE-FACTORIAL-001/hidden-tests" / task["test_filename"]
    if (file_sha(hidden) != contract["frozen_j001_test_sha256"] or
        hashlib.sha256(task["request"].encode()).hexdigest() != contract["task_request_sha256"] or
        (BASELINE / task["test_path"]).exists()):
        raise QualificationFailure("FROZEN_TASK_OR_HIDDEN_BOUNDARY_CHANGED")
    if task["files"] != ["src/main/java/dev/atmcompanion/state/SnapshotFormatter.java"]:
        raise QualificationFailure("FROZEN_WRITE_SCOPE_CHANGED")
    components = {
        "controller": controller,
        "baseline": {"classification": "EXACTLY_REPRODUCED", "git_tree": baseline_tree},
        "historical_corpus": {"classification": "EXACTLY_REPRODUCED", "git_tree": corpus_tree},
        "frozen_acceptance": {"classification": "EXACTLY_REPRODUCED", "sha256": file_sha(hidden), "model_visible": False},
        "task_and_scope": {"classification": "EXACTLY_REPRODUCED", "request_sha256": task["request_sha256"], "allowed_files": task["files"]},
        "python_runtime": {"classification": "DIFFERENT_ENVIRONMENT", "version": platform.python_version(),
                           "platform": platform.platform(), "executable_sha256": file_sha(Path(sys.executable)),
                           "historical": "Windows CPython 3.13.14 plus sealed DLL/stdlib/packages/import paths"},
        "verifier_image": {"classification": "UNAVAILABLE", "required_image_id": contract["verifier_image_id"]},
        "gradle_cache_and_nfrt": {"classification": "UNAVAILABLE", "required_selected_files": 4866, "required_layout_files": 4873},
        "java_and_gradle": {"classification": "UNAVAILABLE", "required_java": "Temurin 21.0.12.1+1", "required_gradle": "9.2.1"},
        "network_policy": {"classification": "UNAVAILABLE", "required": "verifier --network none, offline Gradle; provider TLS API only"},
    }
    blockers = ["REMOTE_PYTHON_RUNTIME_NOT_QUALIFIED", "REMOTE_BASELINE_CONTROL_NOT_RUN",
                "REMOTE_FULL_GATE_CONTROL_NOT_RUN", "REMOTE_ISOLATION_NOT_LIVE_PROBED",
                "REMOTE_EXECUTION_CONTRACT_NOT_REVIEWED", "ARTIFACT_TRANSFER_RIGHTS_UNVERIFIED"]
    source_probe = subprocess.run([sys.executable, "-B", str(ROOT / "recovery/rc1-replay/verify_source.py"), "verify"],
                                  capture_output=True, timeout=30)
    historical_source_preflight = "PASS" if source_probe.returncode == 0 else "FAILED"
    if source_probe.returncode != 0:
        # Keep the historical command's result. The path-indexed byte check
        # above records identities only; it does not override this failed gate.
        blockers.append("HISTORICAL_SOURCE_PREFLIGHT_FAILED_ON_THIS_PLATFORM")
    docker = shutil.which("docker")
    if docker:
        try:
            image = subprocess.run([docker, "image", "inspect", contract["verifier_image_id"], "--format", "{{.Id}}"],
                                   capture_output=True, text=True, timeout=15, check=True).stdout.strip()
            if image == contract["verifier_image_id"]:
                components["verifier_image"]["classification"] = "EXACTLY_REPRODUCED"
        except (subprocess.SubprocessError, OSError):
            blockers.append("PINNED_VERIFIER_IMAGE_UNAVAILABLE")
    else:
        blockers.append("DOCKER_UNAVAILABLE")
    if environment_root is not None:
        try:
            module_path = ROOT / "recovery/rc1-closure/environment/verify_environment.py"
            spec = importlib.util.spec_from_file_location("remote_environment_inventory", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            relocated = module.verify(environment_root)
            layout_path = ROOT / "recovery/rc1-replay/verify_replay.py"
            spec = importlib.util.spec_from_file_location("remote_layout_inventory", layout_path)
            layout_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(layout_module)
            count = layout_module.verify_exact_relocation_layout(environment_root, module, freeze)
            components["gradle_cache_and_nfrt"].update(classification="EXACTLY_REPRODUCED", sealed_layout_files=count,
                                                    environment=relocated, acquisition="HASH_VERIFIED_RELOCATION_ONLY")
            # Cache/image IDs prove bytes, not remote execution or host qualification.
        except Exception:
            blockers.append("SEALED_CACHE_OR_NFRT_UNAVAILABLE_OR_INVALID")
    else:
        blockers.append("SEALED_CACHE_OR_NFRT_NOT_SUPPLIED")
    free = shutil.disk_usage(ROOT).free
    return {"schema_version": 1, "experiment_family": "HIVE-REMOTE-API-QUALIFICATION-001",
            "git_commit": expected_commit, "components": components, "classification": "UNAVAILABLE",
            "remote_verifier_qualified": False, "ready_for_model_backed_task": False,
            "blockers": blockers, "host_cpu_count": os.cpu_count(), "host_free_disk_bytes": free,
            "model_calls": 0, "promotion_authorization": "unavailable",
            "historical_source_preflight": historical_source_preflight,
            "recovery_002_authorization_reused": False,
            "conclusion": "Source reproduced; remote apparatus and behavior are not qualified."}


def require_remote_qualification(_report: dict):
    # A JSON passed=true flag is not authority. There is intentionally no caller
    # override or generic command execution while apparatus/transfer is blocked.
    raise QualificationFailure("REMOTE_APPARATUS_UNQUALIFIED: new reviewed contract required")
