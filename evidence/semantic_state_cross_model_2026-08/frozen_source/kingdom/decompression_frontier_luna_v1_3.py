"""Luna compression frontier v1.3 exact-replication protocol.

Protocol v1.3 leaves every v1.2 inference variable unchanged and repeats the
entire matched 24-call schedule six times.  Its only experimental change is
the preregistered repetition count needed to distinguish a recurring C0 loss
from a migrating, stochastic solver error.
"""

from __future__ import annotations

import argparse
import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hive_llm import ask_hive
from kingdom import decompression_frontier_luna as v1
from kingdom import decompression_frontier_luna_v1_2 as v1_2


PROTOCOL_ID = "hive-luna-compression-frontier-v1.3"
PROTOCOL_VERSION = "1.3"
SCHEMA_VERSION = v1_2.SCHEMA_VERSION
REPLICATION_COUNT = 6
CALLS_PER_REPLICATION = v1.MAX_GENERATION_CALLS
MAX_GENERATION_CALLS = REPLICATION_COUNT * CALLS_PER_REPLICATION
AUTHORIZED_COST_CEILING_USD = 1.75
RUN_DIR = Path(".hive/benchmarks/decompression_test/luna-frontier-v1-3-001")
FROZEN_V1_2_INFERENCE_SHA256 = (
    "e563686089680920898c8cdaaf07c98754b2bd2e67e85e6c82b45d4cd96d891e"
)
SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *v1_2.SOURCE_FILES,
            "kingdom/decompression_frontier_luna_v1_3.py",
            "benchmarks/decompression_test/PROTOCOL_LUNA_FRONTIER_V1_3.md",
            "tests/test_decompression_frontier_luna_v1_3.py",
        )
    )
)
_V1_2_PRIMARY_RESULT = v1_2._primary_result


def _replicate_primary_result(**kwargs):
    result_code, primary = _V1_2_PRIMARY_RESULT(**kwargs)
    rewritten = dict(primary)
    rewritten["benchmark_scope"] = (
        "one preregistered component of the six-replication Luna v1.3 study"
    )
    rewritten["replication_required"] = "governed_by_v1_3_aggregate"
    return result_code, rewritten


