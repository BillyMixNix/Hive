"""Compile novel frozen JUnit against the unchanged baseline; expected red gate.

No implementation or model is supplied. Missing target APIs are expected;
syntax, imports, and unrelated Java errors are not.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "workshop"))

from workshop import external_root, hive_jvm, hive_verifier  # noqa: E402


def main() -> int:
    historical = json.loads((HERE.parent / "HIVE-ASTRA-001" / "FREEZE-v2.json").read_text(encoding="utf-8"))
    baseline = Path(historical["baseline"]["root"])
    baseline_hash = historical["baseline"]["tree_sha256"]
    if external_root.tree_sha256(baseline) != baseline_hash:
        raise RuntimeError("baseline changed before novel-test validation")
    cache = (HERE.parent / "Nix-Workshop-v0.11.1-persistent-agents" / "Nix_Workshop_v0_11_1" /
             "hive_runs" / "approved-gradle-caches" / historical["approved_cache"]["run_id"])
    os.environ["GRADLE_USER_HOME"] = str(cache.resolve(strict=True))
    profile = hive_jvm.inspect_gradle_project(baseline)
    specs = []
    for source_path in sorted((HERE / "novel-frozen-tests").glob("*.java")):
        source = source_path.read_text(encoding="utf-8")
        package = re.search(r"(?m)^package\s+([\w.]+)\s*;", source)
        if not package:
            raise ValueError(f"missing package in {source_path}")
        specs.append({
            "path": "src/test/java/" + package.group(1).replace(".", "/") + "/" + source_path.name,
            "class_name": package.group(1) + "." + source_path.stem,
            "expected_cases": 1, "source": source,
        })
    if len(specs) != 8:
        raise ValueError("expected exactly eight novel acceptance tests")
    frozen = hive_jvm.freeze_junit_tests(baseline, specs)
    run_dir = HERE / "diagnostics" / "novel-test-red-gate"
    if run_dir.exists():
        raise RuntimeError("novel-test validation evidence already exists")
    frozen = hive_jvm.store_frozen_junit_tests(frozen, run_dir)
    report = hive_verifier.targeted_verify_isolated(
        baseline, [], external_root=True, frozen_junit_tests=frozen,
        expected_jvm_profile=profile, expected_external_baseline_sha256=baseline_hash,
    )
    if external_root.tree_sha256(baseline) != baseline_hash:
        raise RuntimeError("baseline changed during novel-test validation")
    run_dir.joinpath("report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    checks = report.get("checks") or []
    targeted = next((item for item in checks if item.get("name") == "frozen_junit_acceptance"), {})
    detail = targeted.get("detail") or {}
    text = (detail.get("stdout_tail", "") + "\n" + detail.get("stderr_tail", "")) if isinstance(detail, dict) else str(detail)
    missing_symbols = text.count("cannot find symbol")
    print(json.dumps({"passed": report.get("passed"), "network": (report.get("isolation") or {}).get("network"),
                      "test_sources": len(specs), "missing_symbol_diagnostics": missing_symbols,
                      "other_error_excerpt": text[-2500:], "evidence": str(run_dir / "report.json")}), flush=True)
    return 0 if not report.get("passed") and missing_symbols >= len(specs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
