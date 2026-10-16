import copy
import hashlib
from pathlib import Path
import random
import tempfile

from .evaluate import candidate_snapshot, grade, read_suite, write_files
from .ledger import append, begin, canonical, digest, finish


def implementation_hashes():
    root = Path(__file__).resolve().parent.parent
    names = ["hive_orchestrator.py", "local_agent.py", "jarvis/store.py"]
    names += [p.relative_to(root).as_posix() for p in (root / "hive_learning").glob("*.py")]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(names)}


def validate_lesson(value):
    if not isinstance(value, dict) or set(value) != {"when", "summary", "rationale"}:
        raise ValueError("lesson requires exactly when, summary, rationale")
    if any(not isinstance(v, str) or not v.strip() for v in value.values()):
        raise ValueError("lesson fields must be nonempty text")
    if len(canonical(value).encode()) > 4096:
        raise ValueError("lesson exceeds 4096 bytes")
    return copy.deepcopy(value)


def validate_usage(value, cap):
    if not isinstance(value, dict) or not {"calls", "prompt_tokens", "output_tokens"} <= set(value):
        raise ValueError("adapter must report measured usage")
    for key in ("calls", "prompt_tokens", "output_tokens"):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError("usage must contain nonnegative integers")
    if not 1 <= value["calls"] <= cap:
        raise ValueError("model call cap violated")
    return copy.deepcopy(value)


def run(store, task_id, suite_path, suite_sha256, adapter, *, calls=36, seed=42,
        diagnostic_replay_of=None):
    """One consumed episode. Adapter is a trusted, metered, stateless transport.

    Proposer gets public failure only. Recipient gets public files and guidance.
    Evaluation results never return to either model during the episode.
    """
    if type(calls) is not int or not 1 <= calls <= 128 or type(seed) is not int:
        raise ValueError("invalid budget or seed")
    suite = read_suite(suite_path, suite_sha256)
    original_suite_fingerprint = digest(suite)
    identity = copy.deepcopy(adapter.identity)
    if identity.get("scope") not in {"development_real_model", "development_simulated"}:
        raise ValueError("adapter must declare evidence scope")
    config = {"adapter": identity, "recipient_call_cap": calls, "proposer_call_cap": 1,
              "seed": seed, "implementation": implementation_hashes(),
              "gate": "all-treatment-pass_strict-transfer-gain_neutral-control.v1"}
    if diagnostic_replay_of is not None:
        if (not isinstance(diagnostic_replay_of, str) or len(diagnostic_replay_of) != 64
                or any(c not in "0123456789abcdef" for c in diagnostic_replay_of)):
            raise ValueError("diagnostic replay requires the prior episode's exact identifier")
        config["diagnostic_replay_of"] = diagnostic_replay_of
    start, packet, parent, inherited = begin(store, task_id, suite_sha256, config, suite)
    suite = copy.deepcopy(suite)
    suite["cases"].extend(inherited)
    suite_fingerprint = digest(suite)
    episode = start["episode_id"]
    frozen_parent = digest(parent)
    trials = []
    lesson = None
    proposal_usage = None
    try:
        lesson, proposal_usage = adapter.propose(copy.deepcopy(packet))
        lesson = validate_lesson(lesson)
        if len(canonical([*parent, lesson]).encode()) > 60_000:
            raise ValueError("guidance capacity exceeded; cannot silently truncate the bank")
        proposal_usage = validate_usage(proposal_usage, 1)
        sealed_lesson = digest(lesson)
        append(store, task_id, "LEARNING_PROPOSED", {
            "episode_id": episode, "lesson": lesson, "lesson_sha256": sealed_lesson,
            "usage": proposal_usage,
        })
        # Fixed neutral guidance, padded to the candidate's character count.
        # Provider token counts are recorded, not assumed equal.
        neutral = {k: "." + " " * (len(v) - 1) for k, v in lesson.items()}
        schedule = [(i, arm) for i in range(len(suite["cases"]))
                    for arm in ("baseline", "lesson", "neutral")]
        random.Random(seed).shuffle(schedule)
        append(store, task_id, "LEARNING_SCHEDULED", {
            "episode_id": episode, "schedule": schedule, "neutral": neutral,
        })
        for index, arm in schedule:
            if (digest(adapter.identity) != digest(identity) or digest(parent) != frozen_parent
                    or digest(lesson) != sealed_lesson or digest(suite) != suite_fingerprint):
                raise ValueError("frozen episode inputs changed")
            case = suite["cases"][index]
            guidance = copy.deepcopy(parent)
            if arm != "baseline":
                guidance.append(copy.deepcopy(lesson if arm == "lesson" else neutral))
            with tempfile.TemporaryDirectory(prefix="hive-recipient-") as temp:
                root = Path(temp)
                write_files(root, case["files"])
                usage = adapter.repair(root, case["goal"], guidance, calls)
                usage = validate_usage(usage, calls)
                candidate = candidate_snapshot(root, case["files"])
            # Candidate is copied and committed before the evaluator sees it.
            trial = {"episode_id": episode, "case_id": case["id"], "split": case["split"],
                     "arm": arm, "candidate_sha256": digest(candidate), "candidate": candidate,
                     "guidance_sha256": digest(guidance), "usage": usage}
            append(store, task_id, "LEARNING_CANDIDATE", trial)
            trial = {**trial, "score": grade(candidate, case["protected_tests"])}
            append(store, task_id, "LEARNING_EVALUATED", trial)
            trials.append(trial)
        if (digest(adapter.identity) != digest(identity) or digest(lesson) != sealed_lesson
                or digest(read_suite(suite_path, suite_sha256)) != original_suite_fingerprint
                or implementation_hashes() != config["implementation"]):
            raise ValueError("episode inputs changed during evaluation")
        valid = all(t["score"]["valid"] for t in trials)
        all_pass = all(t["score"]["passed"] for t in trials if t["arm"] == "lesson")
        transfer = {arm: sum(t["score"]["passed"] for t in trials
                            if t["arm"] == arm and t["split"] == "transfer")
                    for arm in ("baseline", "lesson", "neutral")}
        gain = transfer["lesson"] > transfer["baseline"]
        control = transfer["neutral"] <= transfer["baseline"]
        verdict = "INVALID" if not valid else "PROMOTED" if all_pass and gain and control else "REJECTED"
        report = {"episode_id": episode, "suite_sha256": suite_sha256,
                  "scope": identity["scope"], "verdict": verdict, "lesson": lesson,
                  "parent_bank_sha256": frozen_parent, "transfer_passes": transfer,
                  "inherited_retention_cases": len(inherited),
                  "gates": {"valid": valid, "all_treatment_pass": all_pass,
                            "strict_transfer_gain": gain, "neutral_control": control},
                  "proposal_usage": proposal_usage,
                  "recipient_usage": {key: sum(t["usage"][key] for t in trials)
                                      for key in ("calls", "prompt_tokens", "output_tokens")}}
    except Exception as exc:
        report = {"episode_id": episode, "suite_sha256": suite_sha256,
                  "scope": identity["scope"], "verdict": "INVALID", "lesson": lesson,
                  "reason": f"{type(exc).__name__}: {exc}", "completed_trials": len(trials),
                  "proposal_usage": proposal_usage}
    if hasattr(adapter, "observed_usage"):
        report["transport_usage"] = adapter.observed_usage()
    if diagnostic_replay_of is not None:
        report["diagnostic_replay_of"] = diagnostic_replay_of
        report["promotion_eligible"] = False
        if report["verdict"] == "PROMOTED":
            report["verdict"] = "REPLAY_GATE_PASSED"
    return finish(store, task_id, report, frozen_parent)
