"""Apparatus-only sealed-verifier resource measurement; never calls a model.

Each invocation uses the unchanged baseline and approved read-only caches.
The verifier still creates a fresh private container/stage. Docker stats and
cgroup counters are sampled externally while that container runs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSHOP = HERE / "workshop"
V1 = HERE.parent / "HIVE-ASTRA-001"
ORIGINAL_WORKSHOP = HERE.parent / "Nix-Workshop-v0.11.1-persistent-agents" / "Nix_Workshop_v0_11_1"
sys.path.insert(0, str(WORKSHOP))

from workshop import external_root, hive_jvm, hive_verifier  # noqa: E402


def _read_cgroup(name: str) -> dict:
    result = subprocess.run(
        ["docker", "exec", name, "sh", "-c",
         "for f in pids.current pids.peak pids.max pids.events memory.current memory.peak memory.max memory.events; "
         "do echo ====\"$f\"; cat /sys/fs/cgroup/\"$f\" 2>/dev/null || true; done"],
        capture_output=True, text=True, timeout=8,
    )
    if result.returncode:
        return {}
    pieces = result.stdout.split("====")
    return {part.splitlines()[0]: "\n".join(part.splitlines()[1:]).strip()
            for part in pieces if part.strip() and part.splitlines()}


def _monitor(done: threading.Event, samples: list[dict]) -> None:
    last_name = None
    while not done.is_set():
        try:
            listed = subprocess.run(
                ["docker", "ps", "--filter", "name=hive-verify-", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=8,
            )
            names = sorted(name for name in listed.stdout.splitlines()
                           if name.startswith("hive-verify-"))
            if names:
                name = names[0]
                if name != last_name or not samples or time.monotonic() - samples[-1]["at"] > 1.0:
                    counters = _read_cgroup(name)
                    if counters:
                        samples.append({"at": time.monotonic(), "container": name, "cgroup": counters})
                    last_name = name
        except (OSError, subprocess.TimeoutExpired):
            pass
        done.wait(0.35)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pids", type=int, choices=(384, 448, 512, 576, 640), default=384)
    parser.add_argument("--mode", choices=("targeted", "full"), default="targeted")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    freeze = json.loads((V1 / "FREEZE-v2.json").read_text(encoding="utf-8"))
    baseline = Path(freeze["baseline"]["root"])
    expected_hash = freeze["baseline"]["tree_sha256"]
    if external_root.tree_sha256(baseline) != expected_hash:
        raise RuntimeError("baseline hash mismatch before verifier diagnostic")
    cache = ORIGINAL_WORKSHOP / "hive_runs" / "approved-gradle-caches" / freeze["approved_cache"]["run_id"]
    os.environ["GRADLE_USER_HOME"] = str(cache.resolve(strict=True))
    profile = hive_jvm.inspect_gradle_project(baseline)
    frozen = json.loads((ORIGINAL_WORKSHOP / "hive_runs" / freeze["approved_cache"]["run_id"] /
                         "frozen-junit-manifest.json").read_text(encoding="utf-8"))
    image = subprocess.run(["docker", "image", "inspect", hive_verifier.DEFAULT_IMAGE,
                            "--format", "{{.Id}}"], capture_output=True, text=True, timeout=15)
    if image.returncode or image.stdout.strip() != freeze["verifier"]["image_id"]:
        raise RuntimeError("sealed verifier image differs from approved artifact")
    hive_jvm.gradle_cache_locations(profile)
    hive_jvm.external_build_input_locations(profile, baseline_sha256=expected_hash,
                                             container_image_id=image.stdout.strip())
    hive_verifier.JVM_CONTAINER_LIMITS["pids"] = args.pids
    done = threading.Event()
    samples: list[dict] = []
    monitor = threading.Thread(target=_monitor, args=(done, samples), daemon=True)
    started = time.monotonic()
    monitor.start()
    try:
        report = hive_verifier.run_isolated(
            baseline, args.mode, timeout=660 if args.mode == "full" else 300,
            external_root=True, frozen_junit_tests=frozen,
            expected_jvm_profile=profile, expected_external_baseline_sha256=expected_hash,
        )
    finally:
        done.set()
        monitor.join(timeout=10)
    after = external_root.tree_sha256(baseline)
    if after != expected_hash:
        raise RuntimeError("baseline hash changed during diagnostic")
    hive_jvm.external_build_input_locations(profile, baseline_sha256=expected_hash,
                                             container_image_id=image.stdout.strip())
    peak = max((int(row["cgroup"].get("pids.peak", "0") or 0) for row in samples), default=0)
    events = [row["cgroup"].get("pids.events", "") for row in samples]
    normalized_checks = []
    for item in report.get("checks", []):
        detail = item.get("detail")
        detail = detail if isinstance(detail, dict) else {"message": str(detail or "")}
        normalized_checks.append({
            "name": item.get("name"), "passed": item.get("passed"),
            "returncode": detail.get("returncode"),
            "report_error": detail.get("report_error"),
            "message": detail.get("message"),
            "test_cases": sum(t.get("tests", 0) for t in detail.get("tests", [])),
            "stderr_tail": detail.get("stderr_tail", "")[-1500:],
        })
    summary = {
        "label": args.label, "mode": args.mode, "pids_limit": args.pids,
        "image_id": image.stdout.strip(), "baseline_sha256": after,
        "network": (report.get("isolation") or {}).get("network"),
        "memory_limit": (report.get("isolation") or {}).get("limits", {}).get("memory"),
        "passed": report.get("passed"), "wall_seconds": round(time.monotonic() - started, 3),
        "sampled_pids_peak": peak, "sampled_pids_events_last": events[-1] if events else None,
        "samples": samples,
        "checks": normalized_checks,
    }
    destination = HERE / "diagnostics" / f"{args.label}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in {"samples", "checks"}},
                     sort_keys=True), flush=True)
    print(json.dumps(summary["checks"], sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
