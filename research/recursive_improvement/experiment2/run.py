"""Frozen Experiment 2; model code is data on the host and executes only in Docker."""
import argparse
from contextlib import redirect_stdout
from dataclasses import asdict, replace
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
import urllib.request

from research.recursive_improvement.container_runner import ContainerRunner, Limits
from research.recursive_improvement.experiment1.run import (
    baseline_agents, digest, evaluate_cases, generation_context, recorded_regressions,
    security_checks, snapshot, stage_patch, strict_json, summarize_generation_cost, write,
)
from research.recursive_improvement.gate import Trial, evaluate_candidate
from research.recursive_improvement.integration import CandidatePolicy, propose_candidate
from research.recursive_improvement.experiment2.structured import (
    FILE, SYMBOL, PLAN_SCHEMA, CODE_SCHEMA, compact_prompt, hive_plan,
    method_to_contract, validate_plan,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


class ExperimentRunner(ContainerRunner):
    def command(self, source, name, mode):
        command = super().command(source, name, mode)
        if mode == "pytest":
            command[command.index("fsize=1048576:1048576")] = "fsize=33554432:33554432"
        return command


def cost_report(calls):
    # Transport completion/usage and downstream schema validity are different.
    accounting = [{**c, "status": "completed" if c.get("done") is True and
                   all(type(c.get(k)) is int and c[k] >= 0 for k in ("prompt_eval_count", "eval_count"))
                   else c.get("status")} for c in calls]
    return summarize_generation_cost(accounting)


class StructuredTransport:
    def __init__(self, protocol, seed, original, public, output, all_calls):
        self.protocol, self.seed, self.original, self.public = protocol, seed, original, public
        self.output, self.all_calls, self.calls = output, all_calls, []
        self.plan, self.patch = None, None

    def __call__(self, original_prompt, role="default", **_):
        config = self.protocol["generation"]
        if role not in ("planner", "coder") or len(self.calls) >= 2 or len(self.all_calls) >= config["max_calls"]:
            raise RuntimeError("Frozen generation budget exhausted")
        if (role == "planner" and self.calls) or (role == "coder" and self.plan is None):
            raise RuntimeError("Planner approval required before Coder")
        prompt = compact_prompt(role, self.protocol, self.original, self.public, self.plan)
        if len(prompt) > config["max_prompt_characters"]:
            raise ValueError("Compact prompt envelope exceeded")
        record = {"role": role, "seed": self.seed, "status": "started", "prompt_characters": len(prompt)}
        self.calls.append(record)
        self.all_calls.append(record)
        (self.output / f"{role}-original-prompt.txt").write_text(original_prompt)
        (self.output / f"{role}-actual-prompt.txt").write_text(prompt)
        schema = PLAN_SCHEMA if role == "planner" else CODE_SCHEMA
        body = {"model": self.protocol["model"], "prompt": prompt, "stream": False, "format": schema,
                "options": {**{k: config[k] for k in ("temperature", "num_ctx", "num_thread")},
                            "seed": self.seed, "num_predict": config[f"{role}_output_tokens"]}}
        write(self.output / f"{role}-request.json", body)
        started = time.monotonic()
        try:
            request = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=config[f"{role}_timeout_seconds"]) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ValueError("Model response limit exceeded")
            data = strict_json(raw)
            write(self.output / f"{role}-raw-response.json", data)
            record.update({k: data.get(k) for k in ("done", "done_reason", "model", "prompt_eval_count", "eval_count", "total_duration", "eval_duration", "prompt_eval_duration")})
            if isinstance(data.get("response"), str):
                (self.output / f"{role}-response.txt").write_text(data["response"])
            if data.get("done") is not True or data.get("done_reason") == "length":
                raise ValueError("Incomplete or truncated structured response")
            if role == "planner":
                self.plan = validate_plan(data["response"])
                result = hive_plan(self.plan)
            else:
                result = method_to_contract(data["response"], self.original)
                self.patch = {"target_file": FILE, "patch": result.split("PATCH:\n", 1)[1],
                              "status": "diagnostic_only", "source": "structured_model_transport"}
            (self.output / f"{role}-hive-contract.txt").write_text(result)
            record["status"] = "completed"
            return result
        except Exception as exc:
            record["status"] = type(exc).__name__
            record["error"] = str(exc)
            raise
        finally:
            record["wall_ms"] = (time.monotonic() - started) * 1000
            write(self.output / "model-calls.json", self.calls)


