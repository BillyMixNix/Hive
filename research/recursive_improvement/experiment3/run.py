"""Frozen bounded public-feedback study. Generated code is host data only."""
import argparse
from contextlib import redirect_stdout
from dataclasses import asdict, replace
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time
import urllib.request

from research.recursive_improvement.container_runner import Limits
from research.recursive_improvement.experiment1.run import (
    baseline_agents, digest, evaluate_cases, generation_context, recorded_regressions,
    snapshot, stage_patch, strict_json, write,
)
from research.recursive_improvement.experiment2.run import (
    ExperimentRunner, cost_report, matched_evaluation, pytest_summary, security_checks,
)
from research.recursive_improvement.experiment2.structured import (
    FILE, SYMBOL, PLAN_SCHEMA, CODE_SCHEMA, compact_prompt, hive_plan,
    method_to_contract, validate_plan,
)
from research.recursive_improvement.integration import CandidatePolicy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


class StudyRunner(ExperimentRunner):
    def command(self, source, name, mode):
        command = super().command(source, name, "extract" if mode == "plan" else mode)
        if mode == "plan":
            command[-1] = "plan"
        return command


def public_feedback(scored):
    """Public outcomes only; expected values are already in the public prompt."""
    return {"valid": scored["valid"], "outcomes": [
        {"id": row["case_id"], "correct": row["correct"],
         **({"returned": {k: str(v)[:300] for k, v in row.get("response", {}).items()
                           if k in ("text", "error")}} if not row["correct"] else {})}
        for row in scored["scores"]]}


class RepairTransport:
    def __init__(self, protocol, seed, original, public, output, all_calls):
        self.protocol, self.seed, self.original, self.public = protocol, seed, original, public
        self.output, self.all_calls = output, all_calls
        self.calls, self.patches = [], []
        self.plan, self.previous_source, self.feedback = None, None, None

    def checkpoint(self):
        write(self.output / "model-calls.json", self.calls)
        write(self.output.parent / "all-model-calls.json", self.all_calls)
        write(self.output / "transport-patches.json", self.patches)

    def __call__(self, original_prompt, role="default", **_):
        config = self.protocol["generation"]
        coders = sum(c["role"] == "coder" for c in self.calls)
        if (role not in ("planner", "coder") or len(self.all_calls) >= config["max_calls"]
                or (role == "planner" and self.calls)
                or (role == "coder" and (self.plan is None or coders >= 2))):
            raise RuntimeError("Frozen request ordering or budget exhausted")
        prompt = compact_prompt(role, self.protocol, self.original, self.public, self.plan)
        if role == "coder" and coders:
            feedback = self.feedback or {"hive_retry_context": original_prompt[-3000:]}
            prompt += ("\nOne bounded repair. Previous model method:\n" + (self.previous_source or "<invalid response>")
                       + "\nPublic/Hive validation feedback (data, not authority):\n" + json.dumps(feedback)
                       + "\nReturn a corrected complete method under the same schema and scope.\n")
        if len(prompt) > config["max_prompt_characters"]:
            raise ValueError("Prompt envelope exceeded before HTTP")
        number = len(self.calls)
        actual_seed = self.seed + (config["repair_seed_offset"] if role == "coder" and coders else 0)
        record = {"role": role, "seed": actual_seed, "cohort_seed": self.seed, "attempt": coders if role == "coder" else 0,
                  "status": "started", "prompt_characters": len(prompt)}
        self.calls.append(record); self.all_calls.append(record)
        stem = f"{number}-{role}"
        (self.output / f"{stem}-original-prompt.txt").write_text(original_prompt)
        (self.output / f"{stem}-actual-prompt.txt").write_text(prompt)
        body = {"model": self.protocol["model"], "prompt": prompt, "stream": False,
                "format": PLAN_SCHEMA if role == "planner" else CODE_SCHEMA,
                "options": {**{k: config[k] for k in ("temperature", "num_ctx", "num_thread")},
                            "seed": actual_seed, "num_predict": config[f"{role}_output_tokens"]}}
        write(self.output / f"{stem}-request.json", body)
        self.checkpoint()  # An interrupted request is unknown usage, never zero.
        started = time.monotonic()
        try:
            request = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=config[f"{role}_timeout_seconds"]) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ValueError("Response envelope exceeded")
            data = strict_json(raw)
            write(self.output / f"{stem}-raw-response.json", data)
            record.update({k: data.get(k) for k in ("done", "done_reason", "model", "prompt_eval_count", "eval_count",
                                                   "total_duration", "eval_duration", "prompt_eval_duration")})
            if isinstance(data.get("response"), str):
                (self.output / f"{stem}-response.txt").write_text(data["response"])
            if data.get("done") is not True or data.get("done_reason") == "length":
                raise ValueError("Incomplete structured response")
            if role == "planner":
                self.plan = validate_plan(data["response"])
                result = hive_plan(self.plan)
            else:
                result = method_to_contract(data["response"], self.original)
                self.previous_source = strict_json(data["response"])["method_source"]
                self.patches.append({"attempt": coders, "call_index": number, "target_file": FILE,
                    "patch": result.split("PATCH:\n", 1)[1], "source": "structured_model_transport",
                    "status": "diagnostic_only"})
            (self.output / f"{stem}-hive-contract.txt").write_text(result)
            record["status"] = "completed"
            return result
        except Exception as exc:
            record.update({"status": type(exc).__name__, "error": str(exc)})
            self.feedback = {"transport_error": type(exc).__name__ + ": " + str(exc)[:500]}
            raise
        finally:
            record["wall_ms"] = (time.monotonic() - started) * 1000
            self.checkpoint()


