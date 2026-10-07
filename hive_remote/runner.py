"""Manual remote infrastructure commands. Real coding launch is deliberately blocked."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from .providers import Budget, Limits, OpenAIProvider, ProviderFailure, encode, sha
from .qualification import ROOT, FREEZE, controller_identity, exact_checkout, inventory, require_remote_qualification

SMOKE_PROMPT = "Infrastructure connection test only. Return exactly HIVE_API_OK and nothing else."


def save(path: Path, value):
    with path.open("xb") as stream:
        stream.write(encode(value) + b"\n")


def evidence_index(folder: Path):
    rows = [{"path": p.relative_to(folder).as_posix(), "sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
            for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "evidence-index.json"]
    save(folder / "evidence-index.json", {"schema_version": 1, "files": rows})


def new_run(output_root: Path) -> Path:
    if not output_root.is_absolute():
        raise ValueError("evidence root must be absolute")
    root = output_root.resolve()
    if root == ROOT or ROOT in root.parents or root in ROOT.parents:
        raise ValueError("evidence storage overlaps the repository")
    # No caller run IDs, shell expressions, or overwriting prior experiment evidence.
    root.mkdir(parents=True, exist_ok=True)
    folder = root / ("HIVE-REMOTE-API-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:12])
    folder.mkdir()
    return folder


async def smoke(folder: Path, *, model: str, reasoning_effort: str | None, limits: Limits, transport=None) -> dict:
    credential = os.environ.get("OPENAI_API_KEY", "")
    safe_model = model if not credential or credential not in model else None
    report = {"schema_version": 1, "run_id": folder.name, "experiment_family": "PROVIDER_INFRASTRUCTURE_SMOKE",
              "provider": "openai_responses", "configured_model": safe_model,
              "software_generation_success": False, "candidate_execution": False,
              "verifier_execution": False, "promotion_authorization": "unavailable"}
    budget = Budget(limits, folder / "provider")
    try:
        kwargs = {} if transport is None else {"transport": transport}
        provider = OpenAIProvider(model=model, budget=budget, reasoning_effort=reasoning_effort, **kwargs)
        result = await provider("smoke", SMOKE_PROMPT)
        report.update(status="PASS" if result.strip() == "HIVE_API_OK" else "UNEXPECTED_RESPONSE",
                      secret_removed_from_process_environment="OPENAI_API_KEY" not in os.environ,
                      secret_isolation_evidence="PAYLOAD_AND_ARTIFACT_BOUNDARY_ONLY; NO LIVE CANDIDATE/VERIFIER PROBE")
    except ProviderFailure as exc:
        report.update(status="UNAVAILABLE" if exc.classification == "API_KEY_UNAVAILABLE" else "FAIL",
                      failure_class=exc.classification)
        budget.halt(exc.classification)
    report["accounting"] = budget.summary()
    save(folder / "HIVE_REMOTE_API_SMOKE.json", report)
    return report


def prepare(report: dict) -> dict:
    task = next(t for t in json.loads(FREEZE.read_bytes())["tasks"] if t["id"] == "J001")
    return {"schema_version": 1, "experiment_family": "HIVE-REMOTE-API-J001-PREPARED",
            "status": "PREPARED_BLOCKED", "task_id": "J001", "git_commit": report["git_commit"],
            "controller_identity": report["components"]["controller"], "request": task["request"],
            "request_sha256": task["request_sha256"], "allowed_write_files": task["files"],
            "frozen_acceptance_sha256": task["test_sha256"], "frozen_cases": task["test_cases"],
            "targeted_timeout_seconds": 240, "full_timeout_seconds": 660,
            "required_full_commands": ["clean", "build", "runGameTestServer", "runQuestTestServer", "packTestJar"],
            "proposed_new_paired_budget": {"max_model_calls": 12, "max_input_tokens": 60000,
                                          "max_output_tokens": 4096, "max_total_tokens": 250000,
                                          "max_experiment_seconds": 3600, "provider_timeout_seconds": 900,
                                          "status": "PROPOSED_NOT_AUTHORIZED; both arms must use the same limits"},
            "model_calls": 0, "authorization": "NEW_SEPARATE_AUTHORIZATION_REQUIRED",
            "qualification_blockers": report["blockers"], "promotion_authorization": "unavailable",
            "comparison": "New paired local/API trials must freeze identical budgets and request policies. Historical factorial cells are not interchangeable."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "smoke", "prepare", "experiment"))
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", ""))
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--max-model-calls", type=int, default=1)
    parser.add_argument("--max-output-tokens", type=int, default=32)
    parser.add_argument("--max-input-tokens", type=int, default=512)
    parser.add_argument("--max-total-tokens", type=int, default=1024)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--max-cost-usd")
    parser.add_argument("--input-usd-per-million")
    parser.add_argument("--output-usd-per-million")
    args = parser.parse_args(argv)
    exact_checkout(args.expected_commit)
    folder = new_run(args.output_root)
    common = {"run_id": folder.name, "git_commit": args.expected_commit, "started_unix": time.time(),
              "controller_identity": controller_identity(), "mode": args.mode}
    save(folder / "run-identity.json", common)
    try:
        if args.mode == "smoke":
            # Infrastructure smoke is always one generation and at most 64 output
            # tokens. The model stays operator-configured; no guessed model alias.
            if args.max_model_calls != 1 or not 16 <= args.max_output_tokens <= 64 or args.max_input_tokens > 512 or args.max_total_tokens > 1024 or args.timeout_seconds > 60:
                raise ProviderFailure("SMOKE_BUDGET_TOO_LARGE")
            limits = Limits(max_model_calls=args.max_model_calls, max_output_tokens=args.max_output_tokens,
                            max_input_tokens=args.max_input_tokens, max_total_tokens=args.max_total_tokens,
                            timeout_seconds=args.timeout_seconds, max_cost_usd=args.max_cost_usd,
                            input_usd_per_million=args.input_usd_per_million,
                            output_usd_per_million=args.output_usd_per_million)
            value = asyncio.run(smoke(folder, model=args.model, reasoning_effort=args.reasoning_effort, limits=limits))
            code = 0 if value["status"] == "PASS" else 2
        else:
            value = inventory(expected_commit=args.expected_commit, environment_root=args.environment_root)
            save(folder / "HIVE_REMOTE_API_QUALIFICATION.json", value)
            if args.mode == "prepare":
                save(folder / "J001-PREPARED.json", prepare(value))
            if args.mode == "experiment":
                # Before key loading, provider construction, candidate staging,
                # or consuming the existing RECOVERY-002 one-shot claim.
                require_remote_qualification(value)
            code = 2  # unavailable qualification is never a successful experiment
        save(folder / "outcome.json", {"status": "INFRASTRUCTURE_PASS" if code == 0 else "BLOCKED_OR_FAILED",
                                      "software_verified": False, "promotion_authorization": "unavailable"})
    except Exception as exc:
        classification = exc.classification if isinstance(exc, ProviderFailure) else "REMOTE_APPARATUS_UNQUALIFIED_OR_SETUP_FAILURE"
        budget_file = folder / "provider/budget.json"
        accounting = json.loads(budget_file.read_bytes()) if budget_file.exists() else {"model_call_count": 0}
        save(folder / "outcome.json", {"status": "BLOCKED", "failure_class": classification,
                                      "accounting": accounting, "software_verified": False,
                                      "promotion_authorization": "unavailable"})
        code = 2
    finally:
        evidence_index(folder)
    print(json.dumps({"evidence_directory": str(folder), "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