def generate(protocol, seed, baseline, runner, public, output, all_calls):
    output.mkdir()
    transport = StructuredTransport(protocol, seed, (baseline / FILE).read_text(), public, output, all_calls)
    task = {"id": f"experiment2-{seed}", "target_file": FILE, "target_symbol": SYMBOL,
            "task_type": "bugfix", "change_intent": "modify_existing_logic", "expected_operation": "modify_logic",
            "note": f"Repair JSON extraction in {SYMBOL} in {FILE}. " + protocol["contract"],
            "metadata": {"target_file": FILE, "target_symbol": SYMBOL}}
    captures = {"seed": seed, "status": "blocked", "transport_override": "compact prompts + JSON schema; no semantic code repair"}

    class SmokeExecutor:
        def test_patch_in_sandbox(self, patch_text, target_file, patch_reason=""):
            try:
                with tempfile.TemporaryDirectory(prefix="hive-exp2-smoke-") as tmp:
                    variant = Path(tmp) / "subject"
                    stage_patch(baseline, variant, {"target_file": target_file, "patch": patch_text})
                    scored = evaluate_cases(runner, variant, public, 0)
                    captures["public_smoke"] = scored
                    ok = scored["valid"] and all(s["correct"] for s in scored["scores"])
                    return {"applied": True, "syntax_valid": True, "semantic_valid": ok,
                            "errors": [] if ok else ["Frozen public smoke failed"], "notes": "Docker-only smoke"}
            except Exception as exc:
                return {"applied": False, "syntax_valid": False, "semantic_valid": False, "errors": [str(exc)]}

    with tempfile.TemporaryDirectory(prefix="hive-exp2-generation-") as tmp:
        generation_repo = Path(tmp) / "repo"
        shutil.copytree(baseline, generation_repo)
        with baseline_agents(generation_repo) as (planner_module, coder_module):
            state = generation_context(generation_repo, task)
            write(output / "task.json", task)
            planner_module.ask_hive = coder_module.ask_hive = transport
            planner = planner_module.PlannerAgent(state_manager=state)
            coder = coder_module.CoderAgent(state_manager=state, executor=SmokeExecutor())
            class Planner:
                def plan_task(self, value):
                    captures["plan"] = planner.plan_task(value)
                    if transport.plan is None:
                        raise ValueError("Raw plan failed objective gate; Coder denied")
                    return captures["plan"]
            class Coder:
                def generate_patch(self, value, plan):
                    captures["patch_data"] = coder.generate_patch(value, plan)
                    return captures["patch_data"]
            with (output / "agents.log").open("w") as log, redirect_stdout(log):
                try:
                    proposal = propose_candidate(task, planner=Planner(), coder=Coder(),
                        policy=CandidatePolicy(editable_targets=frozenset({FILE})))
                    captures["proposal"] = asdict(proposal)
                    captures["status"] = "proposed"
                except Exception as exc:
                    captures["error"] = type(exc).__name__ + ": " + str(exc)
    # A diagnostic transport patch cannot become an accepted Hive proposal.
    captures["evaluation_patch"] = captures.get("patch_data") if captures["status"] == "proposed" else transport.patch
    captures["cost"] = cost_report(transport.calls)
    write(output / "generation.json", captures)
    return captures