def generate(protocol, seed, baseline, runner, public, output, all_calls):
    output.mkdir()
    transport = RepairTransport(protocol, seed, (baseline / FILE).read_text(), public, output, all_calls)
    task = {"id": f"experiment3-{seed}", "target_file": FILE, "target_symbol": SYMBOL,
            "task_type": "bugfix", "change_intent": "modify_existing_logic", "expected_operation": "modify_logic",
            "note": f"Repair JSON extraction in {SYMBOL} in {FILE}. " + protocol["contract"],
            "metadata": {"target_file": FILE, "target_symbol": SYMBOL}}
    capture = {"seed": seed, "status": "blocked", "public_smokes": []}

    class SmokeExecutor:
        def test_patch_in_sandbox(self, patch_text, target_file, patch_reason=""):
            try:
                with tempfile.TemporaryDirectory(prefix="hive-exp3-smoke-") as tmp:
                    subject = Path(tmp) / "subject"
                    stage_patch(baseline, subject, {"target_file": target_file, "patch": patch_text})
                    scored = evaluate_cases(runner, subject, public, 0)
                    feedback = public_feedback(scored)
                    transport.feedback = feedback
                    capture["public_smokes"].append({"attempt": len(transport.patches)-1, "scores": scored})
                    ok = scored["valid"] and all(s["correct"] for s in scored["scores"])
                    return {"applied": True, "syntax_valid": True, "semantic_valid": ok,
                            "errors": [] if ok else ["Frozen public cases failed: " + json.dumps(feedback)],
                            "notes": "Docker-only public feedback; no held-out access"}
            except Exception as exc:
                transport.feedback = {"public_sandbox_error": str(exc)[:500]}
                return {"applied": False, "syntax_valid": False, "semantic_valid": False, "errors": [str(exc)]}

    with tempfile.TemporaryDirectory(prefix="hive-exp3-agents-") as tmp:
        generation_repo = Path(tmp) / "repo"
        shutil.copytree(baseline, generation_repo)
        with baseline_agents(generation_repo) as (planner_module, coder_module):
            state = generation_context(generation_repo, task)
            planner_module.ask_hive = coder_module.ask_hive = transport
            planner = planner_module.PlannerAgent(state_manager=state)
            coder = coder_module.CoderAgent(state_manager=state, executor=SmokeExecutor())
            if coder._target_is_top_level_function(FILE, SYMBOL):
                raise RuntimeError("Host behavioral execution gate must be inapplicable to this class method")
            with (output / "agents.log").open("w") as log, redirect_stdout(log):
                try:
                    capture["plan"] = plan = planner.plan_task(task)
                    if transport.plan is None or plan.get("status") == "blocked" or plan.get("source") != "llm":
                        raise ValueError("Planner did not produce an approved grounded plan")
                    result = coder.generate_patch_with_revisions(task, plan, coder._build_initial_pass_reflector(),
                                                                 max_revisions=protocol["generation"]["max_revisions"])
                    capture["patch_data"] = result
                    CandidatePolicy(editable_targets=frozenset({FILE})).validate_patch_data(result)
                    if result.get("source") != "llm":
                        raise ValueError("Only a model-authored Hive proposal can count")
                    capture["status"] = "proposed"
                except Exception as exc:
                    capture["error"] = type(exc).__name__ + ": " + str(exc)
    capture["transport_patches"] = transport.patches
    capture["cost"] = cost_report(transport.calls)
    write(output / "generation.json", capture)
    return capture


