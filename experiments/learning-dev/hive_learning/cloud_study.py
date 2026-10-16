"""One prospectively committed phase; all phases share the original $5 cap."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from .cloud_trial import allowed_launch
from .evaluate import strict_json
from .ledger import digest
from .lesson_study import STAGES, read_study, run_stage, save_json
from .openai_adapter import OpenAIHive, load_api_key
from .response_trace import ResponseTrace
from .spending import LIMIT_NUSD, MODEL, SpendingGuard


REQUEST_CAPS = {"formation": 222, "screen1": 648, "refine": 6, "screen2": 648,
                "confirmation1": 432, "confirmation2": 432, "confirmation3": 648}


def implementation(root):
    files = [root / "hive_orchestrator.py", root / "local_agent.py"]
    files += list((root / "hive_learning").glob("*.py"))
    files += list((root / "jarvis").glob("*.py"))
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files) if p.is_file()}


def committed_json(root, path, expected):
    if not re.fullmatch(r"(?:results|examples)/[A-Za-z0-9_./-]+\.json", path) or ".." in Path(path).parts:
        raise ValueError("invalid committed path")
    raw = (root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("committed input changed")
    return strict_json(raw)


def read_plan(root):
    plan = strict_json((root / "lesson-study-plan.json").read_bytes())
    if (set(plan) != {"stage", "launch_parent", "launch_message", "prior_report", "prior_report_sha256",
                      "study_path", "study_sha256", "prior_state", "prior_state_sha256", "implementation_sha256"}
            or plan["stage"] not in STAGES
            or not re.fullmatch(r"[a-f0-9]{40}", plan["launch_parent"])
            or plan["launch_message"] != "Run authorized Hive lesson study " + plan["stage"]
            or digest(implementation(root)) != plan["implementation_sha256"]):
        raise ValueError("invalid study launch commitment")
    study = read_study(root / plan["study_path"], plan["study_sha256"])
    preflight = strict_json((root / "results/lesson-v2-preflight.json").read_bytes())
    if (study["model"] != MODEL or preflight["validated_cases_sha256"] != digest(study["cases"])
            or not preflight["verified"] or len(preflight["cases"]) != len(study["cases"])):
        raise ValueError("study cases were not preflighted")
    prior = committed_json(root, plan["prior_report"], plan["prior_report_sha256"])
    spent = prior["spending"]["total_upper_nano_usd"]
    if (type(spent) is not int or not 0 <= spent <= LIMIT_NUSD
            or prior["spending"]["unresolved_reservation_nano_usd"]
            or not re.fullmatch(r"[a-f0-9]{64}", prior["episode_id"])):
        raise ValueError("invalid cumulative spending or unresolved request")
    previous = None
    if plan["stage"] == "formation":
        if plan["prior_state"] is not None or plan["prior_state_sha256"] is not None:
            raise ValueError("formation cannot reuse a lesson")
    else:
        previous = committed_json(root, plan["prior_state"], plan["prior_state_sha256"])
        if (prior.get("study_sha256") != plan["study_sha256"]
                or prior.get("study_state_sha256") != plan["prior_state_sha256"]
                or prior.get("implementation_sha256") != plan["implementation_sha256"]
                or previous["study_sha256"] != plan["study_sha256"]):
            raise ValueError("study continuation differs from frozen predecessor")
    return plan, study, prior, previous


class DeadlineHive(OpenAIHive):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase_end = time.monotonic() + 2100

    def _new_meter(self, cap, deadline=900, *, proposer=False):
        remaining = self.phase_end - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("phase deadline exhausted")
        return super()._new_meter(cap, min(deadline, remaining), proposer=proposer)


def main():
    root = Path(__file__).resolve().parent.parent
    plan, study, prior, previous = read_plan(root)
    event = strict_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    if not allowed_launch({**os.environ, "HIVE_LAUNCH_PARENT": plan["launch_parent"]}, event, plan["launch_message"]):
        os.environ.pop("OPENAI_API_KEY", None)
        print(json.dumps({"status": "LAUNCH_REFUSED", "model_requests": 0}))
        return 2
    if sys.argv[1:] == ["--check"]:
        print(json.dumps({"status": "COMMITMENT_VERIFIED", "stage": plan["stage"],
                          "prior_upper_nano_usd": prior["spending"]["total_upper_nano_usd"]}))
        return 0
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"scope": "prospective_lesson_transfer", "plan": plan,
                "run_id": os.environ["GITHUB_RUN_ID"], "commit": os.environ["GITHUB_SHA"],
                "implementation": implementation(root), "prior_episode": prior["episode_id"],
                "authorization": "Billy: keep going; goal is to prove lessons improve the model; original total $5"}
    save_json(output / "manifest.json", manifest)
    report = {"episode_id": digest(manifest), "stage": plan["stage"],
              "study_sha256": plan["study_sha256"], "implementation_sha256": plan["implementation_sha256"],
              "continued_after": prior["episode_id"], "status": "INVALID"}
    guard = adapter = None
    try:
        key = load_api_key()
        guard = SpendingGuard(output / "spending.jsonl", prior_upper_nano_usd=prior["spending"]["total_upper_nano_usd"])
        adapter = DeadlineHive(MODEL, key, max_requests=REQUEST_CAPS[plan["stage"]],
                               spending=guard, observer=ResponseTrace(output / "responses"), seed=study["seed"])
        del key
        state = run_stage(adapter, study, plan["study_sha256"], plan["stage"], output, previous)
        report.update(status="COMPLETED", selection=state["selection"], assessment=state.get("assessment"))
    except Exception as exc:
        report["error"] = type(exc).__name__
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        if guard is not None:
            report["spending"] = guard.snapshot()
            guard.close()
        if adapter is not None:
            report["transport_usage"] = adapter.observed_usage()
    state_path = output / "study-state.json"
    if state_path.is_file():
        report["study_state_sha256"] = hashlib.sha256(state_path.read_bytes()).hexdigest()
    report["interpretation"] = "Formation and screening are development only. Gain requires the frozen independent confirmation, both controls, and retention. Guidance does not retrain model weights. Spending carries all earlier attempts."
    save_json(output / "report.json", report)
    save_json(output / "checksums.json", {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(output.rglob("*")) if p.is_file()})
    print("HIVE_STUDY_REPORT " + json.dumps(report, sort_keys=True), flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text("```json\n" + json.dumps(report, indent=2) + "\n```\n")
    return 0 if report["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
