"""Future, explicitly authorized one-cell host-bound replay entrypoint.

Importing this module makes no provider request. The caller still supplies a
model callable, but only after the full host contract succeeds. No apply path
exists. HIVE-RECOVERY-001C must never invoke this entrypoint.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
from pathlib import Path

from .controller import CandidateSpec, produce_candidate
from .legacy.workshop import hive_verifier

_REPLAY_LOCK = threading.Lock()


async def run_host_bound_j001(*, expected_commit: str, environment_root: Path,
                              runs_root: Path, local_model: str, agent_call):
    if not _REPLAY_LOCK.acquire(blocking=False):
        raise RuntimeError("a host-bound replay is already active in this process")
    try:
        return await _run_locked(expected_commit=expected_commit, environment_root=environment_root,
                                 runs_root=runs_root, local_model=local_model, agent_call=agent_call)
    finally:
        _REPLAY_LOCK.release()


async def _run_locked(*, expected_commit: str, environment_root: Path,
                      runs_root: Path, local_model: str, agent_call):
    root = Path(__file__).resolve().parents[1]
    check_file = root / "recovery/rc1-replay/verify_replay.py"
    module_spec = importlib.util.spec_from_file_location("rc1_replay_contract", check_file)
    checker = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(checker)
    qualified = checker.verify(environment_root, expected_commit=expected_commit)
    root = root.resolve(strict=True)
    baseline = checker.BASELINE.resolve(strict=True)
    if not isinstance(runs_root, Path) or not runs_root.is_absolute():
        raise ValueError("replay run storage must be an absolute path")
    if runs_root.is_symlink() or (hasattr(runs_root, "is_junction") and runs_root.is_junction()):
        raise ValueError("replay run storage is a link or junction")
    runs_root = runs_root.resolve(strict=False)
    if runs_root != Path(qualified["approved_runs_root"]).resolve(strict=False):
        raise ValueError("replay run storage differs from preapproved one-shot root")
    if (runs_root == root or root in runs_root.parents or runs_root in root.parents or
            runs_root == baseline or baseline in runs_root.parents or runs_root in baseline.parents):
        raise ValueError("replay run storage overlaps source or frozen baseline")
    runs_root.mkdir(parents=True, exist_ok=True)
    # Atomic persistent claim enforces the one-replay envelope across process
    # restarts. A failed provider call still consumes the authorized attempt.
    claim = runs_root / ".rc1c-host-bound-replay-claim.json"
    with claim.open("x", encoding="utf-8") as stream:
        json.dump({"task_id": "J001", "commit": expected_commit,
                   "image_id": qualified["environment"]["image_id"],
                   "claimed_unix_seconds": time.time()}, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    freeze = json.loads(checker.FREEZE.read_bytes())
    task = next(item for item in freeze["tasks"] if item["id"] == "J001")
    source = (checker.HIDDEN / task["test_filename"]).read_text(encoding="utf-8")
    spec = CandidateSpec(
        baseline_root=checker.BASELINE, runs_root=runs_root,
        request=task["request"], local_model=local_model,
        allowed_write_files=tuple(qualified["scope"]),
        frozen_junit_tests=({"path": task["test_path"], "class_name": task["test_class"],
                             "expected_cases": task["test_cases"], "source": source},),
    )
    previous = {key: os.environ.get(key) for key in
                ("GRADLE_USER_HOME", "HIVE_NFRT_SEED_MANIFEST", "HIVE_NFRT_SEED_SHA256", "NIX_HIVE_VERIFIER_IMAGE")}
    original_image = hive_verifier.DEFAULT_IMAGE
    env = qualified["environment"]
    # The historical verifier would otherwise inspect a tag and later launch
    # that tag. Launching by verified immutable image ID closes the tag race.
    image_id = env["image_id"]
    try:
        os.environ["GRADLE_USER_HOME"] = env["cache_root"]
        os.environ["HIVE_NFRT_SEED_MANIFEST"] = env["seed_manifest"]
        os.environ["HIVE_NFRT_SEED_SHA256"] = freeze["nfrt"]["sha256"]
        os.environ["NIX_HIVE_VERIFIER_IMAGE"] = image_id
        hive_verifier.DEFAULT_IMAGE = image_id
        return await produce_candidate(spec, agent_call)
    finally:
        hive_verifier.DEFAULT_IMAGE = original_image
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
