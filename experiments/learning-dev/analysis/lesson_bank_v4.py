"""Final prospectively frozen lesson comparison with direct typed tools.

Each recipient has an exclusive request journal and inherits the full cumulative
charge. A settled model-output error consumes the case as an unsuccessful repair;
HTTP, unknown usage and evaluation integrity failures stop the study. No retries.
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
from analysis.typed_actions import TypedHive
from hive_learning.cloud_trial import allowed_launch
from hive_learning.cloud_study import implementation
from hive_learning.evaluate import strict_json
from hive_learning.ledger import digest
from hive_learning.lesson_study import ARMS, compact, neutral_lesson, run_recipient, save_json
from hive_learning.loop import validate_lesson
from hive_learning.openai_adapter import load_api_key
from hive_learning.response_trace import ResponseTrace
from hive_learning.spending import LIMIT_NUSD, MODEL, SpendingGuard

COUNTED_MODEL_FAILURES = {
    "invalid_native_action", "invalid_native_arguments", "response_incomplete",
    "refusal_or_invalid_message", "invalid_json_object", "unexpected_output_items",
    "recipient_limit_or_deadline", "invalid_output_items",
}


def sources():
    names = ["analysis/lesson_bank_v4.py", "analysis/typed_actions.py",
             "analysis/lesson_bank_study.py", "analysis/cloud_http400.py"]
    return implementation(ROOT) | {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def checked(path, expected):
    if not re.fullmatch(r"(?:examples|results)/[A-Za-z0-9_./-]+\.json", path) or ".." in Path(path).parts:
        raise ValueError("invalid committed input path")
    raw = (ROOT/path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("committed input changed")
    return strict_json(raw)


def read_plan():
    plan = strict_json((ROOT/"lesson-v4-plan.json").read_bytes())
    phase = plan["phase"]
    if (type(phase) is not int or not 0 <= phase <= 4
            or plan["launch_message"] != f"Run authorized Hive lesson v4 phase {phase}"
            or not re.fullmatch(r"[a-f0-9]{40}", plan["launch_parent"])
            or plan["source_sha256"] != digest(sources())):
        raise ValueError("invalid frozen launch")
    study = checked(plan["study"], plan["study_sha256"])
    preflight = checked(plan["preflight"], plan["preflight_sha256"])
    formation = checked(study["formation_path"], study["formation_sha256"])
    if (study["schema"] != "hive.lesson-bank.v4" or study["model"] != MODEL
            or study["calls_per_recipient"] != 36 or len(study["cases"]) != 20
            or digest(study["cases"]) != preflight["cases_sha256"] or not preflight["verified"]):
        raise ValueError("invalid study or preflight")
    prior = checked(plan["prior_report"], plan["prior_report_sha256"])
    spent = prior["spending"]["total_upper_nano_usd"]
    if type(spent) is not int or not 0 <= spent <= LIMIT_NUSD or prior["spending"]["unresolved_reservation_nano_usd"]:
        raise ValueError("unsettled predecessor")
    previous = None
    if phase:
        previous = checked(plan["prior_state"], plan["prior_state_sha256"])
        if (prior["status"] != "COMPLETED" or prior["study_state_sha256"] != plan["prior_state_sha256"]
                or prior["source_sha256"] != plan["source_sha256"]
                or previous["study_sha256"] != plan["study_sha256"]
                or [p["phase"] for p in previous["phases"]] != list(range(phase))
                or any(p["status"] != "completed" for p in previous["phases"])
                or digest(previous["lessons"]) != previous["bank_sha256"]):
            raise ValueError("changed bank or consumed/incomplete predecessor")
    elif plan["prior_state"] is not None or plan["prior_state_sha256"] is not None:
        raise ValueError("formation must start fresh")
    return plan, study, formation, prior, previous


def counted_failure(record, adapter, snapshot):
    """A fully metered model mistake is a failed task, never a successful action."""
    codes = {m.failure_code for m in adapter.meters if m.failure_code}
    return (not snapshot["unresolved_reservation_nano_usd"] and bool(codes)
            and codes <= COUNTED_MODEL_FAILURES and record.get("usage", {}).get("calls", 0) > 0)


def attempt(adapter, case, guidance, arm, directory, guard):
    try:
        record = run_recipient(adapter, case, guidance, arm, directory)
    except RuntimeError:
        path = directory/"result.json"
        if not path.exists():
            raise
        record = strict_json(path.read_bytes())
        if not counted_failure(record, adapter, guard.snapshot()):
            raise
        record.update(integrity_valid=True, passed=False, outcome="model_failure_counted",
                      failure_codes=[m.failure_code for m in adapter.meters if m.failure_code])
        save_json(path, record)
    if not record["integrity_valid"]:
        raise RuntimeError("independent evaluation or workspace integrity failure")
    return record


def total_spending(prior, snapshots):
    known = sum(s["measured_usage_upper_nano_usd"] for s in snapshots)
    pending = sum(s["unresolved_reservation_nano_usd"] for s in snapshots)
    return {"limit_nano_usd": LIMIT_NUSD, "prior_upper_nano_usd": prior,
            "measured_usage_upper_nano_usd": known, "unresolved_reservation_nano_usd": pending,
            "total_upper_nano_usd": prior + known + pending,
            "requests_reserved": sum(s["requests_reserved"] for s in snapshots),
            "blocked": bool(pending), "counted_recipient_failures": sum(s["blocked"] for s in snapshots)}


def main():
    plan, study, formation, prior, previous = read_plan()
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
                "source_hashes": sources(), "prior_episode": prior["episode_id"]}
    save_json(output/"manifest.json", manifest)
    report = {"episode_id": digest(manifest), "scope": "final_frozen_retained_lesson_comparison",
              "phase": plan["phase"], "study_sha256": plan["study_sha256"],
              "source_sha256": plan["source_sha256"], "continued_after": prior["episode_id"], "status": "INVALID"}
    state = copy.deepcopy(previous) if previous else {"schema": "hive.lesson-bank.state.v4",
        "study_sha256": plan["study_sha256"], "lessons": [], "lesson_history": [], "phases": [], "trials": []}
    stage = {"phase": plan["phase"], "status": "running"}; state["phases"].append(stage)
    save_json(output/"study-state.json", state)
    snapshots, transport = [], []
    cumulative = initial = prior["spending"]["total_upper_nano_usd"]
    deadline = time.monotonic() + 2100
    def make_adapter(directory, cap):
        directory.mkdir(parents=True, exist_ok=False)
        guard = SpendingGuard(directory/"spending.jsonl", prior_upper_nano_usd=cumulative)
        adapter = TypedHive(MODEL, key, max_requests=cap, spending=guard,
            observer=ResponseTrace(directory/"responses"), request_directory=directory/"requests", seed=study["seed"])
        return guard, adapter
    def settle(guard, adapter, label):
        nonlocal cumulative
        snap = guard.snapshot(); snapshots.append(snap); cumulative = snap["total_upper_nano_usd"]
        guard.close(); transport.append({"recipient": label, "meters": adapter.observed_usage(), "spending": snap})
        save_json(output/"accounting.json", {"recipients": transport, "spending": total_spending(initial, snapshots)})
    try:
        key = load_api_key()
        if plan["phase"] == 0:
            guard, adapter = make_adapter(output/"formation", 4)
            try:
                # One diagnostic of the previously failing packet, never executed
                # or counted as a repair. Subsequent three calls generate lessons.
                action = adapter._new_meter(1, deadline=120).worker(formation["diagnostic_messages"])
                save_json(output/"formation"/"unexecuted-diagnostic.json", {"action": strict_json(action), "executed": False})
                for item in formation["experiences"]:
                    lesson, usage = adapter.propose({"schema": "hive.lesson.refinement.v4",
                        "failure": item["public_record"], "parent_lessons": [item["parent_lesson"]],
                        "learning_focus": "Use the observed failed or redundant debugging actions to refine the diagnostic principle. Explain how to locate the causal source efficiently under the existing tool contracts. Generalize beyond names, IDs, line numbers and this task's answer. Do not claim validation."})
                    lesson = validate_lesson(lesson)
                    state["lessons"].append(lesson)
                    state["lesson_history"].append({"family": item["family"], "lesson": lesson,
                        "source_sha256": digest(item["public_record"]), "usage": usage})
                    save_json(output/"study-state.json", state)
                state["bank_sha256"] = digest(state["lessons"])
            finally:
                settle(guard, adapter, "formation_and_unexecuted_diagnostic")
        else:
            schedule = [(c, a) for c in study["cases"] if c["phase"] == plan["phase"] for a in ARMS]
            random.Random(study["seed"] + plan["phase"]).shuffle(schedule)
            stage["schedule"] = [{"case_id": c["id"], "arm": a} for c, a in schedule]
            save_json(output/"study-state.json", state)
            for case, arm in schedule:
                if time.monotonic() >= deadline:
                    raise RuntimeError("phase deadline reached")
                label = case["id"] + "-" + arm
                guidance = [] if arm == "baseline" else state["lessons"] if arm == "lesson" else [neutral_lesson(x) for x in state["lessons"]]
                guard, adapter = make_adapter(output/"transport"/label, 36)
                try:
                    record = attempt(adapter, case, guidance, arm, output/"recipients"/label, guard)
                    row = compact(record)
                    if "outcome" in record: row["outcome"] = record["outcome"]
                    state["trials"].append(row); save_json(output/"study-state.json", state)
                    print("HIVE_V4_PROGRESS " + json.dumps({"case": case["id"], "arm": arm,
                        "passed": record["passed"], "calls": record["usage"]["calls"]}), flush=True)
                finally:
                    settle(guard, adapter, label)
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
    print("HIVE_V4_REPORT " + json.dumps({k: v for k, v in report.items() if k != "transport_usage"}), flush=True)
    return 0 if report["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