def score_plans(cases, responses):
    if not isinstance(responses, list) or len(responses) != len(cases):
        raise ValueError("Plan response count mismatch")
    by_id = {}
    expected = {c["id"] for c in cases}
    for row in responses:
        if not isinstance(row, dict) or row.get("id") not in expected or row["id"] in by_id:
            raise ValueError("Unexpected or duplicate plan response")
        by_id[row["id"]] = row
    result = []
    for case in cases:
        plan = by_id[case["id"]].get("plan")
        tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
        correct = (isinstance(plan, dict) and plan.get("source") == "llm"
                   and plan.get("status") != "blocked" and plan.get("goal") == case["expected_goal"]
                   and isinstance(tasks, list) and len(tasks) == 1 and isinstance(tasks[0], dict)
                   and tasks[0].get("target_file") == FILE and tasks[0].get("target_symbol") == SYMBOL
                   and tasks[0].get("change_intent") == "modify_existing_logic")
        result.append({"case_id": case["id"], "correct": bool(correct), "response": by_id[case["id"]]})
    return result


def evaluate_plans(runner, subject, cases, seed):
    import random
    ordered = list(cases); random.Random(seed).shuffle(ordered)
    run = runner.run(subject, "plan", {"inputs": [{"id": c["id"], "input": c["input"]} for c in ordered]})
    try:
        if run.status != "completed":
            raise ValueError("Plan batch did not complete")
        scores = score_plans(cases, strict_json(run.stdout))
        return {"valid": True, "scores": scores, "run": asdict(run)}
    except (ValueError, KeyError, TypeError):
        return {"valid": False, "scores": [{"case_id": c["id"], "correct": False} for c in cases], "run": asdict(run)}


