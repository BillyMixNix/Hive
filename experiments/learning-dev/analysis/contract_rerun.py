"""One authorized descriptive rerun of the fixed 15-case comparison.

The retained bank is unchanged. Caller declarations apply identically to all
arms; consuming a single-use iterator is intentionally outside this gate.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.cache_contract_audit import cache_audit_tests
from analysis.checkpoint_followon import BANK_SHA256, sources as original_sources
from analysis.contract_checked_hive import ContractCheckedHive
from analysis.indexed_checkpoint import IndexedCheckpointHive
from analysis.lesson_bank_v4 import attempt, checked, total_spending
from analysis.public_contracts import InputPreservation, PublicContractGate
from hive_learning.cloud_trial import allowed_launch
from hive_learning.evaluate import strict_json
from hive_learning.ledger import digest
from hive_learning.lesson_study import ARMS, compact, neutral_lesson, save_json
from hive_learning.openai_adapter import load_api_key
from hive_learning.response_trace import ResponseTrace
from hive_learning.spending import LIMIT_NUSD, MODEL, SpendingGuard, VALID_UNTIL

PRIOR_NUSD = 3_469_597_600
ORIGINAL_STUDY_SHA256 = "e5ad65904e74ede49e94f66dc0ac4779a36e741223d56b6b63b88292e1e74527"
ORIGINAL_RUNTIME_SHA256 = "c6edd5410e93f4c57bd24519dec9deb475f261514093769f28bbdcec043e98c0"
LAUNCH_MESSAGE = "Run authorized Hive public contract comparison rerun"
WORKFLOW = ".github/workflows/hive-contract-rerun-20260908.yml"

# Explicit caller-owned declarations. Nothing is inferred from lesson text.
DECLARATIONS = {
    "checkpoint_permuted_columns": ("process", ("keys", "values", "order")),
    "checkpoint_absolute_priority": ("process", ("keys", "values")),
    "checkpoint_stable_partition": ("process", ("keys", "values", "flags")),
    "checkpoint_top_k_pairs": ("process", ("keys", "values", "limit")),
    "checkpoint_factor_cache": ("Memo.fetch", ("name", "factor", "values")),
    "checkpoint_operation_cache": ("Memo.fetch", ("name", "mode", "values")),
    "checkpoint_ambient_policy": ("Memo.fetch", ("name", "values")),
    "checkpoint_shared_namespace": ("Memo.fetch", ("name", "revision", "values")),
    "checkpoint_explicit_zero_63": ("configure_63", ("defaults", "overrides")),
    "checkpoint_snapshot_alias_64": ("Journal_64.__init__", ("settings",)),
    "checkpoint_current_input_65": ("Converter_65.buckets", ("volume", "current_width")),
}


def contracts(case):
    if case["id"] not in DECLARATIONS:
        if case["family"] != "single_pass":
            raise ValueError("undeclared non-iterator case")
        return ()
    symbol, arguments = DECLARATIONS[case["id"]]
    paths = [p for p in case["files"] if not Path(p).name.startswith("test_")]
    if len(paths) != 1:
        raise ValueError("ambiguous source")
    return (InputPreservation(paths[0], symbol, arguments),)


def sources():
    frozen = original_sources()
    if digest(frozen) != ORIGINAL_RUNTIME_SHA256:
        raise ValueError("the earlier runtime changed")
    names = ["analysis/contract_rerun.py", "analysis/contract_rerun_preflight.py",
             "analysis/contract_checked_hive.py", "analysis/public_contracts.py",
             "analysis/cache_contract_audit.py"]
    return frozen | {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names} | {
        "repository:" + WORKFLOW: hashlib.sha256((ROOT.parent.parent/WORKFLOW).read_bytes()).hexdigest()}


def schedule(study):
    rng = random.Random(study["seed"])
    cases = list(study["cases"])
    rng.shuffle(cases)
    result = []
    # Keep all three arms adjacent for each task, with frozen randomized order.
    for case in cases:
        arms = list(ARMS)
        rng.shuffle(arms)
        result.extend((case, arm) for arm in arms)
    return result


def read_plan():
    plan = strict_json((ROOT/"contract-rerun-plan.json").read_bytes())
    if (plan["launch_message"] != LAUNCH_MESSAGE
            or not re.fullmatch(r"[a-f0-9]{40}", plan["launch_parent"])
            or plan["source_sha256"] != digest(sources())):
        raise ValueError("invalid frozen launch")
    study = checked(plan["study"], plan["study_sha256"])
    preflight = checked(plan["preflight"], plan["preflight_sha256"])
    original = checked("examples/checkpoint-followon.json", ORIGINAL_STUDY_SHA256)
    expected = []
    for case in original["cases"]:
        expected.append({**case, "protected_tests": {**case["protected_tests"], **cache_audit_tests(case)}})
    if (study["schema"] != "hive.contract-rerun.v1" or study["model"] != MODEL
            or study["calls_per_recipient"] != 36 or study["cases"] != expected
            or study["deadline_seconds"] != 3000 or study["seed"] != 508918
            or study["lessons"] != original["lessons"] or digest(study["lessons"]) != BANK_SHA256
            or preflight["study_sha256"] != plan["study_sha256"] or not preflight["verified"]
            or study["references_sha256"] != original["references_sha256"]
            or preflight["runtime_sha256"] != plan["source_sha256"]):
        raise ValueError("study, lessons, audit or preflight changed")
    if len(expected) != 15 or len({c["id"] for c in expected}) != 15:
        raise ValueError("incorrect sample")
    prior = checked(plan["prior_report"], plan["prior_report_sha256"])
    if (prior["status"] != "COMPLETED" or prior["spending"]["total_upper_nano_usd"] != PRIOR_NUSD
            or prior["spending"]["unresolved_reservation_nano_usd"]
            or prior["episode_id"] != "bf7e9f1b013c72d5703fbc9e766c843ef013e1fe84cce25d8e768a5695de301a"):
        raise ValueError("cumulative predecessor differs")
    return plan, study, prior


class RerunSpendingGuard(SpendingGuard):
    def __init__(self, *args, deadline, **kwargs):
        self.deadline = deadline
        super().__init__(*args, **kwargs)

    def reserve(self):
        # Check before each request, including requests within one recipient.
        if datetime.now(timezone.utc) >= VALID_UNTIL or time.monotonic() >= self.deadline:
            raise RuntimeError("rerun deadline or pricing validity reached")
        return super().reserve()


def describe(state, study):
    rows = state["trials"]
    target = {(c["id"], arm) for c in study["cases"] for arm in ARMS}
    keys = [(r["case_id"], r["arm"]) for r in rows]
    base = {"confirmatory_gain_claim_allowed": False, "completed_recipients": len(rows),
            "expected_recipients": len(target), "reused_tasks": True}
    if len(keys) != len(set(keys)) or not set(keys) <= target or any(not r["integrity_valid"] for r in rows):
        return {**base, "verdict": "INVALID"}
    if set(keys) != target:
        return {**base, "verdict": "INCOMPLETE"}
    by = dict(zip(keys, rows))
    transfer = [c["id"] for c in study["cases"] if c["split"] == "confirmation"]
    retention = [c["id"] for c in study["cases"] if c["split"] == "retention"]
    score = lambda r: r["usage"]["calls"] if r["passed"] else 36
    comparisons = {}
    for arm in ("baseline", "neutral"):
        differences = [score(by[c, arm])-score(by[c, "lesson"]) for c in transfer]
        control = sum(score(by[c, arm]) for c in transfer)
        treatment = sum(score(by[c, "lesson"]) for c in transfer)
        comparisons[arm] = {"control_penalized_calls": control, "lesson_penalized_calls": treatment,
            "relative_reduction": 1-treatment/control, "paired_differences": differences,
            "lesson_lower_effort": sum(d > 0 for d in differences),
            "lesson_higher_effort": sum(d < 0 for d in differences), "ties": sum(d == 0 for d in differences)}
    return {**base, "verdict": "DESCRIPTIVE_ONLY",
        "transfer_successes": {a: sum(by[c, a]["passed"] for c in transfer) for a in ARMS},
        "retention_successes": {a: sum(by[c, a]["passed"] for c in retention) for a in ARMS},
        "false_completions": {a: sum(r["controller_decision"] == "SATISFIED" and not r["passed"]
                                     for r in rows if r["arm"] == a) for a in ARMS},
        "comparisons": comparisons,
        "interpretation": "Same previously evaluated cases and frozen model-generated lessons; no new-task confirmation, weight training, pooled significance test or automatic retry."}


def main():
    plan, study, prior = read_plan()
    event = strict_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    if not allowed_launch({**os.environ, "HIVE_LAUNCH_PARENT": plan["launch_parent"]}, event, LAUNCH_MESSAGE):
        os.environ.pop("OPENAI_API_KEY", None)
        return 2
    if sys.argv[1:] == ["--check"]:
        print(json.dumps({"status": "COMMITMENT_VERIFIED", "recipients": 45, "prior_upper_nano_usd": PRIOR_NUSD}))
        return 0
    output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=False)
    manifest = {"plan": plan, "run_id": os.environ["GITHUB_RUN_ID"], "commit": os.environ["GITHUB_SHA"],
                "source_hashes": sources(), "prior_episode": prior["episode_id"], "bank_sha256": BANK_SHA256}
    save_json(output/"manifest.json", manifest)
    report = {"episode_id": digest(manifest), "scope": "descriptive_public_contract_rerun",
              "study_sha256": plan["study_sha256"], "source_sha256": plan["source_sha256"],
              "continued_after": prior["episode_id"], "status": "INVALID"}
    ordered = schedule(study)
    state = {"schema": "hive.contract-rerun.state.v1", "study_sha256": plan["study_sha256"],
             "bank_sha256": BANK_SHA256, "trials": [],
             "schedule": [{"case_id": c["id"], "arm": a} for c, a in ordered]}
    save_json(output/"study-state.json", state)
    snapshots, transport = [], []
    cumulative = PRIOR_NUSD
    deadline = time.monotonic() + study["deadline_seconds"]
    try:
        key = load_api_key()
        for case, arm in ordered:
            if time.monotonic() >= deadline or datetime.now(timezone.utc) >= VALID_UNTIL:
                raise RuntimeError("rerun deadline reached")
            label = case["id"] + "-" + arm
            directory = output/"transport"/label
            directory.mkdir(parents=True, exist_ok=False)
            guard = RerunSpendingGuard(directory/"spending.jsonl", prior_upper_nano_usd=cumulative, deadline=deadline)
            adapter = None
            try:
                if cumulative + guard.reservation > LIMIT_NUSD:
                    raise RuntimeError("remaining budget cannot reserve another request")
                declarations = contracts(case)
                options = {"contracts": declarations} if declarations else {}
                cls = ContractCheckedHive if declarations else IndexedCheckpointHive
                adapter = cls(MODEL, key, max_requests=36, spending=guard,
                    observer=ResponseTrace(directory/"responses"), request_directory=directory/"requests",
                    seed=study["seed"], **options)
                guidance = [] if arm == "baseline" else study["lessons"] if arm == "lesson" else [neutral_lesson(x) for x in study["lessons"]]
                record = attempt(adapter, case, guidance, arm, output/"recipients"/label, guard)
                row = compact(record)
                if "outcome" in record:
                    row["outcome"] = record["outcome"]
                row["adapter"] = cls.__name__
                row["checkpoint_count"] = sum(len(m.checkpoints) for m in adapter.meters)
                row["public_contract_checks"] = record.get("controller", {}).get("public_contract_checks", [])
                state["trials"].append(row)
                save_json(output/"study-state.json", state)
                print("HIVE_CONTRACT_PROGRESS " + json.dumps({"case": case["id"], "arm": arm,
                    "passed": record["passed"], "calls": record["usage"]["calls"]}), flush=True)
            finally:
                snap = guard.snapshot(); snapshots.append(snap); cumulative = snap["total_upper_nano_usd"]
                guard.close()
                meters = adapter.meters if adapter is not None else []
                save_json(directory/"checkpoints.json", [c for m in meters for c in m.checkpoints])
                transport.append({"recipient": label, "meters": adapter.observed_usage() if adapter else [], "spending": snap})
                save_json(output/"accounting.json", {"recipients": transport, "spending": total_spending(PRIOR_NUSD, snapshots)})
        report["status"] = "COMPLETED"
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        report["spending"] = total_spending(PRIOR_NUSD, snapshots)
        report["transport_usage"] = transport
    state["assessment"] = describe(state, study)
    report["assessment"] = state["assessment"]
    save_json(output/"study-state.json", state)
    report["study_state_sha256"] = hashlib.sha256((output/"study-state.json").read_bytes()).hexdigest()
    report["http_errors"] = [strict_json(p.read_bytes()) for p in sorted(output.glob("**/http-error.json"))]
    save_json(output/"report.json", report)
    save_json(output/"checksums.json", {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(output.rglob("*")) if p.is_file()})
    print("HIVE_CONTRACT_REPORT " + json.dumps({k: v for k, v in report.items() if k != "transport_usage"}), flush=True)
    return 0 if report["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