@contextmanager
def _v1_3_bindings():
    replacements = {
        "PROTOCOL_ID": PROTOCOL_ID,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "RUN_DIR": RUN_DIR,
        "SOURCE_FILES": SOURCE_FILES,
        "_primary_result": _replicate_primary_result,
    }
    originals = {name: getattr(v1_2, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v1_2, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(v1_2, name, value)


def _inference_fingerprint(preflight: Mapping[str, Any]) -> str:
    payload = {
        key: preflight[key]
        for key in (
            "case_pack_sha256",
            "expanded_pack_sha256",
            "solver_prompt_template_sha256",
            "solver_config",
            "solver_config_sha256",
            "levels",
            "slot_to_level",
            "frontier_position_counts",
            "call_plan",
            "representation_utf8_bytes_by_case",
            "raw_baseline",
            "all_conditions_run_unless_apparatus_failure",
            "cost",
        )
    }
    return v1._sha256_text(v1._canonical_json(payload))


def deterministic_preflight(repo_root: Path, *, require_committed: bool = True):
    with _v1_3_bindings():
        payload, cases, calls, child = v1_2.deterministic_preflight(
            repo_root, require_committed=require_committed
        )
    if len(calls) != CALLS_PER_REPLICATION:
        raise v1.ApparatusFailure("v1.3 child schedule is not exactly 24 calls")
    inference_fingerprint = _inference_fingerprint(child)
    if inference_fingerprint != FROZEN_V1_2_INFERENCE_SHA256:
        raise v1.ApparatusFailure("v1.2 inference fingerprint drifted")
    child_cost = float(child["cost"]["conservative_generation_cost_upper_bound_usd"])
    cost_upper = child_cost * REPLICATION_COUNT
    if cost_upper > AUTHORIZED_COST_CEILING_USD:
        raise v1.ApparatusFailure("replication cost exceeds frozen authorization")
    preflight = v1._sealed(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": child["source_revision"],
            "source_file_sha256": child["source_file_sha256"],
            "sole_material_change_from_v1_2": (
                "repeat the exact complete v1.2 schedule six independent times"
            ),
            "replication_count": REPLICATION_COUNT,
            "calls_per_replication": CALLS_PER_REPLICATION,
            "maximum_physical_generation_calls": MAX_GENERATION_CALLS,
            "child_preflight_sha256": child["payload_sha256"],
            "frozen_v1_2_inference_sha256": inference_fingerprint,
            "case_pack_sha256": child["case_pack_sha256"],
            "expanded_pack_sha256": child["expanded_pack_sha256"],
            "solver_prompt_template_sha256": child[
                "solver_prompt_template_sha256"
            ],
            "solver_config": child["solver_config"],
            "solver_config_sha256": child["solver_config_sha256"],
            "call_plan": child["call_plan"],
            "levels": child["levels"],
            "slot_to_level": child["slot_to_level"],
            "frontier_position_counts": child["frontier_position_counts"],
            "representation_utf8_bytes_by_case": child[
                "representation_utf8_bytes_by_case"
            ],
            "cost": {
                "child_conservative_generation_cost_upper_bound_usd": child_cost,
                "conservative_generation_cost_upper_bound_usd": cost_upper,
                "authorized_cost_ceiling_usd": AUTHORIZED_COST_CEILING_USD,
                "pricing_usd_per_million": child["cost"][
                    "pricing_usd_per_million"
                ],
            },
            "attempts_per_scheduled_call": 1,
            "retry": False,
            "repair": False,
            "interim_success_stop": False,
            "replacement_replications": False,
            "prior_v1_2_result_in_confirmatory_sample": False,
            "sequential_execution_required": True,
        }
    )
    return payload, cases, calls, preflight


def exact_two_sided_sign_test(deltas: Sequence[int]) -> Mapping[str, Any]:
    positive = sum(value > 0 for value in deltas)
    negative = sum(value < 0 for value in deltas)
    ties = len(deltas) - positive - negative
    nonzero = positive + negative
    if nonzero == 0:
        p_value = 1.0
        direction = "tie"
    else:
        tail = min(positive, negative)
        tail_probability = sum(
            math.comb(nonzero, index) for index in range(tail + 1)
        ) / (2**nonzero)
        p_value = min(1.0, 2.0 * tail_probability)
        direction = (
            "positive" if positive > negative else "negative" if negative > positive else "tie"
        )
    return {
        "test": "exact_two_sided_sign_test",
        "replication_unit": "complete_20_case_run",
        "nonzero_differences": nonzero,
        "positive_differences": positive,
        "negative_differences": negative,
        "ties": ties,
        "direction": direction,
        "p_value": p_value,
        "alpha": 0.05,
    }


def _condition_payload(result: Mapping[str, Any], condition: str) -> Mapping[str, Any]:
    return result["raw"] if condition == "raw" else result["frontier"][condition]


def _condition_stability(results: Sequence[Mapping[str, Any]], condition: str):
    summaries = [_condition_payload(result, condition) for result in results]
    exact_by_run = [int(summary["exact_correct"]) for summary in summaries]
    admissible_by_run = [int(summary["admissible"]) for summary in summaries]
    chronology_by_run = [
        int(summary["chronology_authority_errors"]) for summary in summaries
    ]
    promotions_by_run = [
        int(summary["illegal_state_promotions"]) for summary in summaries
    ]
    return {
        "total_trials": sum(int(summary["total"]) for summary in summaries),
        "admissible": sum(admissible_by_run),
        "exact_correct": sum(exact_by_run),
        "chronology_authority_errors": sum(chronology_by_run),
        "illegal_state_promotions": sum(promotions_by_run),
        "insufficient_responses": sum(
            int(summary["insufficient_responses"]) for summary in summaries
        ),
        "solver_budget_exhaustions": sum(
            int(summary.get("solver_budget_exhaustions", 0)) for summary in summaries
        ),
        "exact_correct_by_replication": exact_by_run,
        "exact_correct_mean": sum(exact_by_run) / len(exact_by_run),
        "exact_correct_min": min(exact_by_run),
        "exact_correct_max": max(exact_by_run),
        "perfect_replications": sum(value == 20 for value in exact_by_run),
        "admissible_by_replication": admissible_by_run,
        "chronology_authority_errors_by_replication": chronology_by_run,
        "illegal_state_promotions_by_replication": promotions_by_run,
    }


def _case_stability(results: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    first_scores = _condition_payload(results[0], "raw")["scores"]
    case_order = [str(score["case_id"]) for score in first_scores]
    rows = []
    for case_id in case_order:
        condition_rows: dict[str, Any] = {}
        for condition in ("raw", *v1.LEVELS):
            selected = []
            for result in results:
                scores = _condition_payload(result, condition)["scores"]
                matches = [score for score in scores if score["case_id"] == case_id]
                if len(matches) != 1:
                    raise v1.ApparatusFailure(
                        f"{condition}/{case_id} is not unique in a replication"
                    )
                selected.append(matches[0])
            label_counts: dict[str, int] = {}
            for score in selected:
                label = score.get("selected_label")
                key = label if isinstance(label, str) else "NO_LABEL"
                label_counts[key] = label_counts.get(key, 0) + 1
            condition_rows[condition] = {
                "exact_correct": sum(score["answer_correct"] is True for score in selected),
                "admissible": sum(score["admissible"] is True for score in selected),
                "chronology_authority_errors": sum(
                    score["chronology_authority_error"] is True for score in selected
                ),
                "illegal_state_promotions": sum(
                    int(score.get("illegal_state_promotions") or 0) for score in selected
                ),
                "selected_label_counts": dict(sorted(label_counts.items())),
            }
        outcomes = {name: 0 for name in (
            "both_correct",
            "baseline_only_correct",
            "candidate_only_correct",
            "both_wrong",
        )}
        for result in results:
            pairs = result["paired_vs_raw"]["C0"]["cases"]
            match = [row for row in pairs if row["case_id"] == case_id]
            if len(match) != 1:
                raise v1.ApparatusFailure(f"C0/Raw pair for {case_id} is not unique")
            outcomes[str(match[0]["outcome"])] += 1
        rows.append(
            {
                "case_id": case_id,
                "conditions": condition_rows,
                "C0_vs_Raw_outcomes": outcomes,
            }
        )
    return rows


def _pooled_comparison(
    results: Sequence[Mapping[str, Any]], comparison_path: Sequence[str]
) -> Mapping[str, Any]:
    comparisons = []
    for result in results:
        current: Any = result
        for key in comparison_path:
            current = current[key]
        comparisons.append(current)
    count_fields = (
        "both_correct",
        "baseline_only_correct",
        "candidate_only_correct",
        "both_wrong",
    )
    return {
        "baseline_condition": comparisons[0]["baseline_condition"],
        "candidate_condition": comparisons[0]["candidate_condition"],
        "total_matched_trials": sum(
            int(item["total_matched_cases"]) for item in comparisons
        ),
        **{
            name: sum(int(item[name]) for item in comparisons)
            for name in count_fields
        },
        "exact_correct_delta_candidate_minus_baseline_by_replication": [
            int(item["exact_correct_delta_candidate_minus_baseline"])
            for item in comparisons
        ],
        "chronology_authority_error_delta_candidate_minus_baseline_by_replication": [
            int(item["chronology_authority_error_delta_candidate_minus_baseline"])
            for item in comparisons
        ],
        "illegal_state_promotion_delta_candidate_minus_baseline_by_replication": [
            int(item["illegal_state_promotion_delta_candidate_minus_baseline"])
            for item in comparisons
        ],
        "quality_not_worse_replications": sum(
            item["quality_not_worse_than_baseline"] is True for item in comparisons
        ),
        "per_case_zero_distortion_replications": sum(
            item["per_case_zero_distortion"] is True for item in comparisons
        ),
    }


def _classify_stability(
    c0_comparisons: Sequence[Mapping[str, Any]],
    *,
    low_capability_replications: int = 0,
) -> Mapping[str, Any]:
    quality_passes = sum(
        item["quality_not_worse_than_baseline"] is True for item in c0_comparisons
    )
    zero_distortion_passes = sum(
        item["per_case_zero_distortion"] is True for item in c0_comparisons
    )
    correctness = exact_two_sided_sign_test(
        [
            int(item["exact_correct_delta_candidate_minus_baseline"])
            for item in c0_comparisons
        ]
    )
    chronology = exact_two_sided_sign_test(
        [
            int(item["chronology_authority_error_delta_candidate_minus_baseline"])
            for item in c0_comparisons
        ]
    )
    promotions = exact_two_sided_sign_test(
        [
            int(item["illegal_state_promotion_delta_candidate_minus_baseline"])
            for item in c0_comparisons
        ]
    )
    systematic_correctness_loss = (
        correctness["p_value"] < correctness["alpha"]
        and correctness["direction"] == "negative"
    )
    chronology_deltas = [
        int(item["chronology_authority_error_delta_candidate_minus_baseline"])
        for item in c0_comparisons
    ]
    promotion_deltas = [
        int(item["illegal_state_promotion_delta_candidate_minus_baseline"])
        for item in c0_comparisons
    ]
    observed_chronology_loss_all_six = all(value > 0 for value in chronology_deltas)
    observed_promotion_loss_all_six = all(value > 0 for value in promotion_deltas)
    if low_capability_replications:
        result_code = "VALID_INCONCLUSIVE_LOW_SOLVER_CAPABILITY"
        evidence_label = "INCONCLUSIVE"
        stability = "NOT_ASSESSED_LOW_SOLVER_CAPABILITY"
    elif systematic_correctness_loss:
        result_code = "VALID_SYSTEMATIC_C0_CORRECTNESS_REGRESSION"
        evidence_label = "NOT_SUPPORTED"
        stability = "SYSTEMATIC_CORRECTNESS_REGRESSION"
    elif quality_passes == REPLICATION_COUNT:
        if zero_distortion_passes == REPLICATION_COUNT:
            result_code = "VALID_OBSERVED_C0_ZERO_DISTORTION_ALL_SIX"
        else:
            result_code = "VALID_OBSERVED_C0_NO_REGRESSION_ALL_SIX"
        evidence_label = "SUPPORTED"
        stability = "OBSERVED_NO_REGRESSION_ALL_SIX"
    elif observed_chronology_loss_all_six or observed_promotion_loss_all_six:
        result_code = "VALID_OBSERVED_C0_SAFETY_REGRESSION_ALL_SIX"
        evidence_label = "NOT_SUPPORTED"
        stability = "OBSERVED_SAFETY_REGRESSION_ALL_SIX"
    else:
        result_code = "VALID_MIXED_C0_STABILITY"
        evidence_label = "INCONCLUSIVE_MIXED"
        stability = "CONSISTENT_WITH_STOCHASTIC_VARIATION_NOT_PROVEN"
    return {
        "result_code": result_code,
        "evidence_label": evidence_label,
        "stability_class": stability,
        "quality_not_worse_replications": quality_passes,
        "per_case_zero_distortion_replications": zero_distortion_passes,
        "correctness_sign_test": correctness,
        "chronology_error_sign_test": chronology,
        "illegal_promotion_sign_test": promotions,
        "systematic_correctness_loss": systematic_correctness_loss,
        "chronology_and_promotion_sign_tests_inferential_role": (
            "descriptive_only_not_used_for_unadjusted_multiple_testing"
        ),
        "observed_chronology_loss_all_six": observed_chronology_loss_all_six,
        "observed_promotion_loss_all_six": observed_promotion_loss_all_six,
        "low_solver_capability_replications": low_capability_replications,
        "absence_of_significance_proves_equivalence": False,
        "statistical_equivalence_established": False,
    }


def _aggregate_usage(results: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    condition_fields = (
        "call_artifacts",
        "physical_generation_calls",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "latency_seconds",
    )
    conditions = ("raw_capability", *v1.LEVELS)
    by_condition: dict[str, Any] = {}
    for condition in conditions:
        by_condition[condition] = {
            field: sum(
                result["usage"]["by_condition"][condition][field]
                for result in results
            )
            for field in condition_fields
        }
    total = {
        field: sum(result["usage"]["total"][field] for result in results)
        for field in condition_fields
    }
    total["estimated_generation_cost_usd"] = sum(
        result["usage"]["total"]["estimated_generation_cost_usd"]
        for result in results
    )
    return {"by_condition": by_condition, "total": total}


def aggregate_results(
    results: Sequence[Mapping[str, Any]], *, source_revision: str
) -> Mapping[str, Any]:
    if len(results) != REPLICATION_COUNT:
        raise v1.ApparatusFailure("aggregate does not contain six replications")
    if any(
        result.get("validity") != "VALID"
        or result.get("protocol_id") != PROTOCOL_ID
        for result in results
    ):
        raise v1.ApparatusFailure("aggregate contains an invalid or foreign child")
    returned_models = {result.get("returned_model") for result in results}
    if (
        len(returned_models) != 1
        or not isinstance(next(iter(returned_models)), str)
        or not next(iter(returned_models))
    ):
        raise v1.ApparatusFailure("returned model drifted across replications")
    representations = [result["representation_utf8_bytes"] for result in results]
    if any(item != representations[0] for item in representations[1:]):
        raise v1.ApparatusFailure("representation byte totals drifted across replications")
    low_capability_replications = []
    for index, result in enumerate(results, start=1):
        maximum = max(
            int(result["raw"]["exact_correct"]),
            *(int(result["frontier"][level]["exact_correct"]) for level in v1.LEVELS),
        )
        is_low_capability = maximum <= v1_2.LOW_CAPABILITY_MAX_CORRECT
        reported_low_capability = (
            result["result_code"] == "VALID_INCONCLUSIVE_LOW_SOLVER_CAPABILITY"
        )
        if is_low_capability != reported_low_capability:
            raise v1.ApparatusFailure(
                f"replication {index} low-capability classification drifted"
            )
        if is_low_capability:
            low_capability_replications.append(index)
    c0_comparisons = [result["paired_vs_raw"]["C0"] for result in results]
    stability = _classify_stability(
        c0_comparisons,
        low_capability_replications=len(low_capability_replications),
    )
    case_stability = _case_stability(results)
    recurring_raw_only = [
        row["case_id"]
        for row in case_stability
        if row["C0_vs_Raw_outcomes"]["baseline_only_correct"]
        == REPLICATION_COUNT
    ]
    replicate_summaries = []
    for index, result in enumerate(results, start=1):
        comparison = result["paired_vs_raw"]["C0"]
        replicate_summaries.append(
            {
                "replication": index,
                "result_code": result["result_code"],
                "Raw_exact_correct": result["raw"]["exact_correct"],
                **{
                    f"{level}_exact_correct": result["frontier"][level][
                        "exact_correct"
                    ]
                    for level in v1.LEVELS
                },
                "C0_minus_Raw_exact_correct": comparison[
                    "exact_correct_delta_candidate_minus_baseline"
                ],
                "C0_quality_not_worse": comparison[
                    "quality_not_worse_than_baseline"
                ],
                "C0_per_case_zero_distortion": comparison[
                    "per_case_zero_distortion"
                ],
                "C0_Raw_only_case_ids": comparison[
                    "baseline_only_correct_case_ids"
                ],
                "C0_only_case_ids": comparison[
                    "candidate_only_correct_case_ids"
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "source_revision": source_revision,
        "validity": "VALID",
        "result_code": stability["result_code"],
        "replication_count": REPLICATION_COUNT,
        "physical_call_budget": MAX_GENERATION_CALLS,
        "replicate_summaries": replicate_summaries,
        "conditions": {
            condition: _condition_stability(results, condition)
            for condition in ("raw", *v1.LEVELS)
        },
        "pooled_paired_comparisons": {
            "C0_vs_Raw": _pooled_comparison(
                results, ("paired_vs_raw", "C0")
            ),
            "C1_vs_C0": _pooled_comparison(
                results, ("paired_adjacent_frontier", "C1_vs_C0")
            ),
            "C2_vs_C1": _pooled_comparison(
                results, ("paired_adjacent_frontier", "C2_vs_C1")
            ),
        },
        "C0_replication_inference": {
            **stability,
            "low_solver_capability_replication_ids": low_capability_replications,
            "same_Raw_only_case_in_all_six_replications": recurring_raw_only,
            "existing_v1_2_run_included": False,
            "pooled_case_trials_used_as_independent_for_sign_test": False,
            "claim_scope": (
                "C0 versus Raw on six fresh exact replications of the frozen "
                "20-case Luna benchmark"
            ),
            "broad_hive_claim": "NOT_PROVEN",
        },
        "case_stability": case_stability,
        "representation_utf8_bytes": representations[0],
        "representation_ratios_to_raw": results[0][
            "representation_ratios_to_raw"
        ],
        "usage": _aggregate_usage(results),
        "returned_models": sorted(returned_models),
    }


def _write_root_index(output_dir: Path, *, source_revision: str) -> None:
    index_path = output_dir / "EVIDENCE_INDEX.json"
    rows = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        if path == index_path:
            continue
        rows.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": v1._sha256_bytes(path.read_bytes()),
            }
        )
    index = v1._sealed(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "source_revision": source_revision,
            "file_count": len(rows),
            "total_bytes": sum(row["bytes"] for row in rows),
            "files": rows,
        }
    )
    v1._write_exclusive(index_path, v1._pretty_json(index))


def _finish_root(
    output_dir: Path, *, preflight: Mapping[str, Any], result: Mapping[str, Any]
) -> Mapping[str, Any]:
    v1._write_exclusive(
        output_dir / "RESULT.json", v1._pretty_json(v1._sealed(result))
    )
    v1._write_exclusive(
        output_dir / "RUN_STATUS.json",
        v1._pretty_json(
            v1._sealed(
                {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "finished_at_utc": v1._utc_now(),
                    "validity": result["validity"],
                    "result_code": result["result_code"],
                    "physical_generation_calls": result["usage"]["total"][
                        "physical_generation_calls"
                    ],
                }
            )
        ),
    )
    _write_root_index(
        output_dir, source_revision=str(preflight["source_revision"])
    )
    return result


def _assert_current_child_binding(
    repo_root: Path,
    *,
    root_preflight: Mapping[str, Any],
    require_committed: bool,
) -> None:
    with _v1_3_bindings():
        _, _, _, current = v1_2.deterministic_preflight(
            repo_root, require_committed=require_committed
        )
    if current["payload_sha256"] != root_preflight["child_preflight_sha256"]:
        raise v1.ApparatusFailure("child preflight drifted from the frozen root")
    if current["source_revision"] != root_preflight["source_revision"]:
        raise v1.ApparatusFailure("source revision drifted between replications")


def _assert_child_artifact_binding(
    child_dir: Path, *, root_preflight: Mapping[str, Any]
) -> None:
    child = json.loads((child_dir / "PRECHECK.json").read_text(encoding="utf-8"))
    v1._verify_seal(child)
    if child["payload_sha256"] != root_preflight["child_preflight_sha256"]:
        raise v1.ApparatusFailure("child artifact preflight differs from the root")
    if child["source_revision"] != root_preflight["source_revision"]:
        raise v1.ApparatusFailure("child artifact source revision differs from the root")


class ReplicationRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        output_dir: Path,
        ask_fn: Callable[..., str] = ask_hive,
        require_committed: bool = True,
    ) -> None:
        self.repo_root = repo_root
        self.output_dir = output_dir
        self.ask_fn = ask_fn
        self.require_committed = require_committed

    def _invalid(
        self,
        *,
        preflight: Mapping[str, Any],
        results: Sequence[Mapping[str, Any]],
        failed_replication: int,
        reason: str,
    ) -> Mapping[str, Any]:
        invalid = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": preflight["source_revision"],
            "validity": "INVALID",
            "result_code": "INVALID_REPLICATION_APPARATUS",
            "failed_replication": failed_replication,
            "replications_started": len(results),
            "replications_completed": sum(
                result["validity"] == "VALID" for result in results
            ),
            "child_result_codes": [result["result_code"] for result in results],
            "apparatus_failure": reason,
            "usage": _aggregate_usage(results),
            "evidence_interpretation": (
                "No replication or representation claim is licensed."
            ),
        }
        return _finish_root(self.output_dir, preflight=preflight, result=invalid)

    def run(self) -> Mapping[str, Any]:
        expected_live_dir = (self.repo_root / RUN_DIR).resolve()
        if self.require_committed and self.output_dir.resolve() != expected_live_dir:
            raise v1.ApparatusFailure(
                "live v1.3 execution is locked to the preregistered run directory"
            )
        if self.output_dir.exists():
            raise v1.ApparatusFailure(
                "v1.3 run directory already exists; no inference was started"
            )
        _, _, _, preflight = deterministic_preflight(
            self.repo_root, require_committed=self.require_committed
        )
        v1._write_exclusive(
            self.output_dir / "PRECHECK.json", v1._pretty_json(preflight)
        )
        v1._write_exclusive(
            self.output_dir / "PROTOCOL_REPLICATION.json",
            v1._pretty_json(
                v1._sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "protocol_version": PROTOCOL_VERSION,
                        "sole_material_change_from_v1_2": (
                            "six fresh exact complete replications"
                        ),
                        "replication_count_fixed_before_inference": REPLICATION_COUNT,
                        "prior_v1_2_result_excluded": True,
                        "no_interim_stop": True,
                        "no_replacement_run": True,
                        "sequential_execution": True,
                        "prompt_model_representation_order_settings_changed": False,
                    }
                )
            ),
        )
        v1._write_exclusive(
            self.output_dir / "MANIFEST.json",
            v1._pretty_json(
                v1._sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "protocol_version": PROTOCOL_VERSION,
                        "created_at_utc": v1._utc_now(),
                        "source_revision": preflight["source_revision"],
                        "precheck_sha256": preflight["payload_sha256"],
                        "replication_count": REPLICATION_COUNT,
                        "calls_per_replication": CALLS_PER_REPLICATION,
                        "maximum_physical_generation_calls": MAX_GENERATION_CALLS,
                        "attempts_per_call": 1,
                        "no_retry": True,
                        "no_repair": True,
                    }
                )
            ),
        )
        results = []
        returned_model = None
        for index in range(1, REPLICATION_COUNT + 1):
            child_dir = self.output_dir / f"replicate-{index:03d}"
            try:
                _assert_current_child_binding(
                    self.repo_root,
                    root_preflight=preflight,
                    require_committed=self.require_committed,
                )
            except BaseException as exc:
                return self._invalid(
                    preflight=preflight,
                    results=results,
                    failed_replication=index,
                    reason=str(exc),
                )
            with _v1_3_bindings():
                child = v1_2.MatchedBaselineRunner(
                    repo_root=self.repo_root,
                    output_dir=child_dir,
                    ask_fn=self.ask_fn,
                    require_committed=self.require_committed,
                ).run()
            results.append(child)
            if child["validity"] != "VALID":
                return self._invalid(
                    preflight=preflight,
                    results=results,
                    failed_replication=index,
                    reason=str(child.get("apparatus_failure", "child apparatus failure")),
                )
            try:
                _assert_child_artifact_binding(
                    child_dir, root_preflight=preflight
                )
                _assert_current_child_binding(
                    self.repo_root,
                    root_preflight=preflight,
                    require_committed=self.require_committed,
                )
                child_model = child.get("returned_model")
                if not isinstance(child_model, str) or not child_model:
                    raise v1.ApparatusFailure("child returned model is missing")
                if returned_model is None:
                    returned_model = child_model
                elif child_model != returned_model:
                    raise v1.ApparatusFailure(
                        "returned model drifted between replications"
                    )
            except BaseException as exc:
                return self._invalid(
                    preflight=preflight,
                    results=results,
                    failed_replication=index,
                    reason=str(exc),
                )
        aggregate = aggregate_results(
            results, source_revision=str(preflight["source_revision"])
        )
        return _finish_root(
            self.output_dir, preflight=preflight, result=aggregate
        )


