from __future__ import annotations

import argparse
import json
import subprocess
import sys
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from grow.core import ExperimentInvalid, stable_json, utc_now
from grow.experiment import Grow0Experiment
from grow.model import FixedOllamaInvoker


BASELINE_MAIN_SHA = "d0ee22781336331c1d387b7fafe37fcf744be60e"
BASELINE_TEST_COUNT = 335


def _run(command: list[str], cwd: Path) -> dict:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    return {
        "command": command,
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def run_prior_suite(repo_root: Path) -> dict:
    pytest_result = _run([sys.executable, "-m", "pytest", "-q"], repo_root)
    reliability_result = _run([sys.executable, "-u", "-m", "scripts.ci_gate"], repo_root)
    return {
        "passed": pytest_result["passed"] and reliability_result["passed"],
        "pytest": pytest_result,
        "reliability_gate": reliability_result,
    }


def run_prior_hive_suite_on_candidate(
    repo_root: Path, candidate_root: Path, mutable_paths: tuple[str, ...]
) -> dict:
    """Rerun the pre-GROW Hive capability suite on a disposable G1 overlay."""
    with tempfile.TemporaryDirectory(prefix="hive-grow0-prior-suite-") as tmp:
        validation_root = Path(tmp) / "repo"
        shutil.copytree(
            repo_root,
            validation_root,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", ".pytest_cache", ".venv", "backups", "_tmp_reliability_*"
            ),
        )
        shutil.rmtree(validation_root / "grow" / "state", ignore_errors=True)
        for rel in mutable_paths:
            source = candidate_root / rel
            destination = validation_root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        pytest_result = _run(
            [sys.executable, "-m", "pytest", "-q", "--ignore-glob=tests/test_grow0*.py"],
            validation_root,
        )
        reliability_result = _run(
            [sys.executable, "-u", "-m", "scripts.ci_gate"], validation_root
        )
        return {
            "passed": pytest_result["passed"] and reliability_result["passed"],
            "scope": "pre-GROW Hive tests plus reliability gate on candidate overlay",
            "pytest": pytest_result,
            "reliability_gate": reliability_result,
        }


def write_run_artifacts(repo_root: Path, result: dict) -> Path:
    stamp = utc_now().replace(":", "-")
    run_dir = repo_root / "grow" / "state" / "runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    mapping = {
        "result.json": result,
        "failure_packet.json": result.get("failure_packet"),
        "diagnosis.json": result.get("diagnosis"),
        "probe.json": result.get("probe"),
        "modification_manifest.json": result.get("manifest"),
        "evaluation.json": {"g0": result.get("g0"), "g1": result.get("g1")},
        "promotion.json": result.get("promotion"),
    }
    for name, payload in mapping.items():
        if payload is None:
            continue
        (run_dir / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return run_dir


def cmd_dry_run(args) -> int:
    repo_root = Path(args.repo_root).resolve()
    exp = Grow0Experiment(repo_root)
    baseline = {
        "passed": True,
        "source": "pinned-main-ci",
        "main_sha": BASELINE_MAIN_SHA,
        "pytest_passed": BASELINE_TEST_COUNT,
        "reliability_gate": "PASS",
    }
    _, snapshot = exp.freeze_g0(baseline_ref=BASELINE_MAIN_SHA, prior_suite=baseline)
    result = exp.dry_run_rejection(snapshot=snapshot)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("disposition") == "INVALID" and result.get("ancestor_unchanged") else 1


def cmd_real(args) -> int:
    repo_root = Path(args.repo_root).resolve()
    exp = Grow0Experiment(repo_root)
    if args.model_digest:
        exp.model_config = replace(exp.model_config, digest=args.model_digest)
    if not exp.model_config.digest or exp.model_config.digest.startswith("REQUIRE_"):
        print(json.dumps({
            "disposition": "INVALID",
            "reason": "A concrete Ollama model digest is required before a real lineage can be frozen.",
        }, indent=2))
        return 2

    baseline = run_prior_suite(repo_root)
    if not baseline["passed"]:
        print(json.dumps({"disposition": "INVALID", "reason": "baseline suite failed", "baseline": baseline}, indent=2))
        return 2

    _, snapshot = exp.freeze_g0(baseline_ref="local-working-tree", prior_suite=baseline)
    try:
        g0 = FixedOllamaInvoker(exp.model_config)
        modifier = FixedOllamaInvoker(exp.model_config)
        g1 = FixedOllamaInvoker(exp.model_config)
        result = exp.one_generation(
            snapshot=snapshot,
            invoke_g0=g0.invoke,
            invoke_modifier=modifier.invoke,
            invoke_g1=g1.invoke,
            prior_suite_g1=lambda candidate_root: run_prior_hive_suite_on_candidate(
                repo_root, candidate_root, exp.mutable_paths
            ),
        )
        result["metrics"] = {
            "g0": g0.metrics(),
            "modifier": modifier.metrics(),
            "g1": g1.metrics(),
            "total_model_calls": g0.calls + modifier.calls + g1.calls,
            "total_input_tokens": g0.input_tokens + modifier.input_tokens + g1.input_tokens,
            "total_output_tokens": g0.output_tokens + modifier.output_tokens + g1.output_tokens,
            "total_wall_time": g0.wall_time + modifier.wall_time + g1.wall_time,
        }
        run_dir = write_run_artifacts(repo_root, result)
        result["artifact_dir"] = str(run_dir.relative_to(repo_root))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("record", {}).get("disposition") == "PROMOTED" else 1
    except ExperimentInvalid as exc:
        result = {"disposition": "INVALID", "reason": str(exc)}
        write_run_artifacts(repo_root, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GROW-0 failure-driven workshop evolution experiment")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dry-run", help="mechanically demonstrate forbidden candidate writes are rejected")
    real = sub.add_parser("real", help="run one real G0 -> G1 lineage with a pinned local Ollama model")
    real.add_argument("--model-digest", help="exact digest for the configured qwen2.5-coder:7b model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dry-run":
        return cmd_dry_run(args)
    if args.command == "real":
        return cmd_real(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
