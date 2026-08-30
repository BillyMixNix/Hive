"""Luna compression frontier v1.2 matched-baseline protocol.

Protocol v1.2 preserves the frozen v1.1 apparatus and replaces the Raw
perfection gate with the comparison the experiment actually needs: all four
representations run, and each compressed condition is scored case-by-case
against the contemporaneous Raw result from the same frozen execution.
"""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hive_llm import ask_hive
from kingdom import decompression_frontier_luna as v1
from kingdom import decompression_frontier_luna_v1_1 as v1_1
from kingdom import decompression_test as worlds
from kingdom import decompression_test_v2 as grading


PROTOCOL_ID = "hive-luna-compression-frontier-v1.2"
PROTOCOL_VERSION = "1.2"
SCHEMA_VERSION = v1_1.SCHEMA_VERSION
MAX_OUTPUT_TOKENS = v1_1.MAX_OUTPUT_TOKENS
AUTHORIZED_COST_CEILING_USD = v1_1.AUTHORIZED_COST_CEILING_USD
RUN_DIR = Path(".hive/benchmarks/decompression_test/luna-frontier-v1-2-001")
PRIMARY_COMPRESSED_CONDITION = "C0"
LOW_CAPABILITY_MAX_CORRECT = 10
SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *v1_1.SOURCE_FILES,
            "kingdom/decompression_frontier_luna_v1_2.py",
            "benchmarks/decompression_test/PROTOCOL_LUNA_FRONTIER_V1_2.md",
            "tests/test_decompression_frontier_luna_v1_2.py",
        )
    )
)


def _correct(score: grading.LabelScore) -> bool:
    return score.answer_correct is True


def _score_map(
    scores: Sequence[grading.LabelScore], *, condition: str
) -> dict[str, grading.LabelScore]:
    mapped = {score.case_id: score for score in scores}
    if len(scores) != 20 or len(mapped) != 20:
        raise v1.ApparatusFailure(f"{condition} does not contain 20 unique scores")
    if any(score.condition != condition for score in scores):
        raise v1.ApparatusFailure(f"{condition} score identity drifted")
    return mapped


def paired_comparison(
    baseline_scores: Sequence[grading.LabelScore],
    candidate_scores: Sequence[grading.LabelScore],
    *,
    baseline_condition: str,
    candidate_condition: str,
    case_order: Sequence[str],
) -> dict[str, Any]:
    baseline = _score_map(baseline_scores, condition=baseline_condition)
    candidate = _score_map(candidate_scores, condition=candidate_condition)
    if set(baseline) != set(candidate) or set(baseline) != set(case_order):
        raise v1.ApparatusFailure(
            f"{candidate_condition} is not case-matched to {baseline_condition}"
        )
    rows = []
    counts = {
        "both_correct": 0,
        "baseline_only_correct": 0,
        "candidate_only_correct": 0,
        "both_wrong": 0,
    }
    outcome_case_ids = {name: [] for name in counts}
    selected_label_agreement = 0
    for case_id in case_order:
        baseline_score = baseline[case_id]
        candidate_score = candidate[case_id]
        baseline_correct = _correct(baseline_score)
        candidate_correct = _correct(candidate_score)
        if baseline_correct and candidate_correct:
            outcome = "both_correct"
        elif baseline_correct:
            outcome = "baseline_only_correct"
        elif candidate_correct:
            outcome = "candidate_only_correct"
        else:
            outcome = "both_wrong"
        counts[outcome] += 1
        outcome_case_ids[outcome].append(case_id)
        if baseline_score.selected_label == candidate_score.selected_label:
            selected_label_agreement += 1
        rows.append(
            {
                "case_id": case_id,
                "outcome": outcome,
                "baseline_selected_label": baseline_score.selected_label,
                "candidate_selected_label": candidate_score.selected_label,
                "expected_label": baseline_score.expected_label,
                "baseline_admissible": baseline_score.admissible,
                "candidate_admissible": candidate_score.admissible,
                "baseline_chronology_authority_error": (
                    baseline_score.chronology_authority_error
                ),
                "candidate_chronology_authority_error": (
                    candidate_score.chronology_authority_error
                ),
                "baseline_illegal_state_promotions": (
                    baseline_score.illegal_state_promotions
                ),
                "candidate_illegal_state_promotions": (
                    candidate_score.illegal_state_promotions
                ),
            }
        )
    baseline_correct_count = sum(_correct(score) for score in baseline_scores)
    candidate_correct_count = sum(_correct(score) for score in candidate_scores)
    baseline_chronology = sum(
        score.chronology_authority_error is True for score in baseline_scores
    )
    candidate_chronology = sum(
        score.chronology_authority_error is True for score in candidate_scores
    )
    baseline_promotions = sum(
        score.illegal_state_promotions or 0 for score in baseline_scores
    )
    candidate_promotions = sum(
        score.illegal_state_promotions or 0 for score in candidate_scores
    )
    baseline_admissible = sum(score.admissible for score in baseline_scores)
    candidate_admissible = sum(score.admissible for score in candidate_scores)
    quality_not_worse = (
        candidate_correct_count >= baseline_correct_count
        and candidate_chronology <= baseline_chronology
        and candidate_promotions <= baseline_promotions
        and candidate_admissible >= baseline_admissible
    )
    return {
        "baseline_condition": baseline_condition,
        "candidate_condition": candidate_condition,
        "total_matched_cases": 20,
        **counts,
        **{f"{name}_case_ids": ids for name, ids in outcome_case_ids.items()},
        "selected_label_agreement": selected_label_agreement,
        "baseline_exact_correct": baseline_correct_count,
        "candidate_exact_correct": candidate_correct_count,
        "exact_correct_delta_candidate_minus_baseline": (
            candidate_correct_count - baseline_correct_count
        ),
        "baseline_admissible": baseline_admissible,
        "candidate_admissible": candidate_admissible,
        "admissible_delta_candidate_minus_baseline": (
            candidate_admissible - baseline_admissible
        ),
        "baseline_chronology_authority_errors": baseline_chronology,
        "candidate_chronology_authority_errors": candidate_chronology,
        "chronology_authority_error_delta_candidate_minus_baseline": (
            candidate_chronology - baseline_chronology
        ),
        "baseline_illegal_state_promotions": baseline_promotions,
        "candidate_illegal_state_promotions": candidate_promotions,
        "illegal_state_promotion_delta_candidate_minus_baseline": (
            candidate_promotions - baseline_promotions
        ),
        "quality_not_worse_than_baseline": quality_not_worse,
        "per_case_zero_distortion": (
            quality_not_worse and counts["baseline_only_correct"] == 0
        ),
        "cases": rows,
    }


