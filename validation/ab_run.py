"""Paired A/B experiment for measuring Hive lesson reuse.

Unlike the older pack-level A/B helper, this runner keeps one shared lesson store
for the ordered task sequence in each arm. That makes improvement over time
observable: the lessons-on arm can reuse failures from earlier tasks, while the
lessons-off arm receives the same tasks and model responses without memory reuse.
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
from pathlib import Path
from typing import Callable, Iterable

from benchmark_harness import ReliabilityBenchmarkHarness
from benchmark_pack import build_reliability_benchmark_pack
from validation.experiment_cases import build_lesson_reuse_experiment_pack


HarnessFactory = Callable[[], ReliabilityBenchmarkHarness]


def _arm_metrics(records: Iterable[dict]) -> dict:
    records = list(records)
    passed = sum(bool((record.get("pass_fail_record") or {}).get("passed")) for record in records)
    accepted = sum(record.get("final_status") == "proposed" for record in records)
    retries = sum(int(record.get("retry_count") or 0) for record in records)
    regressions = len(records) - passed
    return {
        "cases": len(records),
        "passed_cases": passed,
        "accepted_patches": accepted,
        "total_retries": retries,
        "mean_retries": (retries / len(records)) if records else 0.0,
        "true_regressions": regressions,
    }


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _paired_summary(repeats: list[dict]) -> dict:
    metric_names = (
        "passed_cases",
        "accepted_patches",
        "total_retries",
        "mean_retries",
        "true_regressions",
    )
    summary = {}
    for metric in metric_names:
        with_values = [float(item["with_lessons"][metric]) for item in repeats]
        without_values = [float(item["without_lessons"][metric]) for item in repeats]
        deltas = [with_value - without_value for with_value, without_value in zip(with_values, without_values)]
        variance = statistics.variance(deltas) if len(deltas) > 1 else 0.0
        standard_error = (variance / len(deltas)) ** 0.5 if deltas else 0.0
        summary[metric] = {
            "with_lessons_mean": _mean(with_values),
            "without_lessons_mean": _mean(without_values),
            "paired_delta_mean": _mean(deltas),
            "paired_delta_variance": variance,
            "paired_delta_standard_error": standard_error,
            "paired_deltas": deltas,
        }
    return summary


def _effect_exceeds_uncertainty(metric: dict, *, direction: str) -> bool:
    delta = float(metric["paired_delta_mean"])
    uncertainty = 2.0 * float(metric["paired_delta_standard_error"])
    if direction == "positive":
        return delta > uncertainty
    if direction == "negative":
        return delta < -uncertainty
    raise ValueError(f"Unknown effect direction: {direction}")


def _verdict(summary: dict, repeats: int) -> str:
    pass_metric = summary["passed_cases"]
    retry_metric = summary["total_retries"]
    regression_metric = summary["true_regressions"]

    pass_delta = pass_metric["paired_delta_mean"]
    retry_delta = retry_metric["paired_delta_mean"]
    regression_delta = regression_metric["paired_delta_mean"]

    if repeats < 2:
        return "inconclusive_insufficient_repeats"
    if _effect_exceeds_uncertainty(regression_metric, direction="positive"):
        return "lessons_hurt"
    if _effect_exceeds_uncertainty(pass_metric, direction="negative"):
        return "lessons_hurt"

    pass_help = _effect_exceeds_uncertainty(pass_metric, direction="positive")
    retry_help = _effect_exceeds_uncertainty(retry_metric, direction="negative")
    no_regression_harm = regression_delta <= 0

    if pass_help and retry_delta <= 0 and no_regression_harm:
        return "lessons_help"
    if retry_help and pass_delta >= 0 and no_regression_harm:
        return "lessons_help_efficiency_only"
    if pass_delta == 0 and retry_delta == 0 and regression_delta == 0:
        return "no_measured_difference"
    return "inconclusive"


def run_sequence_ab(
    *,
    cases: Iterable[dict] | None = None,
    repeats: int = 3,
    harness_factory: HarnessFactory = ReliabilityBenchmarkHarness,
    live_model: bool = False,
    output_path: str | Path | None = None,
) -> dict:
    """Run paired lessons-on/off sequences and return aggregate evidence."""

    if repeats < 1:
        raise ValueError("A/B experiment requires at least one repeat")

    base_cases = list(build_reliability_benchmark_pack() if cases is None else cases)
    if not base_cases:
        raise ValueError("A/B experiment requires at least one case")

    prepared_cases = copy.deepcopy(base_cases)
    if live_model:
        for case in prepared_cases:
            case["live_coder"] = True
            case["live_reflector"] = True

    repeat_records = []
    for repeat_index in range(repeats):
        if repeat_index % 2 == 0:
            arm_order = ["with_lessons", "without_lessons"]
            on_records = harness_factory().run_sequence(copy.deepcopy(prepared_cases), lessons_enabled=True)
            off_records = harness_factory().run_sequence(copy.deepcopy(prepared_cases), lessons_enabled=False)
        else:
            arm_order = ["without_lessons", "with_lessons"]
            off_records = harness_factory().run_sequence(copy.deepcopy(prepared_cases), lessons_enabled=False)
            on_records = harness_factory().run_sequence(copy.deepcopy(prepared_cases), lessons_enabled=True)

        repeat_records.append(
            {
                "repeat_index": repeat_index,
                "arm_order": arm_order,
                "case_order": [case.get("name") for case in prepared_cases],
                "with_lessons": _arm_metrics(on_records),
                "without_lessons": _arm_metrics(off_records),
                "case_pairs": [
                    {
                        "name": on_record.get("name"),
                        "with_lessons": {
                            "passed": bool((on_record.get("pass_fail_record") or {}).get("passed")),
                            "final_status": on_record.get("final_status"),
                            "retry_count": int(on_record.get("retry_count") or 0),
                            "failure_code": on_record.get("failure_code"),
                        },
                        "without_lessons": {
                            "passed": bool((off_record.get("pass_fail_record") or {}).get("passed")),
                            "final_status": off_record.get("final_status"),
                            "retry_count": int(off_record.get("retry_count") or 0),
                            "failure_code": off_record.get("failure_code"),
                        },
                    }
                    for on_record, off_record in zip(on_records, off_records)
                ],
            }
        )

    paired = _paired_summary(repeat_records)
    report = {
        "schema_version": 1,
        "experiment": "same_task_sequence_lessons_on_vs_off",
        "repeats": repeats,
        "case_count": len(prepared_cases),
        "live_model": bool(live_model),
        "counterbalanced_arm_order": True,
        "decision_rule": "paired mean effect must exceed two standard errors without added regressions",
        "paired_summary": paired,
        "verdict": _verdict(paired, repeats),
        "repeat_records": repeat_records,
        "interpretation": (
            "A lessons-on advantage is reported only when its paired effect exceeds two standard errors "
            "and does not introduce additional regressions. Arm order alternates between repeats."
        ),
    }

    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hive's paired lesson-memory A/B experiment")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--live", action="store_true", help="Use the configured live coder and reflector model")
    parser.add_argument(
        "--pack",
        choices=("lesson-reuse", "reliability"),
        default=None,
        help="Use the deterministic lesson-reuse contract pack or the broader reliability pack",
    )
    parser.add_argument("--output", default="validation/results/lesson_ab.json")
    args = parser.parse_args()

    selected_pack = args.pack or ("reliability" if args.live else "lesson-reuse")
    cases = (
        build_lesson_reuse_experiment_pack()
        if selected_pack == "lesson-reuse"
        else build_reliability_benchmark_pack()
    )
    report = run_sequence_ab(
        cases=cases,
        repeats=args.repeats,
        live_model=args.live,
        output_path=args.output,
    )
    print(json.dumps({
        "verdict": report["verdict"],
        "repeats": report["repeats"],
        "case_count": report["case_count"],
        "live_model": report["live_model"],
        "pack": selected_pack,
        "paired_summary": report["paired_summary"],
        "output": args.output,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
