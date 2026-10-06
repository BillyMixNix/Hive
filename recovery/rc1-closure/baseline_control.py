"""Model-free J001 baseline control against an explicitly verified fresh cache root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hive_canonical.legacy.workshop import external_root, hive_jvm, hive_verifier  # noqa: E402


def run(fresh_root: Path) -> dict:
    env = verify_environment(fresh_root)
    freeze = json.loads((ROOT / "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1/FREEZE.json").read_bytes())
    baseline = ROOT / "recovery/workshop-source-20261006/external/m3.2-baseline"
    task = next(item for item in freeze["tasks"] if item["id"] == "J001")
    hidden = ROOT / "recovery/workshop-source-20261006/external/historical-work/HIVE-FACTORIAL-001/hidden-tests" / task["test_filename"]
    if hashlib.sha256(hidden.read_bytes()).hexdigest() != task["test_sha256"]:
        raise ValueError("frozen J001 source identity mismatch")
    baseline_sha = external_root.tree_sha256(baseline)
    if baseline_sha != freeze["baseline"]["sha256"]:
        raise ValueError("frozen baseline identity mismatch")
    profile = hive_jvm.inspect_gradle_project(baseline)
    if profile != freeze["verifier"]["jvm_profile"]:
        raise ValueError("frozen Gradle profile mismatch")
    os.environ["GRADLE_USER_HOME"] = env["cache_root"]
    os.environ["HIVE_NFRT_SEED_MANIFEST"] = env["seed_manifest"]
    os.environ["HIVE_NFRT_SEED_SHA256"] = freeze["nfrt"]["sha256"]
    frozen = hive_jvm.freeze_junit_tests(baseline, [{
        "path": task["test_path"], "class_name": task["test_class"],
        "expected_cases": task["test_cases"], "source": hidden.read_text(encoding="utf-8"),
    }])
    with tempfile.TemporaryDirectory(prefix="rc1b-j001-baseline-") as temp:
        metadata = hive_jvm.store_frozen_junit_tests(frozen, Path(temp))
        started = time.monotonic()
        result = hive_verifier.run_isolated(
            baseline, "targeted", [], timeout=240, external_root=True,
            frozen_junit_tests=metadata, expected_jvm_profile=profile,
            expected_external_baseline_sha256=baseline_sha,
            diagnostics_dir=Path(temp) / "diagnostics",
        )
        elapsed = round(time.monotonic() - started, 3)
        summary = {
            "classification": "FRESH_BASELINE_CONTROL",
            "passed": result.get("passed"), "elapsed_seconds": elapsed,
            "timeout": bool((result.get("diagnostics") or {}).get("timed_out")),
            "checks": result.get("checks"), "diagnostics": result.get("diagnostics"),
            "baseline_sha256": baseline_sha, "frozen_test_sha256": task["test_sha256"],
            "environment": env,
        }
        if result.get("passed") is True:
            raise RuntimeError("INTEGRITY_FAILURE: unchanged J001 baseline unexpectedly passed")
        return summary


if __name__ == "__main__":
    import importlib.util
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    module = ROOT / "recovery/rc1-closure/environment/verify_environment.py"
    spec = importlib.util.spec_from_file_location("verify_environment", module)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    verify_environment = loaded.verify
    value = run(args.fresh_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": value["passed"], "elapsed_seconds": value["elapsed_seconds"],
                      "check_names": [x.get("name") for x in value["checks"]]}))