def _primary_result(
    *,
    raw_summary: Mapping[str, Any],
    c0_summary: Mapping[str, Any],
    c0_comparison: Mapping[str, Any],
    representation_totals: Mapping[str, int],
    max_correct_across_conditions: int,
) -> tuple[str, Mapping[str, Any]]:
    raw_correct = int(raw_summary["exact_correct"])
    c0_correct = int(c0_summary["exact_correct"])
    reduced = representation_totals[PRIMARY_COMPRESSED_CONDITION] < representation_totals["raw"]
    low_capability = max_correct_across_conditions <= LOW_CAPABILITY_MAX_CORRECT
    if low_capability:
        result_code = "VALID_INCONCLUSIVE_LOW_SOLVER_CAPABILITY"
        evidence_label = "INCONCLUSIVE"
        reason = (
            "Raw and C0 were both at or below the frozen low-capability ceiling; "
            "representation quality is not isolated."
        )
    elif reduced and bool(c0_comparison["quality_not_worse_than_baseline"]):
        result_code = "VALID_SUPPORTED_C0_VS_RAW"
        evidence_label = "SUPPORTED"
        reason = (
            "C0 supplied fewer representation bytes while matching or improving "
            "Raw correctness, admissibility, chronology/authority errors, and "
            "illegal promotions on the same 20 cases."
        )
    else:
        result_code = "VALID_NOT_SUPPORTED_C0_VS_RAW"
        evidence_label = "NOT_SUPPORTED"
        reason = (
            "C0 did not satisfy the frozen no-regression criteria against Raw "
            "on this matched 20-case execution."
        )
    aggregate_supported = (
        evidence_label == "SUPPORTED"
        and bool(c0_comparison["quality_not_worse_than_baseline"])
    )
    zero_distortion_supported = (
        aggregate_supported and bool(c0_comparison["per_case_zero_distortion"])
    )
    return result_code, {
        "claim": (
            "The full compact representation preserves enough usable causal, "
            "temporal, and authority structure to match or improve Raw on the "
            "frozen benchmark while supplying less state."
        ),
        "evidence_label": evidence_label,
        "benchmark_scope": "frozen 20-case Luna v1.2 smoke only",
        "representation_bytes_reduced": reduced,
        "aggregate_usable_performance": (
            "SUPPORTED" if aggregate_supported else evidence_label
        ),
        "per_case_zero_distortion": (
            "SUPPORTED" if zero_distortion_supported else "NOT_SUPPORTED"
        ),
        "quality_not_worse_than_raw": c0_comparison[
            "quality_not_worse_than_baseline"
        ],
        "reason": reason,
        "broad_hive_claim": "NOT_PROVEN",
        "replication_required": True,
    }


