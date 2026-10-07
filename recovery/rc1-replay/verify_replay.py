"""Pre-model host-bound J001 replay contract. No provider call is made here."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "recovery/rc1-replay/REPLAY_ENVIRONMENT_CONTRACT.json"
ENV_SCRIPT = ROOT / "recovery/rc1-closure/environment/verify_environment.py"
BASELINE = ROOT / "recovery/workshop-source-20261006/external/m3.2-baseline"
HIDDEN = ROOT / "recovery/workshop-source-20261006/external/historical-work/HIVE-FACTORIAL-001/hidden-tests"
FREEZE = ROOT / "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1/FREEZE.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def verify_exact_relocation_layout(root: Path, environment_module, freeze: dict) -> int:
    """Reject any unsealed Gradle init script or cache file, not just bad selected files."""
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("environment root is a link or junction")
    root = root.resolve(strict=True)
    cache, sibling = environment_module.paths(root)
    _, rows = environment_module._source_manifest(cache, freeze)
    relative_cache = cache.relative_to(root)
    relative_sibling = sibling.relative_to(root)
    metadata = relative_cache / ".hive-priming-provenance" / environment_module.RUN_ID
    expected = {str(relative_cache / item["path"]).replace("\\", "/") for item in rows}
    expected.update(str(metadata / name).replace("\\", "/") for name in environment_module.PROVENANCE)
    expected.update(str(relative_sibling / name).replace("\\", "/") for name in environment_module.PROVENANCE
                    if name.startswith("external-build-inputs."))
    expected.add("approved-nfrt-seed-v2.json")
    actual = set()
    for entry in root.rglob("*"):
        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()) or (
            getattr(entry.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("environment contains a link or junction")
        if entry.is_file():
            actual.add(entry.relative_to(root).as_posix())
        elif not entry.is_dir():
            raise ValueError("environment contains a non-regular entry")
    if actual != expected:
        raise ValueError(f"environment has unexpected or missing files: {len(actual ^ expected)}")
    return len(actual)


def verify(environment_root: Path, *, expected_commit: str, require_clean: bool = True) -> dict:
    contract = json.loads(CONTRACT.read_bytes())
    if contract.get("schema_version") != 1 or contract.get("classification") != "HOST_BOUND_RECOVERY_REPLAY_ONLY":
        raise ValueError("unrecognized host-bound replay contract")
    if contract.get("max_replays") != 1 or contract.get("promotion_authorization") != "unavailable":
        raise ValueError("replay cardinality or promotion policy differs")
    if not isinstance(expected_commit, str) or len(expected_commit) != 40 or git("rev-parse", "HEAD") != expected_commit:
        raise ValueError("replay checkout differs from explicitly approved exact commit")
    if environment_root.resolve(strict=True) != Path(contract["approved_environment_root"]).resolve(strict=True):
        raise ValueError("replay environment root differs from attested host location")
    if git("branch", "--show-current") != contract["required_branch"]:
        raise ValueError("replay checkout is not on the qualified recovery branch")
    if require_clean and git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("replay checkout is not clean")
    if git("rev-parse", "HEAD:recovery/workshop-source-20261006") != contract["historical_corpus_tree"]:
        raise ValueError("historical corpus changed")
    baseline_git_path = BASELINE.relative_to(ROOT).as_posix()
    if git("rev-parse", f"HEAD:{baseline_git_path}") != contract["baseline_git_tree"]:
        raise ValueError("frozen baseline Git tree changed")
    if sha(ROOT / "recovery/rc1-closure/environment/ENVIRONMENT_MANIFEST.json") != contract["environment_manifest_sha256"]:
        raise ValueError("approved environment manifest changed")
    python_manifest = ROOT / "recovery/rc1-replay/PYTHON_RUNTIME_MANIFEST.json"
    if sha(python_manifest) != contract["python_runtime_manifest_sha256"]:
        raise ValueError("host Python runtime manifest changed")
    python_spec = importlib.util.spec_from_file_location("rc1c_python", ROOT / "recovery/rc1-replay/python_runtime.py")
    python_module = importlib.util.module_from_spec(python_spec)
    python_spec.loader.exec_module(python_module)
    python_runtime = python_module.verify()
    source_script = ROOT / "recovery/rc1-replay/verify_source.py"
    source_spec = importlib.util.spec_from_file_location("rc1c_source", source_script)
    source_module = importlib.util.module_from_spec(source_spec)
    source_spec.loader.exec_module(source_module)
    source_manifest = ROOT / "recovery/rc1-replay/SOURCE_MANIFEST.json"
    if json.loads(source_manifest.read_bytes()) != source_module.build():
        raise ValueError("001C runtime source provenance changed")
    sys.path.insert(0, str(ROOT))
    from hive_canonical.legacy.workshop import external_root, hive_jvm
    from hive_canonical.controller import _qualify_gradle_scope
    if external_root.tree_sha256(BASELINE) != contract["baseline_source_sha256"]:
        raise ValueError("frozen baseline source identity changed")
    freeze = json.loads(FREEZE.read_bytes())
    task = next(item for item in freeze["tasks"] if item["id"] == contract["task_id"])
    request_sha = hashlib.sha256(task["request"].encode("utf-8")).hexdigest()
    if request_sha != contract["task_request_sha256"] or request_sha != task["request_sha256"]:
        raise ValueError("frozen J001 request identity changed")
    frozen_test = HIDDEN / task["test_filename"]
    if sha(frozen_test) != contract["frozen_j001_test_sha256"] or sha(frozen_test) != task["test_sha256"]:
        raise ValueError("frozen J001 acceptance identity changed")
    if (BASELINE / task["test_path"]).exists():
        raise ValueError("protected J001 test is present in model-visible baseline")
    scope = tuple(task["files"])
    _qualify_gradle_scope(scope, gradle_project=True)
    if any(not path.startswith("src/main/java/") or not path.endswith(".java") for path in scope):
        raise ValueError("J001 scope is not ordinary application Java")
    if hive_jvm.inspect_gradle_project(BASELINE) != freeze["verifier"]["jvm_profile"]:
        raise ValueError("Gradle project profile differs from frozen identity")
    spec = importlib.util.spec_from_file_location("rc1b_environment", ENV_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    environment = module.verify(environment_root)
    layout_files = verify_exact_relocation_layout(environment_root, module, freeze)
    if (environment["image_id"] != contract["verifier_image_id"] or
            environment["invoked_image_tag_id"] != contract["verifier_image_id"] or
            environment["selected_artifact_count"] != contract["selected_cache_files"]):
        raise ValueError("host-bound verifier environment differs")
    if freeze["nfrt"]["sha256"] != contract["nfrt_attestation_sha256"]:
        raise ValueError("NFRT attestation identity differs")
    return {"status": "PASS_HOST_BOUND", "commit": expected_commit,
            "baseline_sha256": contract["baseline_source_sha256"],
            "frozen_test_sha256": contract["frozen_j001_test_sha256"],
            "scope": list(scope), "environment": environment,
            "approved_runs_root": contract["approved_runs_root"],
            "sealed_layout_files": layout_files, "python_runtime": python_runtime,
            "promotion_authorization": "unavailable", "portable": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.environment_root, expected_commit=args.expected_commit), indent=2))