def pytest_summary(run):
    import re
    matches = re.findall(r"(\d+) (passed|failed|skipped|error|errors)\b", run.stdout)
    counts = {key: int(value) for value, key in matches}
    return {"passed": counts.get("passed", 0), "failed": counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0),
            "skipped": counts.get("skipped", 0), "run": asdict(run)}


def matched_evaluation(protocol, baseline, candidate, runner, tests_runner, public, heldout, baseline_tests):
    seeds = protocol["evaluation"]["shuffle_seeds"]
    trials, decisions = [], []
    for index, seed in enumerate(seeds):
        order = [("baseline", baseline), ("candidate", candidate)]
        if index % 2:
            order.reverse()
        pair = {"seed": seed}
        for label, subject in order:
            pair[label] = {kind: evaluate_cases(runner, subject, cases, seed)
                           for kind, cases in (("public", public), ("heldout", heldout))}
        b, c = pair["baseline"]["heldout"], pair["candidate"]["heldout"]
        groups = [[Trial(s["case_id"], s["correct"], 0, group["run"]["wall_ms"] / len(heldout))
                   for s in group["scores"]] for group in (b, c)]
        e = protocol["evaluation"]
        decisions.append(asdict(evaluate_candidate(*groups, min_cases=e["minimum_distinct_heldout_cases"],
            min_accuracy_gain=e["minimum_accuracy_gain"], max_cost_increase=e["maximum_generation_cost_increase"])))
        trials.append(pair)
    legacy = pytest_summary(tests_runner.run(candidate, "pytest"))
    regressions = recorded_regressions(runner, candidate, baseline)
    btime = statistics.median(t["baseline"]["heldout"]["run"]["wall_ms"] for t in trials)
    ctime = statistics.median(t["candidate"]["heldout"]["run"]["wall_ms"] for t in trials)
    no_regression = all(not a["correct"] or b["correct"] for t in trials
        for a, b in zip(t["baseline"]["heldout"]["scores"], t["candidate"]["heldout"]["scores"]))
    criteria = {"all_accuracy_api_cost_gates": all(d["accepted"] for d in decisions),
        "valid_runs": all(t[label][kind]["valid"] for t in trials for label in ("baseline", "candidate") for kind in ("public", "heldout")),
        "all_public_correct": all(s["correct"] for t in trials for s in t["candidate"]["public"]["scores"]),
        "no_baseline_correct_regression": no_regression,
        "recorded_regressions": regressions["passed"],
        "repository_suite": legacy["run"]["status"] == "completed" and legacy["failed"] == 0 and
            legacy["passed"] == baseline_tests["passed"] and legacy["skipped"] == baseline_tests["skipped"],
        "host_latency": ctime / max(btime, protocol["evaluation"]["latency_floor_ms"]) <= protocol["evaluation"]["maximum_median_latency_ratio"]}
    return {"trials": trials, "decisions": decisions, "repository_tests": legacy, "recorded_regressions": regressions,
            "host_batch_latency_ms": {"baseline_median": btime, "candidate_median": ctime, "ratio": ctime / btime},
            "criteria": criteria, "bounded_gates_passed": all(criteria.values()),
            "cost_limit": "API charges only; complete compute/lifecycle dollar cost remains unknown."}


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
    frozen = json.loads((HERE / "frozen_sha256.json").read_text())
    if any(digest(ROOT / name) != sha for name, sha in frozen.items()):
        raise RuntimeError("Frozen study changed")
    for name in frozen:
        dest = args.output / "frozen_sources" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, dest)
    report = {"experiment": protocol["experiment"], "status": "started", "promotion_allowed": False,
              "recursive_self_improvement_proven": False, "protocol_sha256": digest(HERE / "protocol.json"),
              "controller_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "python": platform.python_version(), "generation": [], "evaluations": {}}
    write(args.output / "result.json", report)
    with tempfile.TemporaryDirectory(prefix="hive-experiment2-") as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        baseline.mkdir()
        snapshot(baseline, protocol["baseline_commit"])
        baseline_hash = digest(baseline / FILE)
        harness = root / "harness"
        harness.mkdir()
        for name in ("worker.py", "regression_adapter.py"):
            shutil.copy2(HERE / name, harness / name)
        limits = Limits(**{k: protocol["sandbox"][k] for k in asdict(Limits())})
        runner = ExperimentRunner(args.image, harness, limits)
        test_runner = ExperimentRunner(args.image, harness, replace(limits, memory_mb=512, tmpfs_mb=128, wall_seconds=420))
        report["environment"] = runner.preflight()
        report["security_checks"] = security_checks(runner, baseline, args.output)
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
            report["model_identity"] = next(m for m in json.load(response)["models"] if m["name"] == protocol["model"])
        if not report["model_identity"]["digest"].startswith(protocol["model_digest_prefix"]):
            raise ValueError("Model digest changed before study")
        write(args.output / "freeze.json", {"protocol": protocol, "frozen": frozen, "model": report["model_identity"],
                                            "environment": report["environment"], "timestamp_unix": time.time()})
        report["baseline_repository_tests"] = pytest_summary(test_runner.run(baseline, "pytest"))
        bt = report["baseline_repository_tests"]
        write(args.output / "result.json", report)
        if bt["run"]["status"] != "completed" or bt["failed"] or bt["passed"] < protocol["evaluation"]["minimum_repository_passes"]:
            raise RuntimeError("Baseline regression compatibility failed before generation")
        report["baseline_recorded_regressions"] = recorded_regressions(runner, baseline, baseline)
        if not report["baseline_recorded_regressions"]["passed"]:
            raise RuntimeError("Baseline recorded regressions failed")
        calls = []
        # Finish the entire generation cohort before any held-out candidate feedback.
        for seed in protocol["generation"]["seeds"]:
            entry = generate(protocol, seed, baseline, runner, public, args.output / f"seed-{seed}", calls)
            report["generation"].append(entry)
            report["generation_cost"] = cost_report(calls)
            write(args.output / "result.json", report)
        for entry in report["generation"]:
            patch_data = entry.get("evaluation_patch")
            if not patch_data:
                continue
            candidate = root / f"candidate-{entry['seed']}"
            try:
                stage_patch(baseline, candidate, patch_data)
            except Exception as exc:
                entry["staging_failure"] = str(exc)
                continue
            sha = digest(candidate / FILE)
            entry["candidate_source_sha256"] = sha
            (args.output / f"seed-{entry['seed']}" / "candidate.patch").write_text(patch_data["patch"])
            if sha not in report["evaluations"]:
                report["evaluations"][sha] = matched_evaluation(protocol, baseline, candidate, runner, test_runner, public, heldout, bt)
            entry["bounded_gain"] = entry["status"] == "proposed" and report["evaluations"][sha]["bounded_gates_passed"]
            write(args.output / "result.json", report)
        report["status"] = "bounded_gain_observed" if any(e.get("bounded_gain") for e in report["generation"]) else "no_accepted_candidate"
        report["baseline_and_evaluation_unchanged"] = digest(baseline / FILE) == baseline_hash and all(digest(ROOT / n) == s for n, s in frozen.items())
        if not report["baseline_and_evaluation_unchanged"]:
            raise RuntimeError("Frozen baseline/evaluation changed")
        report["claim_limit"] = protocol["claim_limit"]
        write(args.output / "result.json", report)
        print(json.dumps({"status": report["status"], "generation_cost": report["generation_cost"],
                          "proposed": sum(e["status"] == "proposed" for e in report["generation"]),
                          "unique_evaluated": len(report["evaluations"])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if "--output" in __import__("sys").argv:
            argv = __import__("sys").argv
            path = Path(argv[argv.index("--output") + 1]) / "result.json"
            if path.exists():
                report = json.loads(path.read_text())
                report.update({"status": "infrastructure_failed", "error": type(exc).__name__ + ": " + str(exc)})
                write(path, report)
        raise