def _relative_frontier(
    adjacent_comparisons: Mapping[str, Mapping[str, Any]],
    representation_totals: Mapping[str, int],
) -> Mapping[str, Any]:
    passed = []
    first_failure = None
    steps = (
        ("C0", "raw", "C0_vs_raw"),
        ("C1", "C0", "C1_vs_C0"),
        ("C2", "C1", "C2_vs_C1"),
    )
    for level, predecessor, comparison_name in steps:
        qualifies = (
            representation_totals[level] < representation_totals[predecessor]
            and bool(
                adjacent_comparisons[comparison_name][
                    "quality_not_worse_than_baseline"
                ]
            )
        )
        if qualifies and first_failure is None:
            passed.append(level)
        elif first_failure is None:
            first_failure = level
    return {
        "criterion": (
            "each level must be smaller and show no regression against its immediate "
            "predecessor in correctness, admissibility, chronology/authority errors, "
            "or promotions"
        ),
        "deepest_consecutive_passing_level": passed[-1] if passed else None,
        "first_failing_level": first_failure,
        "right_censored_after_C2": len(passed) == len(v1.LEVELS),
    }


@contextmanager
def _v1_2_bindings():
    replacements = {
        "PROTOCOL_ID": PROTOCOL_ID,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "SCHEMA_VERSION": SCHEMA_VERSION,
        "MAX_OUTPUT_TOKENS": MAX_OUTPUT_TOKENS,
        "AUTHORIZED_COST_CEILING_USD": AUTHORIZED_COST_CEILING_USD,
        "RUN_DIR": RUN_DIR,
        "SOURCE_FILES": SOURCE_FILES,
        "OpenAIAuditStore": v1_1.CompletionAuditStore,
        "_score_summary": v1_1._score_summary,
    }
    originals = {name: getattr(v1, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v1, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(v1, name, value)


def deterministic_preflight(repo_root: Path, *, require_committed: bool = True):
    with _v1_2_bindings():
        return _bound_preflight(repo_root, require_committed=require_committed)


def _bound_preflight(repo_root: Path, *, require_committed: bool):
    payload, cases, calls, inherited = v1.deterministic_preflight(
        repo_root, require_committed=require_committed
    )
    rewritten = dict(inherited)
    rewritten.pop("payload_sha256", None)
    rewritten.pop("raw_gate", None)
    rewritten["raw_baseline"] = {
        "calls": v1.RAW_CALLS,
        "cases": 20,
        "required_exact_correct": None,
        "required_illegal_promotions": None,
        "stops_frontier_on_solver_error": False,
        "apparatus_failure_still_stops_run": True,
    }
    rewritten["all_conditions_run_unless_apparatus_failure"] = True
    return payload, cases, calls, v1._sealed(rewritten)


class MatchedBaselineRunner(v1_1.CompletionRunner):
    def __init__(
        self,
        *,
        repo_root: Path,
        output_dir: Path,
        ask_fn: Callable[..., str] = ask_hive,
        require_committed: bool = True,
    ) -> None:
        super().__init__(
            repo_root=repo_root,
            output_dir=output_dir,
            ask_fn=ask_fn,
            require_committed=require_committed,
        )

    def run(self) -> Mapping[str, Any]:
        with _v1_2_bindings():
            return self._run_v1_2()

    def _run_v1_2(self) -> Mapping[str, Any]:
        payload, cases, calls, preflight = _bound_preflight(
            self.repo_root, require_committed=self.require_committed
        )
        by_case = {case.case_id: case for case in cases}
        case_order = [case.case_id for case in cases]
        audit = v1_1.CompletionAuditStore(
            self.output_dir, ask_fn=self.ask_fn, config=self.config
        )
        v1._write_exclusive(
            self.output_dir / "PRECHECK.json", v1._pretty_json(preflight)
        )
        v1._write_exclusive(
            self.output_dir / "PROTOCOL_BASELINE.json",
            v1._pretty_json(
                v1._sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "protocol_version": PROTOCOL_VERSION,
                        "sole_material_change_from_v1_1": (
                            "Raw is a comparison baseline rather than a 20/20 stop gate; "
                            "all 24 calls run unless the apparatus fails"
                        ),
                        "primary_comparison": "C0 versus Raw, paired by case",
                        "raw_perfection_required": False,
                        "all_conditions_matched": True,
                        "prompt_or_representation_change": False,
                        "retry_or_repair": False,
                        "low_capability_max_correct": LOW_CAPABILITY_MAX_CORRECT,
                    }
                )
            ),
        )
        manifest = v1._sealed(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "protocol_version": PROTOCOL_VERSION,
                "created_at_utc": v1._utc_now(),
                "source_revision": preflight["source_revision"],
                "precheck_sha256": preflight["payload_sha256"],
                "solver_config": self.config.to_mapping(),
                "solver_config_sha256": self.config.configuration_hash,
                "expected_openai_sdk": v1.EXPECTED_OPENAI_SDK,
                "generation_call_budget": {
                    "raw_baseline": v1.RAW_CALLS,
                    "compressed_conditions": v1.FRONTIER_CALLS,
                    "total": v1.MAX_GENERATION_CALLS,
                    "attempts_per_call": 1,
                },
                "raw_is_comparison_baseline": True,
                "raw_is_perfection_gate": False,
                "all_conditions_run_unless_apparatus_failure": True,
                "no_retry": True,
                "no_repair": True,
                "no_prompt_tuning_after_outputs": True,
            }
        )
        v1._write_exclusive(
            self.output_dir / "MANIFEST.json", v1._pretty_json(manifest)
        )
        try:
            for planned in calls:
                self._run_call(audit, planned, by_case)
        except v1.ApparatusFailure as exc:
            result = {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "validity": "INVALID",
                "result_code": "INVALID_APPARATUS",
                "apparatus_failure": str(exc),
                "raw": v1_1._score_summary(self.scores["raw_capability"], by_case),
                "frontier": {
                    level: v1_1._score_summary(self.scores[level], by_case)
                    for level in v1.LEVELS
                },
                "paired_vs_raw": "NOT_ASSESSED",
                "usage": self._usage(audit.records),
                "returned_model": audit.returned_model,
                "evidence_interpretation": "No representation claim is licensed.",
            }
            return self._finish(audit, preflight=preflight, result=result)

        raw_summary = v1_1._score_summary(self.scores["raw_capability"], by_case)
        frontier = {
            level: v1_1._score_summary(self.scores[level], by_case)
            for level in v1.LEVELS
        }
        comparisons = {
            level: paired_comparison(
                self.scores["raw_capability"],
                self.scores[level],
                baseline_condition="raw_capability",
                candidate_condition=level,
                case_order=case_order,
            )
            for level in v1.LEVELS
        }
        adjacent_comparisons = {
            "C0_vs_raw": comparisons["C0"],
            "C1_vs_C0": paired_comparison(
                self.scores["C0"],
                self.scores["C1"],
                baseline_condition="C0",
                candidate_condition="C1",
                case_order=case_order,
            ),
            "C2_vs_C1": paired_comparison(
                self.scores["C1"],
                self.scores["C2"],
                baseline_condition="C1",
                candidate_condition="C2",
                case_order=case_order,
            ),
        }
        representation_totals = {
            condition: sum(
                row[condition]
                for row in preflight["representation_utf8_bytes_by_case"].values()
            )
            for condition in ("raw", *v1.LEVELS)
        }
        result_code, primary = _primary_result(
            raw_summary=raw_summary,
            c0_summary=frontier[PRIMARY_COMPRESSED_CONDITION],
            c0_comparison=comparisons[PRIMARY_COMPRESSED_CONDITION],
            representation_totals=representation_totals,
            max_correct_across_conditions=max(
                raw_summary["exact_correct"],
                *(frontier[level]["exact_correct"] for level in v1.LEVELS),
            ),
        )
        result = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "validity": "VALID",
            "result_code": result_code,
            "raw": raw_summary,
            "frontier": frontier,
            "paired_vs_raw": comparisons,
            "paired_adjacent_frontier": adjacent_comparisons,
            "representation_utf8_bytes": representation_totals,
            "representation_ratios_to_raw": {
                level: representation_totals[level] / representation_totals["raw"]
                for level in v1.LEVELS
            },
            "primary_hypothesis": primary,
            "relative_frontier": _relative_frontier(
                adjacent_comparisons, representation_totals
            ),
            "usage": self._usage(audit.records),
            "returned_model": audit.returned_model,
        }
        return self._finish(audit, preflight=preflight, result=result)


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    verified = dict(v1.verify_run(run_dir))
    index = json.loads((run_dir / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    if index.get("protocol_id") != PROTOCOL_ID or result.get("protocol_id") != PROTOCOL_ID:
        raise v1.ApparatusFailure("evidence is not Protocol v1.2")
    if result.get("validity") == "VALID":
        if verified["physical_generation_calls"] != v1.MAX_GENERATION_CALLS:
            raise v1.ApparatusFailure("valid v1.2 run did not execute all 24 calls")
        paired = result.get("paired_vs_raw")
        if not isinstance(paired, Mapping) or set(paired) != set(v1.LEVELS):
            raise v1.ApparatusFailure("valid v1.2 paired comparisons are missing")
    verified["protocol_id"] = PROTOCOL_ID
    return verified


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acknowledge-frozen-luna-frontier-v1-2",
        action="store_true",
        help="required acknowledgement that this is the one frozen v1.2 run",
    )
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge_frozen_luna_frontier_v1_2:
        parser.error("--acknowledge-frozen-luna-frontier-v1-2 is required")
    v1._check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = MatchedBaselineRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
