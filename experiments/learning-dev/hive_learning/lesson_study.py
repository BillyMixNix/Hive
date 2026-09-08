"""Prospective retained-lesson study with independent final confirmation.

All model actions use the repaired Hive bridge and unchanged recovered executive.
Development selects a family/endpoint; exactly one frozen confirmation is allowed.
Reference repairs and protected tests never enter the lesson proposer or worker.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import random

from .evaluate import candidate_snapshot, grade, strict_json, validate_files, write_files
from .ledger import canonical, digest
from .loop import validate_lesson, validate_usage


ARMS = ("baseline", "lesson", "neutral")
STAGES = ("formation", "screen1", "refine", "screen2", "confirmation1", "confirmation2", "confirmation3")


def read_study(path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("study commitment changed")
    study = strict_json(raw)
    if (study["schema"] != "hive.lesson-transfer.v2" or study["calls_per_recipient"] != 36
            or study["policy"]["confirmation_attempts"] != 1):
        raise ValueError("invalid study protocol")
    ids = set()
    for case in study["cases"]:
        if case["id"] in ids:
            raise ValueError("duplicate study task")
        ids.add(case["id"])
        for key in ("files", "acceptance_tests", "protected_tests"):
            validate_files(case[key])
        if (set(case["files"]) & set(case["acceptance_tests"])
                or set(case["files"]) & set(case["protected_tests"])
                or set(case["acceptance_tests"]) & set(case["protected_tests"])):
            raise ValueError("study test paths overlap")
    return study


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def neutral_lesson(lesson):
    words = ("An archived record contains a date and a description of an earlier session "
             "The archive keeps notes in their original order for later inspection").split()
    return {key: " ".join(words[i % len(words)] for i in range(len(text.split())))
            for key, text in lesson.items()}


def public_record(root, case, outcome):
    """Only source/public-test observations actually brokered by Hive are retained.

    Do not use the independent score, reference repair, evaluator body or model
    reasoning. A failed public test plus observed actions is formation evidence.
    """
    states = list((root / ".agent_runs/hive").glob("*/state.json"))
    observations = []
    if len(states) == 1:
        state = strict_json(states[0].read_bytes())
        for item in state.get("evidence", {}).values():
            payload = item.get("payload")
            if (item.get("verified") and isinstance(payload, dict)
                    and {"tool", "arguments", "output"} <= set(payload)):
                observations.append({"tool": payload["tool"], "arguments": payload["arguments"],
                                     "output": str(payload["output"])[:4000]})
    return {"case_id": case["id"], "goal": case["goal"], "initial_public_files": case["files"],
            "observations": observations, "candidate_public_files": outcome.get("candidate"),
            "controller_decision": outcome.get("controller", {}).get("decision"),
            "controller_blocker": outcome.get("controller", {}).get("blocker", "")}


def run_recipient(adapter, case, lessons, arm, output):
    root = output / "workspace"
    root.mkdir(parents=True, exist_ok=False)
    original = copy.deepcopy(case["files"])
    write_files(root, original)
    record = {"case_id": case["id"], "family": case["family"], "split": case["split"], "arm": arm,
              "guidance_sha256": digest(lessons), "passed": False, "integrity_valid": True,
              "acceptance_checks": []}
    def acceptance(workspace):
        try:
            candidate = candidate_snapshot(workspace, original)
        except ValueError:
            return False
        score = grade(candidate, case["acceptance_tests"])
        record["acceptance_checks"].append({"candidate_sha256": digest(candidate), **score})
        return score["valid"] and score["passed"]
    try:
        usage, controller = adapter.work(root, case["goal"], lessons, 36, acceptance_oracle=acceptance)
        record.update({"usage": validate_usage(usage, 36), "controller": controller})
        candidate = candidate_snapshot(root, original)
        record["candidate"] = candidate
        record["candidate_sha256"] = digest(candidate)
        # Commit the candidate before opening the independent final evaluator.
        save_json(output / "candidate.json", candidate)
        final = grade(candidate, case["protected_tests"])
        record["score"] = final
        record["passed"] = bool(final["valid"] and final["passed"] and controller["decision"] == "SATISFIED")
    except Exception as exc:
        record["error"] = type(exc).__name__
        record["integrity_valid"] = False
        if adapter.meters:
            record["usage"] = dict(adapter.meters[-1].usage)
    save_json(output / "result.json", record)
    record["public_record"] = public_record(root, case, record)
    if adapter.budget.failed:
        raise RuntimeError("study stopped after a transport or spending failure")
    return record


def compact(record):
    return {key: record[key] for key in ("case_id", "family", "split", "arm", "guidance_sha256",
            "passed", "integrity_valid", "usage", "score", "error", "candidate_sha256") if key in record} | {
            "controller_decision": record.get("controller", {}).get("decision")}


def sign_p(wins, losses):
    n = wins + losses
    return sum(math.comb(n, k) for k in range(wins, n+1)) / (2**n) if n else 1.0


def choose_signal(trials):
    candidates = []
    for family in sorted({row["family"] for row in trials}):
        rows = {row["arm"]: row for row in trials if row["family"] == family}
        if set(rows) != set(ARMS) or not all(row["integrity_valid"] for row in rows.values()):
            continue
        lesson = rows["lesson"]
        if lesson["passed"] and all(not rows[arm]["passed"] for arm in ("baseline", "neutral")):
            candidates.append((0, family, "accuracy"))
        elif all(row["passed"] for row in rows.values()) and all(
                lesson["usage"]["calls"] <= 0.85 * rows[arm]["usage"]["calls"] for arm in ("baseline", "neutral")):
            candidates.append((1, family, "model_calls"))
    if not candidates:
        return None
    _, family, endpoint = sorted(candidates)[0]
    return {"family": family, "endpoint": endpoint}


def assess_confirmation(state, study):
    selected = state["selection"]
    family, endpoint = selected["family"], selected["endpoint"]
    expected = {c["id"] for c in study["cases"] if c["family"] == family and c["split"] == "confirmation"}
    retained = {c["id"] for c in study["cases"] if c["split"] == "retention"}
    rows = state["confirmation"]
    keys = [(r["case_id"], r["arm"]) for r in rows]
    target = {(case, arm) for case in expected | retained for arm in ARMS}
    if len(keys) != len(set(keys)) or set(keys) != target:
        return {"verdict": "INCOMPLETE", "completed_recipients": len(rows)}
    if not all(r["integrity_valid"] for r in rows):
        return {"verdict": "INVALID", "reason": "a recipient violated source/evaluation integrity"}
    paired = {case: {r["arm"]: r for r in rows if r["case_id"] == case} for case in expected}
    successes = {arm: sum(p[arm]["passed"] for p in paired.values()) for arm in ARMS}
    n = len(expected)
    comparisons = {}
    for control in ("baseline", "neutral"):
        if endpoint == "accuracy":
            wins = sum(p["lesson"]["passed"] and not p[control]["passed"] for p in paired.values())
            losses = sum(p[control]["passed"] and not p["lesson"]["passed"] for p in paired.values())
            effect = (successes["lesson"] - successes[control]) / n
            practical = effect >= study["policy"]["accuracy_minimum_gain"]
        else:
            wins = sum(p["lesson"]["usage"]["calls"] < p[control]["usage"]["calls"] for p in paired.values())
            losses = sum(p["lesson"]["usage"]["calls"] > p[control]["usage"]["calls"] for p in paired.values())
            treatment = sum(p["lesson"]["usage"]["calls"] for p in paired.values())
            baseline = sum(p[control]["usage"]["calls"] for p in paired.values())
            effect = 1 - treatment / baseline
            practical = effect >= study["policy"]["efficiency_minimum_reduction"] and all(v == n for v in successes.values())
        comparisons[control] = {"wins": wins, "losses": losses, "ties": n-wins-losses,
                                "effect": effect, "one_sided_p": sign_p(wins, losses),
                                "practical_threshold_passed": practical}
    retention = all(r["passed"] for r in rows if r["case_id"] in retained and r["arm"] == "lesson")
    passed = retention and all(c["practical_threshold_passed"] and
        c["one_sided_p"] <= study["policy"]["alpha_one_sided"] for c in comparisons.values())
    return {"verdict": "CONFIRMED_GAIN" if passed else "GAIN_NOT_CONFIRMED",
            "endpoint": endpoint, "family": family, "tasks_per_arm": n,
            "successes": successes, "comparisons": comparisons, "retention_passed": retention,
            "interpretation": "Conditional evidence on this authored task family and fixed model alias. Retained guidance changes inputs; weights are not retrained."}


def stage_cases(study, state, stage):
    if stage in {"formation", "screen1", "screen2"}:
        return [case for case in study["cases"] if case["split"] == stage]
    if stage.startswith("confirmation"):
        cases = sorted((c for c in study["cases"] if c["split"] == "confirmation" and
                        c["family"] == state["selection"]["family"]), key=lambda c: c["id"])
        index = int(stage[-1]) - 1
        return cases[index*4:(index+1)*4] + ([c for c in study["cases"] if c["split"] == "retention"] if index == 2 else [])
    return []


def run_stage(adapter, study, study_sha, stage, output, previous=None):
    state = copy.deepcopy(previous) if previous is not None else {
        "schema": "hive.lesson-transfer.state.v2", "study_sha256": study_sha,
        "lessons": {}, "lesson_history": [], "public_records": {}, "stages": [],
        "screens": {}, "confirmation": [], "selection": None, "lesson_bank_status": "CANDIDATE"}
    if state["study_sha256"] != study_sha or any(x["stage"] == stage for x in state["stages"]):
        raise ValueError("study changed or stage already consumed")
    completed = [x["stage"] for x in state["stages"] if x["status"] == "completed"]
    allowed = (not completed and stage == "formation"
               or completed == ["formation"] and stage == "screen1"
               or completed[-1:] == ["screen1"] and not state["selection"] and stage == "refine"
               or completed[-1:] == ["refine"] and stage == "screen2"
               or completed[-1:] in (["screen1"], ["screen2"]) and state["selection"] and stage == "confirmation1"
               or completed[-1:] == ["confirmation1"] and stage == "confirmation2"
               or completed[-1:] == ["confirmation2"] and stage == "confirmation3")
    if len(completed) != len(state["stages"]) or not allowed:
        raise ValueError("stage is not the prospectively permitted successor")
    event = {"stage": stage, "status": "running"}
    state["stages"].append(event)
    path = output / "study-state.json"
    save_json(path, state)
    if stage == "formation":
        for case in stage_cases(study, state, stage):
            record = run_recipient(adapter, case, [], "formation", output / "recipients" / case["id"])
            family = case["family"]
            state["public_records"][family] = [record["public_record"]]
            lesson, usage = adapter.propose({"schema": "hive.lesson.experience.v2",
                "failure": record["public_record"], "parent_lessons": []})
            state["lessons"][family] = validate_lesson(lesson)
            state["lesson_history"].append({"family": family, "stage": stage, "lesson": lesson,
                "source_sha256": digest(record["public_record"]), "usage": validate_usage(usage, 1)})
            save_json(path, state)
            print("HIVE_STUDY_PROGRESS " + canonical({"stage": stage, "case": case["id"], "repaired": record["passed"]}), flush=True)
    elif stage == "refine":
        for family in study["families"]:
            records = state["public_records"][family]
            lesson, usage = adapter.propose({"schema": "hive.lesson.experience.v2",
                "failure": {"recorded_public_experiences": records},
                "parent_lessons": [state["lessons"][family]]})
            state["lessons"][family] = validate_lesson(lesson)
            state["lesson_history"].append({"family": family, "stage": stage, "lesson": lesson,
                "source_sha256": digest(records), "usage": validate_usage(usage, 1)})
            save_json(path, state)
    else:
        cases = stage_cases(study, state, stage)
        schedule = [(case, arm) for case in cases for arm in ARMS]
        random.Random(study["seed"] + STAGES.index(stage)).shuffle(schedule)
        event["schedule"] = [{"case_id": case["id"], "arm": arm} for case, arm in schedule]
        save_json(path, state)
        destination = state["screens"].setdefault(stage, []) if stage.startswith("screen") else state["confirmation"]
        for case, arm in schedule:
            family = case["family"] if stage.startswith("screen") else state["selection"]["family"]
            lesson = state["lessons"][family]
            if stage.startswith("confirmation") and digest(lesson) != state["selection"]["lesson_sha256"]:
                raise ValueError("selected lesson changed before confirmation")
            guidance = [] if arm == "baseline" else [lesson if arm == "lesson" else neutral_lesson(lesson)]
            record = run_recipient(adapter, case, guidance, arm, output / "recipients" / (case["id"] + "-" + arm))
            destination.append(compact(record))
            if stage.startswith("screen") and arm == "baseline":
                state["public_records"][family].append(record["public_record"])
            save_json(path, state)
            print("HIVE_STUDY_PROGRESS " + canonical({"stage": stage, "case": case["id"], "arm": arm,
                "passed": record["passed"], "calls": record.get("usage", {}).get("calls")}), flush=True)
        if stage.startswith("screen"):
            selection = choose_signal(destination)
            if selection:
                state["selection"] = {**selection, "development_stage": stage,
                    "lesson_sha256": digest(state["lessons"][selection["family"]])}
    event["status"] = "completed"
    if stage == "confirmation3":
        state["assessment"] = assess_confirmation(state, study)
        if state["assessment"]["verdict"] == "CONFIRMED_GAIN":
            state["lesson_bank_status"] = "CONFIRMED_ON_FROZEN_FAMILY"
    save_json(path, state)
    return state
