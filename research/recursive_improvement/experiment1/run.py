"""Experiment 1 controller. Execute only trusted baseline agents on the host.

All subject execution, including Coder smoke checks, goes through ContainerRunner.
Expected answers never enter the subject container or generation prompt.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict, replace
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

from research.recursive_improvement.container_runner import ContainerRunner, Limits
from research.recursive_improvement.gate import Trial, evaluate_candidate
from research.recursive_improvement.integration import CandidatePolicy, propose_candidate
from validation.variant import apply_unified_diff


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def strict_json(text):
    def reject(value):
        raise ValueError("Not strict JSON")
    return json.loads(text, parse_constant=reject)


def score(cases, responses):
    """Untrusted responses cannot specify correctness, costs, or case membership."""
    if not isinstance(responses, list) or len(responses) != len(cases):
        raise ValueError("Response count mismatch")
    expected_ids = {c["id"] for c in cases}
    if len(expected_ids) != len(cases):
        raise ValueError("Duplicate case IDs")
    by_id = {}
    for item in responses:
        if not isinstance(item, dict) or item.get("id") not in expected_ids or item["id"] in by_id:
            raise ValueError("Duplicate or unknown response ID")
        if ("error" in item) == ("text" in item):
            raise ValueError("Ambiguous response")
        by_id[item["id"]] = item
    result = []
    for case in cases:
        response = by_id[case["id"]]
        correct = False
        if "error" in case:
            correct = response.get("error") == case["error"]
        elif isinstance(response.get("text"), str):
            try:
                actual = strict_json(response["text"])
                # Canonical JSON distinguishes booleans from integers, unlike Python ==.
                correct = isinstance(actual, dict) and json.dumps(actual, sort_keys=True, ensure_ascii=False) == json.dumps(case["expected"], sort_keys=True, ensure_ascii=False)
            except (ValueError, TypeError):
                pass
        result.append({"case_id": case["id"], "correct": correct, "response": response})
    return result


def evaluate_cases(runner, subject, cases, seed):
    ordered = list(cases)
    random.Random(seed).shuffle(ordered)
    run = runner.run(subject, "extract", {"inputs": [{"id": c["id"], "input": c["input"]} for c in ordered]})
    result = {"run": asdict(run)}
    if run.status != "completed":
        result["valid"] = False
        result["scores"] = [{"case_id": c["id"], "correct": False} for c in cases]
        return result
    try:
        response = strict_json(run.stdout)
        result["scores"] = score(cases, response["responses"])
        result["valid"] = True
    except (ValueError, TypeError, KeyError):
        result["valid"] = False
        result["scores"] = [{"case_id": c["id"], "correct": False} for c in cases]
    return result


def restrict_method(original, candidate):
    """Only the body of the frozen method may differ; no import/decorator edits."""
    before, after = ast.parse(original), ast.parse(candidate)
    def method(tree):
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PlannerAgent")
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_extract_json_object"]
        if len(methods) != 1:
            raise ValueError("Expected one target method")
        return methods[0]
    old, new = method(before), method(after)
    old.body = new.body = [ast.Pass()]
    if ast.dump(before) != ast.dump(after):
        raise PermissionError("Candidate changed code outside the permitted method body")


def stage_patch(baseline, candidate, patch_data):
    policy = CandidatePolicy(editable_targets=frozenset({"planner.py"}))
    target, patch = policy.validate_patch_data(patch_data)
    original = (baseline / target).read_text()
    changed = apply_unified_diff(original, patch)
    restrict_method(original, changed)
    if original == changed:
        raise ValueError("No change")
    shutil.copytree(baseline, candidate)
    (candidate / target).write_text(changed)
    return target


def snapshot(destination, commit):
    archive = subprocess.check_output(["git", "archive", commit], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()) or Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                raise ValueError("Unsafe baseline snapshot")
        tar.extractall(destination, filter="data")
    # Original tests are included; the new oracle/controller never are.


@contextmanager
def baseline_agents(baseline):
    previous = Path.cwd()
    module_names = ("planner", "coder", "hive_llm")
    saved = {key: sys.modules.pop(key, None) for key in module_names}
    sys.path.insert(0, str(baseline))
    os.chdir(baseline)
    try:
        import planner
        import coder
        yield planner, coder
    finally:
        os.chdir(previous)
        sys.path.remove(str(baseline))
        for key in module_names:
            sys.modules.pop(key, None)
            if saved[key] is not None:
                sys.modules[key] = saved[key]


class ModelAdapter:
    """Real, bounded local inference transport; no canned answers or API keys."""
    def __init__(self, protocol, output):
        self.protocol, self.output, self.calls = protocol, output, []

    def __call__(self, prompt, role="default", **_):
        config = self.protocol["generation"]
        if role not in {"planner", "coder"} or len(self.calls) >= config["max_calls"]:
            raise RuntimeError("Generation call budget exhausted")
        if len(prompt) > config["max_prompt_characters"]:
            raise RuntimeError("Prompt envelope exceeded")
        index = len(self.calls)
        record = {"role": role, "prompt_characters": len(prompt), "status": "started"}
        self.calls.append(record)
        (self.output / f"{index}-{role}-prompt.txt").write_text(prompt)
        body = json.dumps({"model": self.protocol["model"], "prompt": prompt, "stream": False,
                           "options": {k: config[k] for k in ("seed", "temperature", "num_predict", "num_ctx", "num_thread")}}).encode()
        request = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json"})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=config["timeout_seconds_per_call"]) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ValueError("Model response envelope exceeded")
            data = strict_json(raw)
            record.update({key: data.get(key) for key in ("model", "done", "done_reason", "prompt_eval_count", "eval_count", "total_duration", "load_duration", "prompt_eval_duration", "eval_duration")})
            if data.get("done") is not True or not isinstance(data.get("response"), str):
                raise ValueError("Incomplete model response")
            record["status"] = "completed"
            (self.output / f"{index}-{role}-response.txt").write_text(data["response"])
            return data["response"]
        except Exception as exc:
            record["status"] = type(exc).__name__
            raise
        finally:
            record["wall_ms"] = (time.monotonic() - started) * 1000
            write(self.output / "model-calls.json", self.calls)


def security_checks(runner, baseline, output):
    probe = runner.run(baseline, "probe")
    if probe.status != "completed":
        raise RuntimeError("Sandbox probe failed: " + probe.stdout)
    info = strict_json(probe.stdout)
    write(output / "security-effective-policy.json", {"run": asdict(probe), "policy": info})
    expected_cpu = runner.limits.cpus
    quota, period = info["cpu_max"].split()
    ok = (info["uid"] == 65534 and all(info["denied"].values())
          and "CapEff:\t0000000000000000" in info["status"]
          and "NoNewPrivs:\t1" in info["status"]
          and "Seccomp:\t2" in info["status"]
          and int(info["memory_max"]) == runner.limits.memory_mb * 1024**2
          and int(info["pids_max"]) == runner.limits.pids
          and quota != "max" and int(quota) / int(period) == expected_cpu
          and not info["credentials"] and not info["docker_socket"])
    if not ok:
        raise RuntimeError("Sandbox effective-policy probe failed")
    short = ContainerRunner(runner.image, runner.harness, replace(runner.limits, wall_seconds=3, output_bytes=16384))
    hang = short.run(baseline, "hang")
    write(output / "security-hang.json", asdict(hang))
    flood = short.run(baseline, "flood")
    write(output / "security-flood.json", asdict(flood))
    oom = runner.run(baseline, "oom")
    write(output / "security-oom.json", asdict(oom))
    if hang.status != "timeout" or flood.status != "output_limit" or oom.status != "oom":
        raise RuntimeError("Sandbox limit enforcement failed")
    return {"effective_policy": info, "probe": asdict(probe), "hang": asdict(hang),
            "flood": asdict(flood), "oom": asdict(oom), "passed": True}


def recorded_regressions(runner, subject, baseline):
    # Reuse frozen recorded cases, but compare expected values on the host.
    calls, expected = [], {}
    for path in sorted((baseline / "validation/regressions").glob("*.json")):
        for case in json.loads(path.read_text()):
            cls, method = case["callable"].split(".")
            calls.append({"id": case["id"], "module": Path(case["target_file"]).stem,
                          "class": cls, "method": method, "args": case["args"]})
            expected[case["id"]] = case["expected"]
    run = runner.run(subject, "regressions", {"calls": calls})
    passed = False
    if run.status == "completed":
        try:
            actual = strict_json(run.stdout)
            ids = [x["id"] for x in actual]
            passed = len(ids) == len(set(ids)) == len(expected) and {x["id"]: x.get("value") for x in actual} == expected
        except (ValueError, TypeError, KeyError):
            pass
    return {"passed": passed, "case_count": len(expected), "run": asdict(run),
            "limitation": "Return-value checks only; recorded alias/post-mutation checks run in pytest."}


def generate(protocol, baseline, runner, public, output):
    transport = ModelAdapter(protocol, output)
    task = {"id": "experiment1-json-extraction", "target_file": "planner.py",
            "target_symbol": "_extract_json_object", "task_type": "bugfix",
            "change_intent": "modify_existing_logic", "expected_operation": "modify_logic",
            "note": "Improve PlannerAgent._extract_json_object in planner.py. " + protocol["contract"]
                    + " Modify only this existing method body; preserve its signature. Do not change tests, evaluator, imports, other methods, permissions or sandbox. Public examples: " + json.dumps(public),
            "metadata": {"target_file": "planner.py", "target_symbol": "_extract_json_object"}}
    captures = {}
    class SmokeExecutor:
        def test_patch_in_sandbox(self, patch_text, target_file, patch_reason=""):
            try:
                with tempfile.TemporaryDirectory(prefix="hive-smoke-") as tmp:
                    subject = Path(tmp) / "subject"
                    stage_patch(baseline, subject, {"target_file": target_file, "patch": patch_text})
                    result = evaluate_cases(runner, subject, public, 0)
                    captures["coder_smoke"] = result
                    ok = result["valid"] and all(s["correct"] for s in result["scores"])
                    return {"applied": True, "syntax_valid": True, "semantic_valid": ok,
                            "errors": [] if ok else ["Public-case smoke failed in container"],
                            "notes": "Public smoke only; held-out evaluation remains external."}
            except Exception as exc:
                return {"applied": False, "syntax_valid": False, "semantic_valid": False,
                        "errors": [type(exc).__name__], "notes": "Candidate policy or container validation failed."}
    with baseline_agents(baseline) as (planner_module, coder_module):
        state = generation_context(baseline, task)
        captures["task_anchor"] = task["metadata"]["anchor"]
        write(output / "generation-task.json", task)
        planner_module.ask_hive = coder_module.ask_hive = transport
        planner = planner_module.PlannerAgent(state_manager=state)
        coder = coder_module.CoderAgent(state_manager=state, executor=SmokeExecutor())
        class CapturePlanner:
            def plan_task(self, value):
                captures["plan"] = planner.plan_task(value)
                return captures["plan"]
        class CaptureCoder:
            def generate_patch(self, value, plan):
                captures["patch_data"] = coder.generate_patch(value, plan)
                return captures["patch_data"]
        with (output / "agents.log").open("w") as log, redirect_stdout(log):
            try:
                proposal = propose_candidate(task, planner=CapturePlanner(), coder=CaptureCoder(),
                                             policy=CandidatePolicy(editable_targets=frozenset({"planner.py"})))
                captures["proposal"] = asdict(proposal)
                captures["status"] = "proposed"
            except Exception as exc:
                captures["status"] = "blocked"
                captures["error"] = type(exc).__name__ + ": " + str(exc)
    captures["model_calls"] = transport.calls
    write(output / "generation.json", captures)
    return captures


def generation_context(baseline, task):
    """Give the original agents their required baseline symbol/span authority."""
    from HiveStateManager import HiveStateManager
    from anchor_utils import canonicalize_task_anchor
    state = HiveStateManager(repo_root=baseline, snapshot_path=baseline / "experiment-state.json")
    state.rebuild_repo_map()
    canonicalize_task_anchor(task, state_manager=state, default_anchor_source="frozen_baseline")
    anchor = task["metadata"]["anchor"]
    if any(anchor.get(name) is None for name in ("target_symbol_id", "lineno", "end_lineno")):
        raise ValueError("Baseline symbol proof unavailable; refusing to spend generation calls")
    return state


def summarize_generation_cost(calls):
    """A disconnected request can consume tokens without returning usage."""
    complete = all(c.get("status") == "completed" and
                   all(type(c.get(k)) is int and c[k] >= 0
                       for k in ("prompt_eval_count", "eval_count")) for c in calls)
    incoming = sum(c["prompt_eval_count"] for c in calls
                   if type(c.get("prompt_eval_count")) is int and c["prompt_eval_count"] >= 0)
    outgoing = sum(c["eval_count"] for c in calls
                   if type(c.get("eval_count")) is int and c["eval_count"] >= 0)
    return {"api_charge_usd": 0, "compute_cost_usd": None, "calls": len(calls),
            "prompt_tokens": incoming if complete else None,
            "output_tokens": outgoing if complete else None,
            "known_prompt_tokens": incoming, "known_output_tokens": outgoing,
            "token_usage_complete": complete,
            "wall_ms": sum(c["wall_ms"] for c in calls),
            "qualification": "Local compute; missing usage is unknown, and zero API fees is not zero lifecycle cost."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    protocol = json.loads((HERE / "protocol.json").read_text())
    public = json.loads((HERE / "public_cases.json").read_text())
    heldout = json.loads((HERE / "heldout_cases.json").read_text())
    checksums = json.loads((HERE / "frozen_sha256.json").read_text())
    if any(digest(HERE / name) != sha for name, sha in checksums.items()):
        raise RuntimeError("Frozen evaluation files changed")
    if len({c["id"] for c in heldout}) < protocol["evaluation"]["minimum_distinct_heldout_cases"]:
        raise RuntimeError("Insufficient distinct held-out cases")
    config = protocol["sandbox"]
    limits = Limits(**{k: config[k] for k in asdict(Limits())})
    runner = ContainerRunner(args.image, HERE, limits)
    # The mount exposes only worker.py, never the oracle files beside it.
    report = {"experiment": protocol["experiment"], "recursive_self_improvement_proven": False,
              "promotion_allowed": False, "status": "started", "protocol_sha256": digest(HERE / "protocol.json"),
              "frozen_files": checksums, "controller_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "python": platform.python_version(), "baseline_commit": protocol["baseline_commit"]}
    write(args.output / "result.json", report)
    with tempfile.TemporaryDirectory(prefix="hive-experiment1-") as tmp:
        root = Path(tmp)
        baseline, candidate = root / "baseline", root / "candidate"
        baseline.mkdir()
        snapshot(baseline, protocol["baseline_commit"])
        harness = root / "harness"
        harness.mkdir()
        shutil.copy2(HERE / "worker.py", harness / "worker.py")
        runner.harness = harness
        report["environment"] = runner.preflight()
        report["security_checks"] = security_checks(runner, baseline, args.output)
        # Model identity and all evaluation hashes are persisted before inference.
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
                models = json.load(response)["models"]
            report["model_identity"] = next(m for m in models if m["name"] == protocol["model"])
        except Exception as exc:
            report["model_identity"] = {"unavailable": type(exc).__name__}
        write(args.output / "freeze.json", {"protocol": protocol, "checksums": checksums,
              "model_identity": report["model_identity"], "environment": report["environment"],
              "timestamp_unix": time.time()})
        for name in checksums:
            shutil.copy2(HERE / name, args.output / name)
        baseline_hash = digest(baseline / "planner.py")
        report["baseline_source_sha256"] = baseline_hash
        seeds = protocol["evaluation"]["shuffle_seeds"]
        baseline_trials = []
        for seed in seeds:
            baseline_trials.append({"seed": seed,
                                    "public": evaluate_cases(runner, baseline, public, seed),
                                    "heldout": evaluate_cases(runner, baseline, heldout, seed)})
        report["baseline"] = baseline_trials
        report["baseline_regressions"] = recorded_regressions(runner, baseline, baseline)
        write(args.output / "result.json", report)
        generated = generate(protocol, baseline, runner, public, args.output)
        report["generation_status"] = generated["status"]
        report["generation_cost"] = summarize_generation_cost(generated["model_calls"])
        patch_data = generated.get("patch_data") or {}
        # Blocked candidates may be evaluated diagnostically, but cannot be accepted.
        if patch_data.get("status") == "blocked" and patch_data.get("failed_patch_text"):
            patch_data = {**patch_data, "status": "diagnostic_only", "patch": patch_data["failed_patch_text"]}
        try:
            stage_patch(baseline, candidate, patch_data)
            report["candidate_source_sha256"] = digest(candidate / "planner.py")
            (args.output / "candidate.patch").write_text(patch_data["patch"])
            trials = []
            paired_baseline = []
            # Alternate order to reduce startup/system-load bias. Baseline pre-run is retained.
            for index, seed in enumerate(seeds):
                results = {}
                order = [("baseline", baseline), ("candidate", candidate)]
                if index % 2:
                    order.reverse()
                for label, subject in order:
                    results[label] = {"seed": seed, "public": evaluate_cases(runner, subject, public, seed),
                                      "heldout": evaluate_cases(runner, subject, heldout, seed)}
                trials.append(results["candidate"])
                paired_baseline.append(results["baseline"])
            report["matched_baseline"], report["candidate"] = paired_baseline, trials
            report["candidate_regressions"] = recorded_regressions(runner, candidate, baseline)
            test_runner = ContainerRunner(args.image, harness, replace(limits, memory_mb=512, wall_seconds=300))
            tests = test_runner.run(candidate, "pytest")
            report["candidate_repository_tests"] = asdict(tests)
            report["candidate_repository_tests"]["qualification"] = "In-container diagnostic; subject shares interpreter with pytest. Host-held-out scoring is authoritative."
            decisions = []
            for base, cand in zip(paired_baseline, trials):
                b = [Trial(s["case_id"], s["correct"], 0, base["heldout"]["run"]["wall_ms"] / len(heldout)) for s in base["heldout"]["scores"]]
                c = [Trial(s["case_id"], s["correct"], 0, cand["heldout"]["run"]["wall_ms"] / len(heldout)) for s in cand["heldout"]["scores"]]
                decisions.append(asdict(evaluate_candidate(b, c)))
            report["per_repetition_gate"] = decisions
            b_times = [x["heldout"]["run"]["wall_ms"] for x in paired_baseline]
            c_times = [x["heldout"]["run"]["wall_ms"] for x in trials]
            ratio = statistics.median(c_times) / max(statistics.median(b_times), protocol["evaluation"]["latency_floor_ms"])
            report["host_latency"] = {"baseline_batch_median_ms": statistics.median(b_times),
                                      "candidate_batch_median_ms": statistics.median(c_times), "ratio": ratio,
                                      "qualification": "Host wall time includes fresh-container startup/cleanup; method timers are untrusted diagnostics."}
            no_regression = all(not bs["correct"] or cs["correct"] for b, c in zip(paired_baseline, trials)
                                for bs, cs in zip(b["heldout"]["scores"], c["heldout"]["scores"]))
            criteria = {"proposal_not_blocked": generated["status"] == "proposed",
                        "all_repetition_gates": all(d["accepted"] for d in decisions),
                        "no_baseline_correct_case_regression": no_regression,
                        "all_public_correct": all(s["correct"] for t in trials for s in t["public"]["scores"]),
                        "valid_matched_runs": all(t[k]["valid"] for t in trials + paired_baseline for k in ("public", "heldout")),
                        "recorded_regressions": report["candidate_regressions"]["passed"] and report["baseline_regressions"]["passed"],
                        "repository_tests": tests.status == "completed" and tests.exit_code == 0,
                        "latency": ratio <= protocol["evaluation"]["maximum_median_latency_ratio"]}
            report["criteria"] = criteria
            report["status"] = "candidate_measured_gain" if all(criteria.values()) else "candidate_rejected"
        except Exception as exc:
            report["status"] = "generation_or_policy_blocked"
            report["candidate_failure"] = type(exc).__name__ + ": " + str(exc)
        if digest(baseline / "planner.py") != baseline_hash:
            raise RuntimeError("Baseline unexpectedly changed")
        if any(digest(HERE / name) != sha for name, sha in checksums.items()):
            raise RuntimeError("Evaluation files unexpectedly changed")
        report["baseline_and_evaluation_unchanged"] = True
        report["claim_limit"] = protocol["claim_limit"]
        write(args.output / "result.json", report)
        print(json.dumps({k: report[k] for k in ("status", "generation_status", "generation_cost", "recursive_self_improvement_proven")}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Preserve a machine-readable infrastructure failure even before inference.
        if "--output" in sys.argv:
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            path = output / "result.json"
            report = json.loads(path.read_text()) if path.exists() else {}
            report.update({"status": "infrastructure_failed", "error": type(exc).__name__ + ": " + str(exc),
                           "promotion_allowed": False, "recursive_self_improvement_proven": False})
            write(path, report)
        raise
