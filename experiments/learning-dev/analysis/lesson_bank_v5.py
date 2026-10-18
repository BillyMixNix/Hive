"""One new comparison after the user's explicit redesign/retest authorization.

Fresh authored tasks, unchanged retained bank, all arms share full callable context
and a structured advisory checkpoint. All previous spend and failures are carried.
"""
import copy
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
from analysis.lesson_bank_study import assess
from analysis.lesson_bank_v4 import attempt, checked, total_spending
from analysis.lesson_checkpoint import CheckpointHive
from hive_learning.cloud_trial import allowed_launch
from hive_learning.cloud_study import implementation
from hive_learning.evaluate import strict_json
from hive_learning.ledger import digest
from hive_learning.lesson_study import ARMS, compact, neutral_lesson, save_json
from hive_learning.openai_adapter import load_api_key
from hive_learning.response_trace import ResponseTrace
from hive_learning.spending import LIMIT_NUSD, MODEL, SpendingGuard

INITIAL_PRIOR_NUSD = 2_314_907_300
BANK_SHA256 = "53e959ee24c1c0fca0be1f899ce711f2636f01c3925ed5e9df3cd4d5cb6936a4"


def sources():
    names = ["analysis/lesson_bank_v5.py", "analysis/lesson_checkpoint.py", "analysis/checkpoint_cases.py",
             "analysis/lesson_bank_v4.py", "analysis/typed_actions.py", "analysis/lesson_bank_study.py",
             "analysis/cloud_http400.py"]
    return implementation(ROOT) | {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def read_plan():
    plan = strict_json((ROOT/"lesson-v5-plan.json").read_bytes())
    phase = plan["phase"]
    if (type(phase) is not int or not 1 <= phase <= 4
            or plan["launch_message"] != f"Run authorized Hive lesson v5 phase {phase}"
            or not re.fullmatch(r"[a-f0-9]{40}", plan["launch_parent"])
            or plan["source_sha256"] != digest(sources())):
        raise ValueError("invalid frozen launch")
    study = checked(plan["study"], plan["study_sha256"])
    preflight = checked(plan["preflight"], plan["preflight_sha256"])
    if (study["schema"] != "hive.lesson-bank.v5" or study["model"] != MODEL
            or study["calls_per_recipient"] != 36 or len(study["cases"]) != 21
            or digest(study["cases"]) != preflight["cases_sha256"] or not preflight["verified"]
            or digest(study["lessons"]) != BANK_SHA256):
        raise ValueError("invalid study, bank or preflight")
    keys = [c["id"] for c in study["cases"]]
    if len(set(keys)) != 21 or sum(c["split"] == "confirmation" for c in study["cases"]) != 18:
        raise ValueError("incorrect prospective sample")
    prior = checked(plan["prior_report"], plan["prior_report_sha256"])
    spent = prior["spending"]["total_upper_nano_usd"]
    if (type(spent) is not int or not INITIAL_PRIOR_NUSD <= spent <= LIMIT_NUSD
            or prior["spending"]["unresolved_reservation_nano_usd"] or prior["status"] != "COMPLETED"):
        raise ValueError("invalid or unsettled predecessor")
    previous = None
    if phase > 1:
        previous = checked(plan["prior_state"], plan["prior_state_sha256"])
        if (prior["study_state_sha256"] != plan["prior_state_sha256"]
                or prior["source_sha256"] != plan["source_sha256"]
                or previous["study_sha256"] != plan["study_sha256"]
                or [p["phase"] for p in previous["phases"]] != list(range(1, phase))
                or any(p["status"] != "completed" for p in previous["phases"])
                or previous["bank_sha256"] != BANK_SHA256):
            raise ValueError("changed bank or consumed/incomplete predecessor")
    elif (plan["prior_state"] is not None or plan["prior_state_sha256"] is not None
          or spent != INITIAL_PRIOR_NUSD or prior["episode_id"] != "24750a49f5249394ceafe43f5b0bf65d02150b0631bab6e3d57e36a4b2b2f006"):
        raise ValueError("new study must carry final V4 account exactly")
    return plan, study, prior, previous


def main():
    plan, study, prior, previous = read_plan()
    event = strict_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    if not allowed_launch({**os.environ, "HIVE_LAUNCH_PARENT": plan["launch_parent"]}, event, plan["launch_message"]):
        os.environ.pop("OPENAI_API_KEY", None)
        return 2
    if sys.argv[1:] == ["--check"]:
        print(json.dumps({"status": "COMMITMENT_VERIFIED", "phase": plan["phase"],
                          "prior_upper_nano_usd": prior["spending"]["total_upper_nano_usd"]}))
        return 0
    output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=False)
    manifest = {"plan": plan, "run_id": os.environ["GITHUB_RUN_ID"], "commit": os.environ["GITHUB_SHA"],
                "source_hashes": sources(), "prior_episode": prior["episode_id"], "bank_sha256": BANK_SHA256}
    save_json(output/"manifest.json", manifest)
    report = {"episode_id": digest(manifest), "scope": "full_context_and_explicit_memory_checkpoint",
              "phase": plan["phase"], "study_sha256": plan["study_sha256"],
              "source_sha256": plan["source_sha256"], "continued_after": prior["episode_id"], "status": "INVALID"}
    state = copy.deepcopy(previous) if previous else {"schema": "hive.lesson-bank.state.v5",
        "study_sha256": plan["study_sha256"], "bank_sha256": BANK_SHA256, "phases": [], "trials": []}
    stage = {"phase": plan["phase"], "status": "running"}; state["phases"].append(stage)
    snapshots, transport = [], []
    cumulative = initial = prior["spending"]["total_upper_nano_usd"]
    deadline = time.monotonic() + 2100
    try:
        key = load_api_key()
        schedule = [(c, a) for c in study["cases"] if c["phase"] == plan["phase"] for a in ARMS]
        random.Random(study["seed"] + plan["phase"]).shuffle(schedule)
        stage["schedule"] = [{"case_id": c["id"], "arm": a} for c, a in schedule]
        save_json(output/"study-state.json", state)
        for case, arm in schedule:
            if time.monotonic() >= deadline:
                raise RuntimeError("phase deadline reached")
            label = case["id"] + "-" + arm
            guidance = [] if arm == "baseline" else study["lessons"] if arm == "lesson" else [neutral_lesson(x) for x in study["lessons"]]
            directory = output/"transport"/label
            directory.mkdir(parents=True, exist_ok=False)
            guard = SpendingGuard(directory/"spending.jsonl", prior_upper_nano_usd=cumulative)
            adapter = CheckpointHive(MODEL, key, max_requests=36, spending=guard,
                observer=ResponseTrace(directory/"responses"), request_directory=directory/"requests", seed=study["seed"])
            try:
                record = attempt(adapter, case, guidance, arm, output/"recipients"/label, guard)
                row = compact(record)
                if "outcome" in record: row["outcome"] = record["outcome"]
                row["checkpoint_count"] = sum(len(m.checkpoints) for m in adapter.meters)
                state["trials"].append(row); save_json(output/"study-state.json", state)
                print("HIVE_V5_PROGRESS " + json.dumps({"case": case["id"], "arm": arm,
                    "passed": record["passed"], "calls": record["usage"]["calls"]}), flush=True)
            finally:
                snap = guard.snapshot(); snapshots.append(snap); cumulative = snap["total_upper_nano_usd"]
                guard.close()
                save_json(directory/"checkpoints.json", [c for m in adapter.meters for c in m.checkpoints])
                transport.append({"recipient": label, "meters": adapter.observed_usage(), "spending": snap})
                save_json(output/"accounting.json", {"recipients": transport, "spending": total_spending(initial, snapshots)})
        stage["status"] = "completed"
        if plan["phase"] == 4:
            state["assessment"] = assess(state, study)
        report.update(status="COMPLETED", assessment=state.get("assessment"))
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        report["spending"] = total_spending(initial, snapshots)
        report["transport_usage"] = transport
    save_json(output/"study-state.json", state)
    report["study_state_sha256"] = hashlib.sha256((output/"study-state.json").read_bytes()).hexdigest()
    report["http_errors"] = [strict_json(p.read_bytes()) for p in sorted(output.glob("**/http-error.json"))]
    save_json(output/"report.json", report)
    save_json(output/"checksums.json", {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(output.rglob("*")) if p.is_file()})
    print("HIVE_V5_REPORT " + json.dumps({k: v for k, v in report.items() if k != "transport_usage"}), flush=True)
    return 0 if report["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
