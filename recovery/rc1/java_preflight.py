"""Model-free frozen baseline JUnit preflight using the historical approved cache.

This is a diagnostic runner, not a task trial. It never sends model requests and
does not edit the baseline or frozen test. Only bounded result metadata prints.
"""

from __future__ import annotations

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


def run() -> dict:
    freeze = json.loads((ROOT / "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1/FREEZE.json").read_bytes())
    baseline = ROOT / "recovery/workshop-source-20261006/external/m3.2-baseline"
    task = next(item for item in freeze["tasks"] if item["id"] == "J001")
    hidden = ROOT / "recovery/workshop-source-20261006/external/historical-work/HIVE-FACTORIAL-001/hidden-tests" / task["test_filename"]
    if hashlib.sha256(hidden.read_bytes()).hexdigest() != task["test_sha256"]:
        raise ValueError("frozen JUnit source differs from historical identity")
    baseline_sha = external_root.tree_sha256(baseline)
    if baseline_sha != freeze["baseline"]["sha256"]:
        raise ValueError("baseline differs from historical identity")
    profile = hive_jvm.inspect_gradle_project(baseline)
    if profile != freeze["verifier"]["jvm_profile"]:
        raise ValueError("Gradle profile differs from historical identity")
    cache = Path(freeze["verifier"]["approved_cache_root"])
    manifest = Path(freeze["nfrt"]["manifest"])
    if not cache.is_dir() or not manifest.is_file():
        return {"classification": "ENVIRONMENT_MISSING", "reason": "approved cache or NFRT manifest absent"}
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != freeze["nfrt"]["sha256"]:
        raise ValueError("NFRT attestation manifest differs from frozen identity")
    os.environ["GRADLE_USER_HOME"] = str(cache)
    os.environ["HIVE_NFRT_SEED_MANIFEST"] = str(manifest)
    os.environ["HIVE_NFRT_SEED_SHA256"] = freeze["nfrt"]["sha256"]
    frozen = hive_jvm.freeze_junit_tests(baseline, [{
        "path": task["test_path"], "class_name": task["test_class"],
        "expected_cases": task["test_cases"], "source": hidden.read_text(encoding="utf-8"),
    }])
    with tempfile.TemporaryDirectory(prefix="rc1-java-preflight-") as temp:
        metadata = hive_jvm.store_frozen_junit_tests(frozen, Path(temp))
        started = time.monotonic()
        result = hive_verifier.run_isolated(
            baseline, "targeted", [], timeout=240, external_root=True,
            frozen_junit_tests=metadata, expected_jvm_profile=profile,
            expected_external_baseline_sha256=baseline_sha,
            diagnostics_dir=Path(temp) / "diagnostics",
        )
        return {
            "classification": "VERIFIER_RETURNED",
            "passed": result.get("passed"),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "checks": [{"name": item.get("name"), "passed": item.get("passed"),
                        "detail_prefix": str(item.get("detail", ""))[:500]}
                       for item in result.get("checks", [])],
            "baseline_sha256": baseline_sha,
            "frozen_test_sha256": task["test_sha256"],
            "diagnostics_last_phase": (result.get("diagnostics") or {}).get("last_observed_phase"),
        }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