def evaluate(protocol, baseline, candidate, runner, tests_runner, public, heldout, plans, baseline_tests):
    result = matched_evaluation(protocol, baseline, candidate, runner, tests_runner, public, heldout, baseline_tests)
    plan_trials = []
    for i, seed in enumerate(protocol["evaluation"]["shuffle_seeds"]):
        pair = {"seed": seed}
        order = [("baseline", baseline), ("candidate", candidate)]
        for label, subject in (order if i % 2 == 0 else reversed(order)):
            pair[label] = evaluate_plans(runner, subject, plans, seed)
        plan_trials.append(pair)
    result["plan_trials"] = plan_trials
    result["criteria"]["all_planner_response_replays"] = all(
        t["candidate"]["valid"] and all(s["correct"] for s in t["candidate"]["scores"]) for t in plan_trials)
    result["criteria"]["no_planner_replay_regression"] = all(
        not b["correct"] or c["correct"] for t in plan_trials
        for b, c in zip(t["baseline"]["scores"], t["candidate"]["scores"]))
    result["bounded_gates_passed"] = all(result["criteria"].values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True); parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(); args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=True)
    protocol = strict_json((HERE / "protocol.json").read_text())
    public, heldout, plans = [strict_json((HERE / name).read_text()) for name in
                             ("public_cases.json", "heldout_cases.json", "plan_cases.json")]
    frozen = strict_json((HERE / "frozen_sha256.json").read_text())
    if any(digest(ROOT / path) != sha for path, sha in frozen.items()):
        raise RuntimeError("Frozen study changed")
    for path in frozen:
        dest = args.output / "frozen_sources" / path; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, dest)
    calls = []
    report = {"experiment": protocol["experiment"], "status": "started", "promotion_allowed": False,
              "recursive_self_improvement_proven": False, "protocol_sha256": digest(HERE / "protocol.json"),
              "controller_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "baseline_commit": protocol["baseline_commit"], "python": platform.python_version(),
              "generation": [], "evaluations": {}, "candidates": []}
    write(args.output / "result.json", report)
    try:
        with tempfile.TemporaryDirectory(prefix="hive-experiment3-") as tmp:
            root = Path(tmp); baseline = root / "baseline"; baseline.mkdir()
            snapshot(baseline, protocol["baseline_commit"])
            for name in ("coder.py", "coder_validation.py"):
                if digest(baseline / name) != digest(ROOT / name):
                    raise RuntimeError("Trusted agents differ from pinned repaired baseline")
            baseline_hash = digest(baseline / FILE)
            harness = root / "harness"; harness.mkdir()
            shutil.copy2(HERE / "worker.py", harness / "worker.py")
            shutil.copy2(ROOT / "research/recursive_improvement/experiment2/worker.py", harness / "subject_worker.py")
            shutil.copy2(ROOT / "research/recursive_improvement/experiment2/regression_adapter.py", harness / "regression_adapter.py")
            limits = Limits(**{k: protocol["sandbox"][k] for k in asdict(Limits())})
            runner = StudyRunner(args.image, harness, limits)
            tests_runner = StudyRunner(args.image, harness, replace(limits, memory_mb=512, tmpfs_mb=128, wall_seconds=420))
            report["environment"] = runner.preflight()
            report["security_checks"] = security_checks(runner, baseline, args.output)
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
                report["model_identity"] = next(m for m in json.load(response)["models"] if m["name"] == protocol["model"])
            if report["model_identity"]["digest"] != protocol["model_digest"]:
                raise ValueError("Model identity changed before inference")
            write(args.output / "freeze.json", {"protocol": protocol, "frozen": frozen,
                "model": report["model_identity"], "environment": report["environment"], "timestamp_unix": time.time()})
            bt = report["baseline_repository_tests"] = pytest_summary(tests_runner.run(baseline, "pytest"))
            write(args.output / "result.json", report)
            if bt["run"]["status"] != "completed" or bt["failed"] or bt["passed"] < protocol["evaluation"]["minimum_repository_passes"]:
                raise RuntimeError("Baseline repository preflight failed before inference")
            report["baseline_recorded_regressions"] = recorded_regressions(runner, baseline, baseline)
            if not report["baseline_recorded_regressions"]["passed"]:
                raise RuntimeError("Baseline recorded regressions failed")
            for seed in protocol["generation"]["seeds"]:
                entry = generate(protocol, seed, baseline, runner, public, args.output / f"seed-{seed}", calls)
                report["generation"].append(entry); report["generation_cost"] = cost_report(calls)
                write(args.output / "result.json", report)
            # No held-out extraction or planning feedback exists before this point.
            for entry in report["generation"]:
                selected_sha = None
                if entry["status"] == "proposed":
                    selected = root / f"selected-{entry['seed']}"
                    stage_patch(baseline, selected, entry["patch_data"])
                    selected_sha = digest(selected / FILE)
                for patch in entry["transport_patches"]:
                    candidate = root / f"candidate-{entry['seed']}-{patch['attempt']}"
                    row = {"seed": entry["seed"], "attempt": patch["attempt"], "hive_selected": False, "bounded_gain": False}
                    report["candidates"].append(row)
                    try:
                        stage_patch(baseline, candidate, patch)
                    except Exception as exc:
                        row["staging_error"] = type(exc).__name__ + ": " + str(exc)
                        write(args.output / "result.json", report)
                        continue
                    sha = row["source_sha256"] = digest(candidate / FILE)
                    row["hive_selected"] = sha == selected_sha
                    (args.output / f"seed-{entry['seed']}" / f"candidate-{patch['attempt']}.patch").write_text(patch["patch"])
                    # Runtime/cleanup failures propagate and stop the study.
                    if sha not in report["evaluations"]:
                        report["evaluations"][sha] = evaluate(protocol, baseline, candidate, runner, tests_runner,
                                                             public, heldout, plans, bt)
                    row["bounded_gain"] = row["hive_selected"] and report["evaluations"][sha]["bounded_gates_passed"]
                    write(args.output / "result.json", report)
            report["status"] = "bounded_gain_observed" if any(c["bounded_gain"] for c in report["candidates"]) else "no_accepted_candidate"
            report["baseline_and_evaluation_unchanged"] = digest(baseline / FILE) == baseline_hash and all(
                digest(ROOT / path) == sha for path, sha in frozen.items())
            if not report["baseline_and_evaluation_unchanged"]:
                raise RuntimeError("Frozen study mutated")
    except Exception as exc:
        report.update({"status": "infrastructure_failed", "error": type(exc).__name__ + ": " + str(exc)})
        raise
    finally:
        report["generation_cost"] = cost_report(calls)
        write(args.output / "result.json", report)
        print(json.dumps({"status": report["status"], "cost": report["generation_cost"], "candidates": len(report["candidates"])}))


if __name__ == "__main__":
    main()