def _verify_root_index(run_dir: Path) -> Mapping[str, Any]:
    index_path = run_dir / "EVIDENCE_INDEX.json"
    if not index_path.is_file():
        raise v1.ApparatusFailure("root EVIDENCE_INDEX.json is missing")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    v1._verify_seal(index)
    expected = {row["path"] for row in index["files"]}
    actual = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path != index_path
    }
    if expected != actual:
        raise v1.ApparatusFailure("root evidence file set differs from sealed index")
    for row in index["files"]:
        path = run_dir / row["path"]
        if (
            path.stat().st_size != row["bytes"]
            or v1._sha256_bytes(path.read_bytes()) != row["sha256"]
        ):
            raise v1.ApparatusFailure(f"root evidence changed: {row['path']}")
        if path.suffix == ".json":
            v1._verify_seal(json.loads(path.read_text(encoding="utf-8")))
    return index


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    index = _verify_root_index(run_dir)
    preflight = json.loads((run_dir / "PRECHECK.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    if result.get("protocol_id") != PROTOCOL_ID:
        raise v1.ApparatusFailure("root result is not Protocol v1.3")
    if (
        preflight.get("source_revision") != index.get("source_revision")
        or preflight.get("frozen_v1_2_inference_sha256")
        != FROZEN_V1_2_INFERENCE_SHA256
    ):
        raise v1.ApparatusFailure("root preflight binding is inconsistent")
    child_dirs = sorted(path for path in run_dir.glob("replicate-*") if path.is_dir())
    child_results = []
    child_verifications = []
    response_ids = []
    returned_models = set()
    with _v1_3_bindings():
        for child_dir in child_dirs:
            child_verifications.append(v1_2.verify_run(child_dir))
            _assert_child_artifact_binding(
                child_dir, root_preflight=preflight
            )
            child_results.append(
                json.loads((child_dir / "RESULT.json").read_text(encoding="utf-8"))
            )
            for call_path in sorted((child_dir / "calls").glob("call_*.json")):
                call = json.loads(call_path.read_text(encoding="utf-8"))
                metadata = call.get("transport_metadata", {})
                if metadata.get("physical_attempts") != 1:
                    raise v1.ApparatusFailure("a scheduled call did not use one attempt")
                response_id = metadata.get("response_id")
                if isinstance(response_id, str) and response_id:
                    response_ids.append(response_id)
                returned_model = metadata.get("returned_model")
                if isinstance(returned_model, str) and returned_model:
                    returned_models.add(returned_model)
    physical_calls = sum(
        int(child["physical_generation_calls"]) for child in child_verifications
    )
    if result["validity"] == "VALID":
        if len(child_dirs) != REPLICATION_COUNT or physical_calls != MAX_GENERATION_CALLS:
            raise v1.ApparatusFailure("valid v1.3 evidence is not six complete runs")
        if len(response_ids) != MAX_GENERATION_CALLS or len(set(response_ids)) != len(
            response_ids
        ):
            raise v1.ApparatusFailure("response IDs are missing or reused")
        if len(returned_models) != 1:
            raise v1.ApparatusFailure("returned model drifted across replications")
        expected = aggregate_results(
            child_results, source_revision=str(index["source_revision"])
        )
        observed = dict(result)
        observed.pop("payload_sha256", None)
        if observed != expected:
            raise v1.ApparatusFailure("root aggregate does not match child evidence")
    elif len(child_dirs) != int(result["replications_started"]):
        raise v1.ApparatusFailure("invalid root child count is inconsistent")
    return {
        "verified": True,
        "protocol_id": PROTOCOL_ID,
        "validity": result["validity"],
        "result_code": result["result_code"],
        "file_count": index["file_count"],
        "total_bytes": index["total_bytes"],
        "replications": len(child_dirs),
        "physical_generation_calls": physical_calls,
        "unique_response_ids": len(set(response_ids)),
        "returned_models": sorted(returned_models),
        "source_revision": index["source_revision"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acknowledge-frozen-luna-frontier-v1-3",
        action="store_true",
        help="required acknowledgement for the one six-replication v1.3 run",
    )
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge_frozen_luna_frontier_v1_3:
        parser.error("--acknowledge-frozen-luna-frontier-v1-3 is required")
    v1._check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = ReplicationRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
