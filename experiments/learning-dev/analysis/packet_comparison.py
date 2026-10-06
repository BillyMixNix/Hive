"""Freeze/check/run a descriptive packet comparison. No retries or auto-launch.

Uses a separately verified September 9 pricing guard; expiration blocks execution.
No command here installs credentials or updates old experiment records.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.contract_rerun import contracts
from analysis.contract_rerun_preflight import verify_study
from analysis.lesson_bank_v4 import attempt
from analysis.packet_adapter import recipient_adapter
from hive_learning.evaluate import strict_json
from hive_learning.lesson_study import save_json
from hive_learning.openai_adapter import load_api_key
from hive_learning.response_trace import ResponseTrace
from analysis.packet_spending import SpendingGuard, MODEL

ARMS = ("raw", "lessons", "packet")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    # Include the recovered controller as well as all experiment implementation.
    repo = ROOT.parent.parent
    return {p.relative_to(repo).as_posix(): sha(p) for p in sorted(repo.rglob("*.py"))
            if not any(x in {".git", "__pycache__", ".venv"} for x in p.parts)}


def schedule(study):
    rng = random.Random(509091)
    ids = [c["id"] for c in study["cases"]]
    if len(ids) != 15 or len(set(ids)) != 15:
        raise ValueError("expected 15 distinct reused tasks")
    rng.shuffle(ids)
    result = []
    for case in ids:
        arms = list(ARMS)
        rng.shuffle(arms)
        result.extend({"case_id": case, "arm": arm} for arm in arms)
    return result


def freeze(destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    study_path = ROOT/"examples/contract-rerun.json"
    preflight = verify_study(study_path)
    study = strict_json(study_path.read_bytes())
    plan = {"schema": "hive.packet-comparison.v1", "model": MODEL,
        "study_sha256": sha(study_path), "sources": sources(),
        "schedule": schedule(study), "new_budget_nano_usd": 5_000_000_000,
        "historical_budget_is_separate": True, "calls_per_recipient": 36,
        "interpretation": "descriptive reused-task state-presentation comparison",
        "preflight": preflight}
    with destination.open("x") as f:
        f.write(json.dumps(plan, indent=2)+"\n")
    return sha(destination)


def check(path, expected_sha):
    if sha(path) != expected_sha:
        raise ValueError("plan commitment mismatch")
    plan = strict_json(Path(path).read_bytes())
    study_path = ROOT/"examples/contract-rerun.json"
    study = strict_json(study_path.read_bytes())
    if (plan["schema"] != "hive.packet-comparison.v1" or plan["model"] != MODEL
            or plan["sources"] != sources() or plan["study_sha256"] != sha(study_path)
            or plan["schedule"] != schedule(study) or plan["calls_per_recipient"] != 36
            or plan["new_budget_nano_usd"] != 5_000_000_000
            or not plan["preflight"]["verified"]
            or plan["preflight"]["study_sha256"] != sha(study_path)):
        raise ValueError("frozen protocol or source changed")
    return plan, study


def run(plan_path, expected_sha, output):
    plan, study = check(plan_path, expected_sha)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    save_json(output/"plan.json", plan)
    # Exclusive adjacent lock survives output-directory changes and partial runs.
    lock = Path(str(plan_path)+".consumed")
    with lock.open("x") as f:
        f.write(expected_sha+"\n")
    report = {"status": "INCOMPLETE", "rows": [], "error_type": None}
    guard = None
    try:
        # Validate current pricing before loading a key or making any request.
        guard = SpendingGuard(output/"spending.jsonl", prior_upper_nano_usd=0)
        key = load_api_key()
        cases = {c["id"]: c for c in study["cases"]}
        for entry in plan["schedule"]:
            case, arm = cases[entry["case_id"]], entry["arm"]
            label = case["id"]+"-"+arm
            transport = output/"transport"/label
            transport.mkdir(parents=True)
            def observe(record):
                with (transport/"packets.jsonl").open("a") as f:
                    f.write(json.dumps(record)+"\n")
            adapter = recipient_adapter(MODEL, key, condition=arm, contracts=contracts(case),
                max_requests=36, spending=guard, observer=ResponseTrace(transport/"responses"),
                request_directory=transport/"requests", packet_observer=observe)
            guidance = study["lessons"] if arm == "lessons" else []
            record = attempt(adapter, case, guidance, arm, output/"recipients"/label, guard)
            report["rows"].append({**entry, "result": record})
            save_json(output/"report.json", report)
        report["status"] = "COMPLETED"
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        report["spending"] = guard.snapshot() if guard else None
        if guard:
            guard.close()
        save_json(output/"report.json", report)
        save_json(output/"checksums.json", {p.relative_to(output).as_posix(): sha(p)
            for p in sorted(output.rglob("*")) if p.is_file() and p.name != "checksums.json"})
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["freeze", "check", "run"])
    parser.add_argument("plan", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        print(freeze(args.plan))
    elif args.mode == "check":
        check(args.plan, args.sha256)
        print("COMMITMENT_VERIFIED")
    else:
        if args.output is None:
            parser.error("--output required")
        report = run(args.plan, args.sha256, args.output)
        print(json.dumps({"status": report["status"], "completed": len(report["rows"]), "error_type": report["error_type"]}))
        return 0 if report["status"] == "COMPLETED" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
