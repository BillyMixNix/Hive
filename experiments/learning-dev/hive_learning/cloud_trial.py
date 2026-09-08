"""One authorized GitHub-hosted development episode; never an automatic retry."""
import hashlib
import json
import os
from pathlib import Path
import sys

from jarvis.store import Store
from .demo import seed_failure
from .loop import implementation_hashes, run
from .openai_adapter import OpenAIHive, load_api_key
from .spending import MODEL, SpendingGuard
from .ledger import digest
from .repair_probe import PROBE_SHA256, run_probe


BRANCH = "refs/heads/agent/hive-live-trial-20260908"
LAUNCH_MESSAGE = "Launch the authorized Hive development trial 2026-09-08"
REPEAT_MESSAGE = "Launch the authorized Hive diagnostic repeat 2"
SUITE_SHA256 = "119c5a5d476e7442ebfbebbba546be2391834b14a4db59326bd7a310cf58962a"


def allowed_launch(env, event, launch_message=LAUNCH_MESSAGE):
    return (env.get("GITHUB_REPOSITORY") == "BillyMixNix/Hive"
            and env.get("GITHUB_REF") == BRANCH
            and env.get("GITHUB_EVENT_NAME") == "push"
            and env.get("GITHUB_RUN_ATTEMPT") == "1"
            and len(env.get("HIVE_LAUNCH_PARENT", "")) == 40
            and event.get("before") == env.get("HIVE_LAUNCH_PARENT")
            and event.get("head_commit", {}).get("message") == launch_message
            and event.get("head_commit", {}).get("id") == env.get("GITHUB_SHA"))


def main(*, repeat_of=None, continuation=None):
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    launch_message = REPEAT_MESSAGE if repeat_of is not None else LAUNCH_MESSAGE
    launch_env = dict(os.environ)
    if continuation is not None:
        launch_message = continuation["launch_message"]
        launch_env["HIVE_LAUNCH_PARENT"] = continuation["launch_parent"]
    if not allowed_launch(launch_env, event, launch_message):
        os.environ.pop("OPENAI_API_KEY", None)
        print(json.dumps({"status": "LAUNCH_REFUSED", "model_requests": 0}))
        return 2
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parent.parent
    is_probe = continuation is not None and continuation["mode"] == "repair_probe"
    guard = adapter = store = task = None
    try:
        key = load_api_key()  # Remove before any repository child can be launched.
        if repeat_of is None:
            guard = SpendingGuard(output / "spending.jsonl")
        else:
            guard = SpendingGuard(output / "spending.jsonl",
                                  prior_upper_nano_usd=repeat_of["spending"]["total_upper_nano_usd"])
        adapter_options = {}
        if continuation is not None:
            from .response_trace import ResponseTrace
            adapter_options["observer"] = ResponseTrace(output / "responses")
        adapter = OpenAIHive(MODEL, key,
                             max_requests=continuation["max_requests"] if continuation else 325,
                             max_output_tokens=4096, spending=guard, **adapter_options)
        del key
        manifest = {"scope": "development_real_model", "fixture": "seen synthetic development suite",
                    "run_id": os.environ["GITHUB_RUN_ID"], "commit": os.environ["GITHUB_SHA"],
                    "suite_sha256": SUITE_SHA256, "adapter": adapter.identity,
                    "implementation": implementation_hashes(), "seed": 42,
                    "recipient_call_cap": 36, "proposer_call_cap": 1}
        if repeat_of is not None:
            manifest["diagnostic_replay_of"] = repeat_of["episode_id"]
            manifest["prior_spending"] = repeat_of["spending"]
            manifest["authorization"] = "Billy: So run it again (2026-09-08)"
        if continuation is not None:
            manifest["continuation"] = continuation
            manifest["authorization"] = "Billy: Ok keep going as long as you need (2026-09-08)"
        if is_probe:
            manifest.pop("suite_sha256")
            manifest.pop("diagnostic_replay_of", None)
            manifest["fixture"] = "frozen visible-failure development repair probe"
            manifest["probe_sha256"] = PROBE_SHA256
            manifest["continued_after"] = repeat_of["episode_id"]
            manifest["proposer_call_cap"] = 0
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if is_probe:
            report = run_probe(adapter, output / "repair-work", project / "examples/repair-probe.json")
            report["episode_id"] = digest(manifest)
            report["continued_after"] = repeat_of["episode_id"]
        else:
            store = Store(output / "jarvis.db")
            task = seed_failure(store, output / "failed-work")
            report = run(store, task, project / "examples/suite.development.json", SUITE_SHA256, adapter,
                         diagnostic_replay_of=repeat_of["episode_id"] if repeat_of is not None else None)
            report["ledger_verified"] = store.verify_chain()[0]
            report["ordinary_jarvis_guidance"] = len(store.guidance())
            report["trials"] = [{key: e["data"][key] for key in
                                ("case_id", "split", "arm", "candidate_sha256", "usage", "score")}
                               for e in store.events(task) if e["type"] == "LEARNING_EVALUATED"]
    except Exception as exc:
        # Startup exceptions are never printed with arguments or traceback.
        report = {"scope": "development_real_model", "verdict": "INVALID",
                  "reason": "trial startup failed: " + type(exc).__name__}
        if adapter is not None:
            report["transport_usage"] = adapter.observed_usage()
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
    if guard is not None:
        report["spending"] = guard.snapshot()
        guard.close()
    if store is not None and task is not None:
        (output / "events.json").write_text(json.dumps(store.events(task), indent=2) + "\n")
        with store.connect() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    report["interpretation"] = (
        "Live integration on previously authored development fixtures. A pass is not evidence of RSI; "
        "a rejected lesson is not retained. Spending is a conservative token-charge upper bound, "
        "not an invoice; unresolved requests retain their full reservation.")
    if is_probe:
        report["interpretation"] = (
            "One frozen visible-failure development repair probe with no supplied lesson. "
            "The initial failure and candidate are independently graded using the same frozen tests. "
            "This verifies integration only; no learning gain, lesson promotion or RSI is established. "
            "Spending carries every preceding attempt and is a conservative token-charge upper bound.")
    elif repeat_of is not None:
        report["interpretation"] += (
            " This is the explicitly authorized diagnostic replay of the consumed development suite. "
            "Original evidence is unchanged; replay results cannot promote a lesson.")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    checksums = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")
    print("HIVE_TRIAL_REPORT " + json.dumps(report, sort_keys=True), flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text("```json\n" + json.dumps(report, indent=2) + "\n```\n")
    if is_probe:
        return 0 if report["verdict"] in {"REPAIR_VERIFIED", "REPAIR_NOT_VERIFIED"} and report.get("probe_integrity_verified") else 2
    return 0 if report["verdict"] in {"PROMOTED", "REJECTED", "REPLAY_GATE_PASSED"} and report.get("ledger_verified") else 2


if __name__ == "__main__":
    raise SystemExit(main())
