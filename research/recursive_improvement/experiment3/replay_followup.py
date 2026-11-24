"""No inference: diagnose the scratch-CWD failure using the exact frozen patches."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from research.recursive_improvement.experiment1.run import digest, snapshot, stage_patch, strict_json, write
from research.recursive_improvement.experiment2.run import security_checks
from research.recursive_improvement.experiment3.run import StudyRunner, evaluate_plans


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


class ReplayRunner(StudyRunner):
    def command(self, source, name, mode):
        command = super().command(source, name, "plan" if mode == "plan_probe" else mode)
        if mode == "plan_probe":
            command[-1] = mode
        return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    frozen = strict_json((HERE / "replay_frozen_sha256.json").read_text())
    if any(digest(ROOT / path) != sha for path, sha in frozen.items()):
        raise RuntimeError("Frozen diagnostic changed")
    for path in frozen:
        dest = args.output / "frozen_sources" / path; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, dest)
    protocol = strict_json((HERE / "protocol.json").read_text())
    plans = strict_json((HERE / "plan_cases.json").read_text())
    records = strict_json((ROOT / "docs/research/experiment3/candidates.json").read_text())
    report = {"status": "started", "diagnostic_only": True, "inference_requests": 0,
              "promotion_allowed": False, "original_experiment_status": "no_accepted_candidate",
              "original_run_id": 45334226981,
              "source_artifact_sha256": "61fef5f6cc04d75e6769e7cac3402a927d3aca8e8883056aa125d99990246a16", "baseline_commit": protocol["baseline_commit"],
              "controller_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "plan_cases_sha256": digest(HERE / "plan_cases.json"), "evaluations": {}}
    write(args.output / "result.json", report)
    try:
        with tempfile.TemporaryDirectory(prefix="hive-exp3-replay-") as tmp:
            root = Path(tmp); baseline = root / "baseline"; baseline.mkdir()
            snapshot(baseline, protocol["baseline_commit"])
            harness = root / "harness"; harness.mkdir()
            shutil.copy2(HERE / "replay_worker.py", harness / "worker.py")
            shutil.copy2(ROOT / "research/recursive_improvement/experiment2/worker.py", harness / "subject_worker.py")
            runner = ReplayRunner(args.image, harness)
            report["environment"] = runner.preflight()
            report["security_checks"] = security_checks(runner, baseline, args.output)
            probe = runner.run(baseline, "plan_probe")
            report["original_cwd_probe"] = asdict(probe)
            data = strict_json(probe.stdout)
            if probe.status != "completed" or data.get("errno") != 30 or data.get("filename") != "hive_lessons.jsonl":
                raise RuntimeError("Original initialization failure was not confirmed")
            for row in records:
                candidate = root / f"candidate-{row['seed']}-{row['attempt']}"
                filename = row["patch_file"]
                if Path(filename).name != filename:
                    raise ValueError("Unsafe patch artifact name")
                patch = (ROOT / "docs/research/experiment3" / filename).read_text()
                stage_patch(baseline, candidate, {"target_file": "planner.py", "patch": patch})
                sha = digest(candidate / "planner.py")
                if sha != row["source_sha256"]:
                    raise RuntimeError("Archived candidate source changed")
                if sha in report["evaluations"]:
                    continue
                trials = []
                for i, seed in enumerate(protocol["evaluation"]["shuffle_seeds"]):
                    pair = {"seed": seed}
                    order = [("baseline", baseline), ("candidate", candidate)]
                    for label, subject in (order if i % 2 == 0 else reversed(order)):
                        pair[label] = evaluate_plans(runner, subject, plans, seed)
                        if not pair[label]["valid"]:
                            raise RuntimeError("Replay response envelope invalid")
                        if label == "baseline" and not pair[label]["scores"][0]["correct"]:
                            raise RuntimeError("Clean baseline positive control failed after scratch repair")
                    trials.append(pair)
                report["evaluations"][sha] = {"trials": trials}
                write(args.output / "result.json", report)
        report["status"] = "diagnostic_complete"
        report["frozen_unchanged"] = all(digest(ROOT / path) == sha for path, sha in frozen.items())
        if not report["frozen_unchanged"]:
            raise RuntimeError("Diagnostic changed during execution")
    except Exception as exc:
        report.update({"status": "infrastructure_failed", "error": type(exc).__name__ + ": " + str(exc)})
        raise
    finally:
        write(args.output / "result.json", report)
        print(json.dumps({"status": report["status"], "inference_requests": 0, "evaluated": len(report["evaluations"])}))


if __name__ == "__main__":
    main()
