"""Frozen 2x2: Luna/Sol crossed with Raw/Hive-C1 representation.

This experiment isolates representation effects within each solver and tests
whether the relative C1 effect differs between solvers.  The benchmark,
prompts, graders, solver settings, and one-attempt contract remain frozen.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from hive_llm import FrozenSolverConfig, ask_hive
from kingdom import decompression_frontier_luna as frontier
from kingdom import decompression_luna_hive_vs_sol_raw as pair
from kingdom import decompression_semantic_authority_luna as study2
from kingdom import decompression_semantic_authority_luna_v1_2 as audit_helpers
from kingdom import decompression_test as worlds
from kingdom import decompression_test_v2 as grading


PROTOCOL_ID = "hive-luna-sol-raw-c1-factorial-v1"
PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = 1
RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/luna-sol-raw-c1-factorial-v1-001"
)
ACKNOWLEDGEMENT = "--acknowledge-frozen-luna-sol-raw-c1-factorial-v1"

SEALED_PARENT = "81dc05d320c7989d2ad9b169a9ef39623ccb8b3b"
SEALED_PAIR_SOURCE = "e9da495ec67e7f0841014c2aa0648458fad013fa"
SEALED_PAIR_RESULT_SHA256 = (
    "de076ec96ef8b1c87966d6607215ec18ae6ca5cf5af4d6f4187fc9448d1064d1"
)
SEALED_PAIR_INDEX_SHA256 = (
    "f0a1395b4a1608387cce0587478eceb428408887f8178c3a288e65dda6a6c41d"
)

LUNA_RAW = "LUNA_RAW"
LUNA_C1 = "LUNA_C1"
SOL_RAW = "SOL_RAW"
SOL_C1 = "SOL_C1"
CONDITIONS = (LUNA_RAW, LUNA_C1, SOL_RAW, SOL_C1)
MODELS = {
    LUNA_RAW: "gpt-5.6-luna",
    LUNA_C1: "gpt-5.6-luna",
    SOL_RAW: "gpt-5.6-sol",
    SOL_C1: "gpt-5.6-sol",
}
REPRESENTATIONS = {
    LUNA_RAW: "raw_capability",
    LUNA_C1: "C1",
    SOL_RAW: "raw_capability",
    SOL_C1: "C1",
}
MODEL_FACTOR = {
    LUNA_RAW: "LUNA",
    LUNA_C1: "LUNA",
    SOL_RAW: "SOL",
    SOL_C1: "SOL",
}
REPRESENTATION_FACTOR = {
    LUNA_RAW: "RAW",
    LUNA_C1: "C1",
    SOL_RAW: "RAW",
    SOL_C1: "C1",
}
MODEL_PRICING_USD_PER_MILLION = {
    "LUNA": {"input": 0.20, "output": 1.20},
    "SOL": {"input": 4.00, "output": 20.00},
}
PRICING_USD_PER_MILLION = {
    condition: MODEL_PRICING_USD_PER_MILLION[MODEL_FACTOR[condition]]
    for condition in CONDITIONS
}

REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 16_384
TIMEOUT_SECONDS = 900
AUTHORIZED_COST_CEILING_USD = 55.0
REPLICATION_COUNT = 8
BATCHES_PER_CONDITION = 6
CASES_PER_CONDITION = 20
CALLS_PER_CONDITION = REPLICATION_COUNT * BATCHES_PER_CONDITION
MAX_GENERATION_CALLS = len(CONDITIONS) * CALLS_PER_CONDITION
TRIALS_PER_CONDITION = REPLICATION_COUNT * CASES_PER_CONDITION
RAW_CAPABILITY_WARNING_THRESHOLD = 144  # 90% of 160 fixed answers

MODULE_PATH = "kingdom/decompression_luna_sol_raw_c1_factorial.py"
TEST_PATH = "tests/test_decompression_luna_sol_raw_c1_factorial.py"
PROTOCOL_PATH = (
    "benchmarks/decompression_test/PROTOCOL_LUNA_SOL_RAW_C1_FACTORIAL_V1.md"
)
SOURCE_FILES = tuple(
    dict.fromkeys((*pair.SOURCE_FILES, MODULE_PATH, TEST_PATH, PROTOCOL_PATH))
)

# Filled from deterministic derivation before the implementation commit.
FROZEN_SCHEDULE_SHA256 = (
    "602971f9978975546ba35c90d3b2b43ac47e4ce0ddf884093c68587f80d31547"
)
FROZEN_REQUEST_PLAN_SHA256 = (
    "697f0f74d62364101401f3ed2e4e7b6f458c1bb2c6ff82449eb3cdc034b447bb"
)
FROZEN_SOLVER_CONFIG_SHA256 = {
    LUNA_RAW: "0fa9c5f438388516fd4ac130c44320f08cafb7bddbad6e102444326c56a04b54",
    LUNA_C1: "0fa9c5f438388516fd4ac130c44320f08cafb7bddbad6e102444326c56a04b54",
    SOL_RAW: "04b279997f7f4789a57c4c399622eccefe8f4dbfdf368bec404f1c7bba8f2422",
    SOL_C1: "04b279997f7f4789a57c4c399622eccefe8f4dbfdf368bec404f1c7bba8f2422",
}
FROZEN_INPUT_TOKEN_UPPER_BOUND = {
    LUNA_RAW: 2_796_272,
    LUNA_C1: 1_362_736,
    SOL_RAW: 2_796_224,
    SOL_C1: 1_362_688,
}
FROZEN_COST_UPPER_BOUND_USD = 50.8121664

WILLIAMS_ORDERS = (
    (LUNA_RAW, LUNA_C1, SOL_C1, SOL_RAW),
    (LUNA_C1, SOL_RAW, LUNA_RAW, SOL_C1),
    (SOL_RAW, SOL_C1, LUNA_C1, LUNA_RAW),
    (SOL_C1, LUNA_RAW, SOL_RAW, LUNA_C1),
)

ApparatusFailure = pair.ApparatusFailure
PlannedCall = pair.PlannedCall
_canonical_json = pair._canonical_json
_pretty_json = pair._pretty_json
_sha256_bytes = pair._sha256_bytes
_sha256_text = pair._sha256_text
_sealed = pair._sealed
_verify_seal = pair._verify_seal
_git = pair._git
render_progress = pair.render_progress
_input_payload_text = pair._input_payload_text
_prior_prompt_map = pair._prior_prompt_map
_load_frozen_cases = pair._load_frozen_cases


def solver_config(condition: str) -> FrozenSolverConfig:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}")
    return FrozenSolverConfig(
        model=MODELS[condition],
        reasoning_effort=REASONING_EFFORT,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        timeout_seconds=TIMEOUT_SECONDS,
        max_attempts=1,
        tool_permissions=(),
        store=False,
        truncation="disabled",
        reasoning_context="current_turn",
        service_tier="default",
        prompt_cache_mode="explicit",
    )


def build_solver_prompt(
    cases: Sequence[worlds.BenchmarkCase], condition: str
) -> str:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}")
    inherited = frontier.build_solver_prompt(cases, REPRESENTATIONS[condition])
    if not inherited.startswith(frontier.SOLVER_PROMPT_PREFIX):
        raise ApparatusFailure("inherited solver prompt prefix changed")
    return pair.NEUTRAL_SOLVER_PROMPT_PREFIX + inherited[len(frontier.SOLVER_PROMPT_PREFIX) :]


def condition_schedule() -> tuple[tuple[tuple[str, ...], ...], ...]:
    """Eight replications with a Williams order over all 48 batch blocks."""

    rows = []
    for replication_index in range(REPLICATION_COUNT):
        row = []
        for batch_index in range(BATCHES_PER_CONDITION):
            flattened = replication_index * BATCHES_PER_CONDITION + batch_index
            row.append(WILLIAMS_ORDERS[flattened % len(WILLIAMS_ORDERS)])
        rows.append(tuple(row))
    return tuple(rows)


def build_call_plan(
    payload: Mapping[str, Any], cases: Sequence[worlds.BenchmarkCase]
) -> tuple[PlannedCall, ...]:
    if len(payload.get("batches", ())) != BATCHES_PER_CONDITION:
        raise ApparatusFailure("frozen benchmark does not contain exactly six batches")
    by_case = {case.case_id: case for case in cases}
    local_sequences = {condition: 0 for condition in CONDITIONS}
    calls: list[PlannedCall] = []
    global_sequence = 1
    for replication, replication_orders in enumerate(condition_schedule(), start=1):
        for batch, order in zip(payload["batches"], replication_orders):
            batch_cases = tuple(by_case[str(case_id)] for case_id in batch["case_ids"])
            for position, condition in enumerate(order, start=1):
                local_sequences[condition] += 1
                calls.append(
                    PlannedCall(
                        global_sequence=global_sequence,
                        local_sequence=local_sequences[condition],
                        replication=replication,
                        condition_position=position,
                        batch_id=int(batch["batch_id"]),
                        condition=condition,
                        case_ids=tuple(case.case_id for case in batch_cases),
                        prompt=build_solver_prompt(batch_cases, condition),
                        text_format=frontier.openai_text_format(len(batch_cases)),
                    )
                )
                global_sequence += 1
    if len(calls) != MAX_GENERATION_CALLS:
        raise ApparatusFailure("call plan does not contain exactly 192 calls")
    return tuple(calls)


def _request_payload(call: PlannedCall) -> Mapping[str, Any]:
    config = solver_config(call.condition)
    return {
        "model": config.model,
        "input": call.prompt,
        "reasoning": {
            "effort": config.reasoning_effort,
            "context": config.reasoning_context,
        },
        "max_output_tokens": config.max_output_tokens,
        "tools": [],
        "store": False,
        "truncation": "disabled",
        "service_tier": "default",
        "prompt_cache_options": {"mode": "explicit"},
        "text": {"format": call.text_format},
    }


def verify_sealed_parent(repo_root: Path) -> Mapping[str, Any]:
    resolved = _git(repo_root, "rev-parse", f"{SEALED_PARENT}^{{commit}}").stdout.strip()
    if resolved != SEALED_PARENT:
        raise ApparatusFailure("sealed two-arm evidence parent did not resolve exactly")
    current = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if _git(
        repo_root, "merge-base", "--is-ancestor", SEALED_PARENT, current, check=False
    ).returncode != 0:
        raise ApparatusFailure("current source does not descend from sealed two-arm evidence")
    result_path = repo_root / pair.RUN_DIR / "RESULT.json"
    index_path = repo_root / pair.RUN_DIR / "EVIDENCE_INDEX.json"
    if (
        _sha256_bytes(result_path.read_bytes()) != SEALED_PAIR_RESULT_SHA256
        or _sha256_bytes(index_path.read_bytes()) != SEALED_PAIR_INDEX_SHA256
    ):
        raise ApparatusFailure("sealed two-arm evidence hashes changed")
    verified = pair.verify_run(repo_root / pair.RUN_DIR)
    if (
        verified["validity"] != "VALID"
        or verified["physical_generation_calls"] != 72
        or verified["unique_response_ids"] != 72
        or verified["source_revision"] != SEALED_PAIR_SOURCE
        or verified["returned_models"]
        != {pair.LUNA_C1: ["gpt-5.6-luna"], pair.SOL_RAW: ["gpt-5.6-sol"]}
    ):
        raise ApparatusFailure("sealed two-arm evidence no longer verifies")
    return {
        "sealed_parent": SEALED_PARENT,
        "current_revision": current,
        "pair_result_sha256": SEALED_PAIR_RESULT_SHA256,
        "pair_evidence_index_sha256": SEALED_PAIR_INDEX_SHA256,
        "pair_verification": verified,
    }


def _git_revision_and_sources(repo_root: Path) -> tuple[str, dict[str, str]]:
    revision = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    hashes: dict[str, str] = {}
    for relative in SOURCE_FILES:
        if _git(
            repo_root, "ls-files", "--error-unmatch", "--", relative, check=False
        ).returncode != 0:
            raise ApparatusFailure(f"experiment source is not committed: {relative}")
        head_oid = _git(repo_root, "rev-parse", f"HEAD:{relative}").stdout.strip()
        worktree_oid = _git(
            repo_root, "hash-object", "--path", relative, "--", relative
        ).stdout.strip()
        if worktree_oid != head_oid:
            raise ApparatusFailure(f"experiment source differs from HEAD: {relative}")
        content = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        hashes[relative] = _sha256_bytes(content)
    return revision, dict(sorted(hashes.items()))


def _assert_sources_unchanged(repo_root: Path, preflight: Mapping[str, Any]) -> None:
    revision, hashes = _git_revision_and_sources(repo_root)
    if revision != preflight["source_revision"] or hashes != preflight["source_file_sha256"]:
        raise ApparatusFailure("committed experiment source changed after preflight")


def _derived_preflight(
    repo_root: Path, *, require_committed: bool
) -> tuple[
    Mapping[str, Any],
    tuple[worlds.BenchmarkCase, ...],
    tuple[PlannedCall, ...],
    Mapping[str, Any],
]:
    lineage = verify_sealed_parent(repo_root)
    payload, cases = _load_frozen_cases(repo_root)
    calls = build_call_plan(payload, cases)
    schedule = condition_schedule()
    schedule_hash = _sha256_text(_canonical_json(schedule))

    if any(sorted(order) != sorted(CONDITIONS) for row in schedule for order in row):
        raise ApparatusFailure("condition schedule contains a non-permutation")
    position_counts = {
        condition: {
            str(position): sum(
                order[position - 1] == condition
                for row in schedule
                for order in row
            )
            for position in range(1, len(CONDITIONS) + 1)
        }
        for condition in CONDITIONS
    }
    if any(
        counts != {"1": 12, "2": 12, "3": 12, "4": 12}
        for counts in position_counts.values()
    ):
        raise ApparatusFailure("condition order is not exactly Williams-counterbalanced")
    carryover_counts = {
        f"{left}->{right}": sum(
            order[index] == left and order[index + 1] == right
            for row in schedule
            for order in row
            for index in range(len(order) - 1)
        )
        for left in CONDITIONS
        for right in CONDITIONS
        if left != right
    }
    if any(count != 12 for count in carryover_counts.values()):
        raise ApparatusFailure("directed adjacent carryover is not exactly balanced")

    prior_prompts = _prior_prompt_map(repo_root)
    input_upper = {condition: 0 for condition in CONDITIONS}
    request_rows = []
    prompt_identity: dict[tuple[int, int, str], str] = {}
    for call in calls:
        representation = REPRESENTATIONS[call.condition]
        prior_prompt = prior_prompts[(representation, call.batch_id)]
        if _input_payload_text(call.prompt) != _input_payload_text(prior_prompt):
            raise ApparatusFailure(
                f"{call.condition} input payload is not byte-identical to its sealed input"
            )
        if call.prompt.split("\n", 1)[1] != prior_prompt.split("\n", 1)[1]:
            raise ApparatusFailure("more than the shared solver title changed from v1.3")
        identity_key = (call.replication, call.batch_id, representation)
        prompt_hash = _sha256_text(call.prompt)
        previous_hash = prompt_identity.setdefault(identity_key, prompt_hash)
        if previous_hash != prompt_hash:
            raise ApparatusFailure("models received different prompts for one representation")
        request = _request_payload(call)
        canonical_request = _canonical_json(request)
        byte_upper = len(canonical_request.encode("utf-8"))
        input_upper[call.condition] += byte_upper
        request_rows.append(
            {
                "global_sequence": call.global_sequence,
                "local_sequence": call.local_sequence,
                "replication": call.replication,
                "condition_position": call.condition_position,
                "batch_id": call.batch_id,
                "condition": call.condition,
                "model_factor": MODEL_FACTOR[call.condition],
                "representation_factor": REPRESENTATION_FACTOR[call.condition],
                "case_ids": list(call.case_ids),
                "prompt_sha256": prompt_hash,
                "prompt_utf8_bytes": len(call.prompt.encode("utf-8")),
                "text_format_sha256": _sha256_text(_canonical_json(call.text_format)),
                "solver_config_sha256": solver_config(call.condition).configuration_hash,
                "request_sha256": _sha256_text(canonical_request),
                "conservative_input_token_upper_bound": byte_upper,
            }
        )

    for model_conditions in ((LUNA_RAW, LUNA_C1), (SOL_RAW, SOL_C1)):
        left = solver_config(model_conditions[0]).to_mapping()
        right = solver_config(model_conditions[1]).to_mapping()
        if left != right:
            raise ApparatusFailure("representation arms within a model have different solver configs")
    luna = solver_config(LUNA_RAW).to_mapping()
    sol = solver_config(SOL_RAW).to_mapping()
    if luna.pop("model") != "gpt-5.6-luna" or sol.pop("model") != "gpt-5.6-sol":
        raise ApparatusFailure("factorial model identities changed")
    if luna != sol:
        raise ApparatusFailure("model arms differ in more than model identity")

    for replication in range(1, REPLICATION_COUNT + 1):
        selected = [call for call in calls if call.replication == replication]
        if len(selected) != 24:
            raise ApparatusFailure("replication does not contain exactly 24 calls")
        for condition in CONDITIONS:
            arm = [call for call in selected if call.condition == condition]
            if [call.batch_id for call in arm] != list(range(1, 7)):
                raise ApparatusFailure("within-arm frozen batch order changed")
            if sum(len(call.case_ids) for call in arm) != CASES_PER_CONDITION:
                raise ApparatusFailure("arm does not contain all 20 frozen worlds")

    output_upper = {
        condition: CALLS_PER_CONDITION * MAX_OUTPUT_TOKENS
        for condition in CONDITIONS
    }
    cost_upper_by_condition = {
        condition: (
            input_upper[condition]
            * PRICING_USD_PER_MILLION[condition]["input"]
            / 1_000_000
            + output_upper[condition]
            * PRICING_USD_PER_MILLION[condition]["output"]
            / 1_000_000
        )
        for condition in CONDITIONS
    }
    cost_upper = sum(cost_upper_by_condition.values())
    if cost_upper > AUTHORIZED_COST_CEILING_USD:
        raise ApparatusFailure("conservative cost upper bound exceeds frozen $55 ceiling")

    raw_bytes = sum(
        len(_canonical_json(worlds.raw_packet(case)).encode("utf-8"))
        for case in cases
    )
    c1_bytes = sum(
        len(
            _canonical_json(
                frontier.transform_compact_packet(worlds.compressed_packet(case), "C1")
            ).encode("utf-8")
        )
        for case in cases
    )
    state_bytes = {
        LUNA_RAW: raw_bytes,
        LUNA_C1: c1_bytes,
        SOL_RAW: raw_bytes,
        SOL_C1: c1_bytes,
    }
    if require_committed:
        revision, source_hashes = _git_revision_and_sources(repo_root)
    else:
        revision = "TEST_UNCOMMITTED"
        source_hashes = {relative: "TEST_UNCOMMITTED" for relative in SOURCE_FILES}

    plan_hash = _sha256_text(_canonical_json(request_rows))
    config_hashes = {
        condition: solver_config(condition).configuration_hash
        for condition in CONDITIONS
    }
    preflight = _sealed(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": revision,
            "source_file_sha256": source_hashes,
            "lineage": lineage,
            "case_pack_sha256": frontier.FROZEN_CASE_PACK_SHA256,
            "expanded_pack_sha256": frontier.FROZEN_EXPANDED_PACK_SHA256,
            "solver_prompt_template_sha256": _sha256_text(
                pair.NEUTRAL_SOLVER_PROMPT_PREFIX
            ),
            "conditions": {
                condition: {
                    "model": MODELS[condition],
                    "model_factor": MODEL_FACTOR[condition],
                    "representation_factor": REPRESENTATION_FACTOR[condition],
                    "representation": (
                        "compact C1 semantic ledger"
                        if REPRESENTATIONS[condition] == "C1"
                        else "full verbose authoritative history"
                    ),
                    **(
                        {"columns": list(frontier.LEVEL_COLUMNS["C1"])}
                        if REPRESENTATIONS[condition] == "C1"
                        else {}
                    ),
                }
                for condition in CONDITIONS
            },
            "solver_configs": {
                condition: solver_config(condition).to_mapping()
                for condition in CONDITIONS
            },
            "solver_config_sha256": config_hashes,
            "factorial_design": {
                "model": ["LUNA", "SOL"],
                "representation": ["RAW", "C1"],
                "fully_crossed": True,
                "only_intentional_request_differences": ["model", "representation"],
            },
            "matched_fields": [
                "20 worlds",
                "six batches",
                "questions",
                "answer options",
                "oracle and grading",
                "solver instruction prefix",
                "reasoning effort medium",
                "max output tokens 16384",
                "strict output schema and exact cardinality",
                "no tools, retries, repair, fallback, storage, or carry-over",
                "one physical attempt per scheduled call",
            ],
            "input_payload_byte_equivalence_to_sealed_v1_3": {
                condition: True for condition in CONDITIONS
            },
            "estimand": (
                "Expected solver accuracy on these fixed 20 worlds under the crossed "
                "Luna/Sol by Raw/C1 conditions and repeated stochastic inference."
            ),
            "causal_claim_boundary": (
                "Within this frozen benchmark, contemporaneous within-model Raw/C1 "
                "contrasts isolate the representation condition; no claim extends to "
                "other worlds, models, learned compression, or long-horizon workflows."
            ),
            "inferential_unit": "complete_20_world_stochastic_replication",
            "fixed_worlds_not_independent_population_samples": True,
            "batch_dependence_disclosed": True,
            "replication_count": REPLICATION_COUNT,
            "batches_per_condition": BATCHES_PER_CONDITION,
            "maximum_physical_generation_calls": MAX_GENERATION_CALLS,
            "calls_per_condition": CALLS_PER_CONDITION,
            "condition_schedule": [[list(order) for order in row] for row in schedule],
            "condition_schedule_sha256": schedule_hash,
            "williams_base_orders": [list(order) for order in WILLIAMS_ORDERS],
            "ordinal_position_counts": position_counts,
            "directed_adjacent_carryover_counts": carryover_counts,
            "request_plan_sha256": plan_hash,
            "call_plan": request_rows,
            "representation_utf8_bytes_per_20_world_replication": state_bytes,
            "attempts_per_call": 1,
            "retry": False,
            "repair": False,
            "fallback": False,
            "tools": False,
            "storage": False,
            "resume": False,
            "overwrite": False,
            "statistics": {
                "confirmatory_family": [
                    "LUNA_C1_MINUS_LUNA_RAW",
                    "SOL_C1_MINUS_SOL_RAW",
                    "REPRESENTATION_BY_MODEL_INTERACTION",
                ],
                "interaction_definition": (
                    "(LUNA_C1-LUNA_RAW)-(SOL_C1-SOL_RAW)"
                ),
                "test": "exact_two_sided_replication_sign_flip_2^8",
                "zero_differences_retained_in_all_256_assignments": True,
                "sign_flip_symmetry_assumption": True,
                "order_schedule_is_not_the_randomization_distribution": True,
                "multiplicity": "Holm correction across exactly three confirmatory tests",
                "alpha": 0.05,
                "non_rejection_is_equivalence": False,
                "case_rows_are_not_independent_inferential_samples": True,
                "secondary": [
                    "pooled representation main effect",
                    "model main effect",
                    "Sol-Luna within each representation",
                    "Luna+C1 versus Sol+Raw",
                    "safety, cost, latency, and token metrics",
                ],
            },
            "capability_gate": {
                "LUNA_RAW_minimum_correct": RAW_CAPABILITY_WARNING_THRESHOLD,
                "SOL_RAW_minimum_correct": RAW_CAPABILITY_WARNING_THRESHOLD,
                "failure_disposition": "VALID_CAPABILITY_WARNING",
                "effect": (
                    "No capable-solver representation claim for a model whose Raw gate "
                    "fails; no interaction claim if either Raw gate fails."
                ),
            },
            "frozen_interpretation": {
                "any_raw_gate_failure": "VALID_CAPABILITY_WARNING",
                "both_raw_gates_pass": "VALID_FACTORIAL_COMPLETE",
                "supported_positive": (
                    "Holm-adjusted p <= .05 and aggregate difference positive"
                ),
                "supported_negative": (
                    "Holm-adjusted p <= .05 and aggregate difference negative"
                ),
                "not_supported": (
                    "Holm-adjusted p > .05 or aggregate difference zero"
                ),
                "positive_interaction_alone_is_not_benefit": True,
                "beneficial_luna_interaction_requires_positive_luna_c1_minus_raw": True,
                "any_apparatus_failure": "INVALID_APPARATUS",
                "non_significance_does_not_prove_equivalence": True,
            },
            "cost": {
                "pricing_usd_per_million": PRICING_USD_PER_MILLION,
                "request_utf8_bytes_input_token_upper_bound": input_upper,
                "output_token_upper_bound": output_upper,
                "condition_cost_upper_bound_usd": cost_upper_by_condition,
                "conservative_generation_cost_upper_bound_usd": cost_upper,
                "authorized_cost_ceiling_usd": AUTHORIZED_COST_CEILING_USD,
                "pilot_maximum_usd": 100.0,
                "note": (
                    "Exact serialized request UTF-8 bytes are a conservative, "
                    "tokenizer-independent input-token upper bound; actual API usage wins."
                ),
            },
        }
    )
    return payload, cases, calls, preflight


def derived_frozen_values(repo_root: Path) -> Mapping[str, Any]:
    _payload, _cases, _calls, preflight = _derived_preflight(
        repo_root, require_committed=False
    )
    return {
        "schedule_sha256": preflight["condition_schedule_sha256"],
        "request_plan_sha256": preflight["request_plan_sha256"],
        "solver_config_sha256": preflight["solver_config_sha256"],
        "input_token_upper_bound": preflight["cost"]
        ["request_utf8_bytes_input_token_upper_bound"],
        "cost_upper_bound_usd": preflight["cost"]
        ["conservative_generation_cost_upper_bound_usd"],
    }


def deterministic_preflight(
    repo_root: Path, *, require_committed: bool = True
) -> tuple[
    Mapping[str, Any],
    tuple[worlds.BenchmarkCase, ...],
    tuple[PlannedCall, ...],
    Mapping[str, Any],
]:
    payload, cases, calls, preflight = _derived_preflight(
        repo_root, require_committed=require_committed
    )
    derived = {
        "schedule_sha256": preflight["condition_schedule_sha256"],
        "request_plan_sha256": preflight["request_plan_sha256"],
        "solver_config_sha256": preflight["solver_config_sha256"],
        "input_token_upper_bound": preflight["cost"]
        ["request_utf8_bytes_input_token_upper_bound"],
        "cost_upper_bound_usd": preflight["cost"]
        ["conservative_generation_cost_upper_bound_usd"],
    }
    frozen = {
        "schedule_sha256": FROZEN_SCHEDULE_SHA256,
        "request_plan_sha256": FROZEN_REQUEST_PLAN_SHA256,
        "solver_config_sha256": FROZEN_SOLVER_CONFIG_SHA256,
        "input_token_upper_bound": FROZEN_INPUT_TOKEN_UPPER_BOUND,
        "cost_upper_bound_usd": FROZEN_COST_UPPER_BOUND_USD,
    }
    if derived != frozen:
        raise ApparatusFailure(
            f"derived protocol constants differ from frozen values: {derived!r}"
        )
    return payload, cases, calls, preflight


def exact_two_sided_sign_flip(differences: Sequence[int]) -> Mapping[str, Any]:
    if len(differences) != REPLICATION_COUNT:
        raise ValueError("exact sign-flip test requires eight replication differences")
    values = tuple(int(value) for value in differences)
    observed = abs(sum(values))
    extreme = 0
    for signs in itertools.product((-1, 1), repeat=REPLICATION_COUNT):
        statistic = abs(sum(sign * value for sign, value in zip(signs, values)))
        if statistic >= observed:
            extreme += 1
    permutations = 2**REPLICATION_COUNT
    return {
        "test": "exact_two_sided_replication_sign_flip",
        "replication_unit": "complete_20_world_run",
        "differences": list(values),
        "observed_absolute_sum": observed,
        "extreme_assignments": extreme,
        "permutations": permutations,
        "p_value": extreme / permutations,
        "zero_differences_retained": True,
        "non_rejection_is_equivalence": False,
    }


def holm_adjust(p_values: Mapping[str, float]) -> Mapping[str, float]:
    if not p_values:
        raise ValueError("Holm family cannot be empty")
    if any(value < 0 or value > 1 for value in p_values.values()):
        raise ValueError("p-values must be in [0, 1]")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    family_size = len(ordered)
    for rank, (comparison_id, p_value) in enumerate(ordered):
        candidate = min(1.0, (family_size - rank) * float(p_value))
        running = max(running, candidate)
        adjusted[comparison_id] = running
    return adjusted


def _measured_int(metadata: Mapping[str, Any], name: str) -> int:
    value = metadata.get(name)
    return value if type(value) is int and value >= 0 else 0


def _measured_float(metadata: Mapping[str, Any], name: str) -> float:
    value = metadata.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _usage(audits: Mapping[str, frontier.OpenAIAuditStore]) -> Mapping[str, Any]:
    by_condition: dict[str, Mapping[str, Any]] = {}
    for condition in CONDITIONS:
        records = audits[condition].records
        input_tokens = sum(_measured_int(row.metadata, "input_tokens") for row in records)
        output_tokens = sum(_measured_int(row.metadata, "output_tokens") for row in records)
        reasoning_tokens = sum(
            _measured_int(row.metadata, "reasoning_tokens") for row in records
        )
        latency = sum(
            _measured_float(row.metadata, "latency_seconds") for row in records
        )
        physical_calls = sum(
            _measured_int(row.metadata, "physical_attempts") for row in records
        )
        price = PRICING_USD_PER_MILLION[condition]
        by_condition[condition] = {
            "call_artifacts": len(records),
            "physical_generation_calls": physical_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_seconds": latency,
            "mean_latency_seconds_per_call": latency / len(records) if records else None,
            "estimated_generation_cost_usd": (
                input_tokens * price["input"] / 1_000_000
                + output_tokens * price["output"] / 1_000_000
            ),
        }
    total_fields = (
        "call_artifacts",
        "physical_generation_calls",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "latency_seconds",
        "estimated_generation_cost_usd",
    )
    return {
        "by_condition": by_condition,
        "total": {
            field: sum(row[field] for row in by_condition.values())
            for field in total_fields
        },
    }


def _comparison(
    comparison_id: str,
    differences: Sequence[int],
    *,
    definition: str,
) -> dict[str, Any]:
    result = dict(exact_two_sided_sign_flip(differences))
    result.update(
        {
            "comparison_id": comparison_id,
            "difference_definition": definition,
            "mean_difference_answers": sum(differences) / REPLICATION_COUNT,
            "aggregate_difference_answers": sum(differences),
            "alpha": 0.05,
        }
    )
    return result


def _safe_percentage(numerator: float, denominator: float) -> float | None:
    return 100 * numerator / denominator if denominator else None


def raw_capability_disposition(totals: Mapping[str, int]) -> Mapping[str, Any]:
    for condition in (LUNA_RAW, SOL_RAW):
        value = totals.get(condition)
        if type(value) is not int or value < 0 or value > TRIALS_PER_CONDITION:
            raise ValueError(f"invalid Raw correct total for {condition}")
    capability = {
        "LUNA": {
            "raw_correct": totals[LUNA_RAW],
            "threshold": RAW_CAPABILITY_WARNING_THRESHOLD,
            "passed": totals[LUNA_RAW] >= RAW_CAPABILITY_WARNING_THRESHOLD,
        },
        "SOL": {
            "raw_correct": totals[SOL_RAW],
            "threshold": RAW_CAPABILITY_WARNING_THRESHOLD,
            "passed": totals[SOL_RAW] >= RAW_CAPABILITY_WARNING_THRESHOLD,
        },
    }
    licenses = {
        "LUNA_C1_MINUS_LUNA_RAW": capability["LUNA"]["passed"],
        "SOL_C1_MINUS_SOL_RAW": capability["SOL"]["passed"],
        "REPRESENTATION_BY_MODEL_INTERACTION": (
            capability["LUNA"]["passed"] and capability["SOL"]["passed"]
        ),
    }
    return {
        "models": capability,
        "primary_claim_licenses": licenses,
        "top_level_result_code": (
            "VALID_FACTORIAL_COMPLETE"
            if all(row["passed"] for row in capability.values())
            else "VALID_CAPABILITY_WARNING"
        ),
    }


def aggregate_valid_result(
    *,
    cases: Sequence[worlds.BenchmarkCase],
    scores: Mapping[int, Mapping[str, Sequence[grading.LabelScore]]],
    audits: Mapping[str, frontier.OpenAIAuditStore],
    preflight: Mapping[str, Any],
) -> Mapping[str, Any]:
    by_case = {case.case_id: case for case in cases}
    vectors: dict[str, list[int]] = {condition: [] for condition in CONDITIONS}
    replication_scores: dict[str, Mapping[str, int]] = {}
    for replication in range(1, REPLICATION_COUNT + 1):
        row: dict[str, int] = {}
        for condition in CONDITIONS:
            selected = list(scores[replication][condition])
            if (
                len(selected) != CASES_PER_CONDITION
                or len({score.case_id for score in selected}) != CASES_PER_CONDITION
            ):
                raise ApparatusFailure("replication is not one complete four-arm benchmark")
            correct = sum(score.answer_correct is True for score in selected)
            row[condition] = correct
            vectors[condition].append(correct)
        replication_scores[str(replication)] = row

    summaries: dict[str, Mapping[str, Any]] = {}
    totals: dict[str, int] = {}
    for condition in CONDITIONS:
        all_scores = [
            score
            for replication in range(1, REPLICATION_COUNT + 1)
            for score in scores[replication][condition]
        ]
        summary = dict(
            study2._score_summary(
                all_scores, by_case, expected_total=TRIALS_PER_CONDITION
            )
        )
        summary["exact_correct_by_replication"] = list(vectors[condition])
        summary["mean_correct_out_of_20"] = sum(vectors[condition]) / REPLICATION_COUNT
        summary["parser_failures"] = 0
        summary["transport_failures"] = 0
        summary["incomplete_responses"] = 0
        summaries[condition] = summary
        totals[condition] = int(summary["exact_correct"])

    luna_representation = [
        c1 - raw for c1, raw in zip(vectors[LUNA_C1], vectors[LUNA_RAW])
    ]
    sol_representation = [
        c1 - raw for c1, raw in zip(vectors[SOL_C1], vectors[SOL_RAW])
    ]
    interaction = [
        luna - sol
        for luna, sol in zip(luna_representation, sol_representation)
    ]
    primary = {
        "LUNA_C1_MINUS_LUNA_RAW": _comparison(
            "LUNA_C1_MINUS_LUNA_RAW",
            luna_representation,
            definition="LUNA_C1_correct_minus_LUNA_RAW_correct_out_of_20",
        ),
        "SOL_C1_MINUS_SOL_RAW": _comparison(
            "SOL_C1_MINUS_SOL_RAW",
            sol_representation,
            definition="SOL_C1_correct_minus_SOL_RAW_correct_out_of_20",
        ),
        "REPRESENTATION_BY_MODEL_INTERACTION": _comparison(
            "REPRESENTATION_BY_MODEL_INTERACTION",
            interaction,
            definition="(LUNA_C1-LUNA_RAW)-(SOL_C1-SOL_RAW)",
        ),
    }
    adjusted = holm_adjust(
        {comparison_id: row["p_value"] for comparison_id, row in primary.items()}
    )
    for comparison_id, row in primary.items():
        row["holm_family"] = list(primary)
        row["holm_adjusted_p_value"] = adjusted[comparison_id]
        row["reject_null_at_alpha_0_05"] = adjusted[comparison_id] <= 0.05
        if row["reject_null_at_alpha_0_05"] and row["aggregate_difference_answers"] > 0:
            row["decision"] = "SUPPORTED_POSITIVE"
        elif row["reject_null_at_alpha_0_05"] and row["aggregate_difference_answers"] < 0:
            row["decision"] = "SUPPORTED_NEGATIVE"
        else:
            row["decision"] = "NOT_SUPPORTED"

    pooled_representation = [
        luna + sol
        for luna, sol in zip(luna_representation, sol_representation)
    ]
    model_main = [
        (sol_raw + sol_c1) - (luna_raw + luna_c1)
        for sol_raw, sol_c1, luna_raw, luna_c1 in zip(
            vectors[SOL_RAW],
            vectors[SOL_C1],
            vectors[LUNA_RAW],
            vectors[LUNA_C1],
        )
    ]
    secondary = {
        "POOLED_C1_MINUS_RAW": _comparison(
            "POOLED_C1_MINUS_RAW",
            pooled_representation,
            definition="(LUNA_C1+SOL_C1)-(LUNA_RAW+SOL_RAW)",
        ),
        "POOLED_SOL_MINUS_LUNA": _comparison(
            "POOLED_SOL_MINUS_LUNA",
            model_main,
            definition="(SOL_RAW+SOL_C1)-(LUNA_RAW+LUNA_C1)",
        ),
        "SOL_MINUS_LUNA_WITH_RAW": _comparison(
            "SOL_MINUS_LUNA_WITH_RAW",
            [sol - luna for sol, luna in zip(vectors[SOL_RAW], vectors[LUNA_RAW])],
            definition="SOL_RAW-LUNA_RAW",
        ),
        "SOL_MINUS_LUNA_WITH_C1": _comparison(
            "SOL_MINUS_LUNA_WITH_C1",
            [sol - luna for sol, luna in zip(vectors[SOL_C1], vectors[LUNA_C1])],
            definition="SOL_C1-LUNA_C1",
        ),
        "LUNA_C1_MINUS_SOL_RAW": _comparison(
            "LUNA_C1_MINUS_SOL_RAW",
            [luna - sol for luna, sol in zip(vectors[LUNA_C1], vectors[SOL_RAW])],
            definition="LUNA_C1-SOL_RAW",
        ),
    }
    for row in secondary.values():
        row["confirmatory"] = False
        row["multiplicity_adjusted"] = False
    for comparison_id in ("POOLED_C1_MINUS_RAW", "POOLED_SOL_MINUS_LUNA"):
        row = secondary[comparison_id]
        row["mean_doubled_factorial_contrast_answers"] = row.pop(
            "mean_difference_answers"
        )
        row["aggregate_doubled_factorial_contrast_answers"] = row.pop(
            "aggregate_difference_answers"
        )
        row["normalized_main_effect_answers_out_of_20"] = (
            row["mean_doubled_factorial_contrast_answers"] / 2
        )
        row["normalized_aggregate_main_effect_answers"] = (
            row["aggregate_doubled_factorial_contrast_answers"] / 2
        )
        row["sign_flip_uses_integer_doubled_contrast"] = True

    gate = raw_capability_disposition(totals)
    capability = gate["models"]
    primary_license = gate["primary_claim_licenses"]
    for comparison_id, row in primary.items():
        row["claim_licensed_by_raw_capability_gate"] = primary_license[comparison_id]
        row["licensed_decision"] = (
            row["decision"]
            if primary_license[comparison_id]
            else "NOT_LICENSED_CAPABILITY_WARNING"
        )
    result_code = str(gate["top_level_result_code"])

    usage = _usage(audits)
    state = preflight["representation_utf8_bytes_per_20_world_replication"]
    efficiency: dict[str, Mapping[str, Any]] = {}
    for model, raw_condition, c1_condition in (
        ("LUNA", LUNA_RAW, LUNA_C1),
        ("SOL", SOL_RAW, SOL_C1),
    ):
        raw_usage = usage["by_condition"][raw_condition]
        c1_usage = usage["by_condition"][c1_condition]
        efficiency[model] = {
            "c1_state_bytes_percentage_of_raw": _safe_percentage(
                state[c1_condition], state[raw_condition]
            ),
            "c1_input_tokens_percentage_of_raw": _safe_percentage(
                c1_usage["input_tokens"], raw_usage["input_tokens"]
            ),
            "c1_cost_percentage_of_raw": _safe_percentage(
                c1_usage["estimated_generation_cost_usd"],
                raw_usage["estimated_generation_cost_usd"],
            ),
            "c1_latency_percentage_of_raw": _safe_percentage(
                c1_usage["latency_seconds"], raw_usage["latency_seconds"]
            ),
        }

    returned_models = {
        condition: sorted(
            {
                str(record.metadata.get("returned_model"))
                for record in audits[condition].records
                if record.metadata.get("returned_model")
            }
        )
        for condition in CONDITIONS
    }
    returned_tiers = {
        condition: sorted(
            {
                str(record.metadata.get("returned_service_tier"))
                for record in audits[condition].records
                if record.metadata.get("returned_service_tier")
            }
        )
        for condition in CONDITIONS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "source_revision": preflight["source_revision"],
        "validity": "VALID",
        "result_code": result_code,
        "evidence_label": "OBSERVED_FACTORIAL_BENCHMARK_RESULT",
        "estimand": preflight["estimand"],
        "replication_count": REPLICATION_COUNT,
        "fixed_world_count": CASES_PER_CONDITION,
        "replication_scores": replication_scores,
        "conditions": summaries,
        "primary_confirmatory_comparisons": primary,
        "secondary_comparisons": secondary,
        "raw_capability_gates": capability,
        "representation_utf8_bytes_per_20_world_replication": state,
        "usage": usage,
        "within_model_efficiency": efficiency,
        "returned_models": returned_models,
        "returned_service_tiers": returned_tiers,
        "physical_generation_calls": usage["total"]["physical_generation_calls"],
        "unique_response_ids": MAX_GENERATION_CALLS,
        "claim_boundary": preflight["causal_claim_boundary"],
        "interpretation_guards": {
            "positive_interaction_is_beneficial_only_if_luna_simple_effect_positive": True,
            "non_rejection_is_not_equivalence": True,
            "raw_gate_failure_blocks_capable_solver_claim_for_that_model": True,
            "raw_gate_failure_blocks_interaction_claim": True,
        },
        "non_claims": [
            "No claim extends beyond this fixed benchmark and frozen configuration.",
            "No result establishes long-horizon workflow performance or transfer.",
            "No result establishes learned compression or recursive improvement.",
            "Non-significance does not establish equivalence.",
        ],
    }


def _write_evidence_index(output_dir: Path, *, source_revision: str) -> Mapping[str, Any]:
    index_path = output_dir / "EVIDENCE_INDEX.json"
    rows = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        if path == index_path:
            continue
        rows.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
            }
        )
    index = _sealed(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "source_revision": source_revision,
            "file_count": len(rows),
            "total_bytes": sum(row["bytes"] for row in rows),
            "files": rows,
        }
    )
    frontier._write_exclusive(index_path, _pretty_json(index))
    return index


_SOURCE_FAILURE_PREFIXES = (
    "experiment source differs from HEAD:",
    "experiment source is not committed:",
    "committed experiment source changed after preflight",
)


def _is_source_failure_reason(reason: str) -> bool:
    return any(reason.startswith(prefix) for prefix in _SOURCE_FAILURE_PREFIXES)


def _capture_source_state(repo_root: Path) -> Mapping[str, Any]:
    revision = _git(repo_root, "rev-parse", "HEAD", check=False)
    return {
        "head_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "source_file_sha256": {
            relative: (
                _sha256_bytes((repo_root / relative).read_bytes())
                if (repo_root / relative).is_file()
                else None
            )
            for relative in SOURCE_FILES
        },
    }


def _artifact_pointer(path: Path, root: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    _verify_seal(payload)
    return {
        "path": path.relative_to(root).as_posix(),
        "file_sha256": _sha256_bytes(path.read_bytes()),
        "status": payload.get("status"),
    }


def _failure_class(
    *,
    reason: str,
    call: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
) -> str:
    if _is_source_failure_reason(reason):
        return "source_integrity_failure"
    if decision is not None and decision.get("status") == "parser_rejected":
        return "parser_failure"
    if call is not None and call.get("status") == "transport_error":
        return "transport_failure"
    if call is not None and call.get("status") == "metadata_rejected":
        return "metadata_failure"
    if reason == "provider response ID is missing or reused":
        return "response_identity_failure"
    return "unverified_internal_failure"


def _failure_evidence(
    *,
    output_dir: Path,
    failed_call: PlannedCall,
    reason: str,
    repo_root: Path,
) -> Mapping[str, Any]:
    condition_dir = output_dir / failed_call.condition.lower()
    call_path = condition_dir / "calls" / f"call_{failed_call.local_sequence:06d}.json"
    decision_path = (
        condition_dir
        / "decisions"
        / f"decision_{failed_call.local_sequence:06d}.json"
    )
    call = (
        json.loads(call_path.read_text(encoding="utf-8"))
        if call_path.is_file()
        else None
    )
    decision = (
        json.loads(decision_path.read_text(encoding="utf-8"))
        if decision_path.is_file()
        else None
    )
    failure_class = _failure_class(reason=reason, call=call, decision=decision)
    return {
        "failure_class": failure_class,
        "reason_sha256": _sha256_text(reason),
        "failed_call_artifact": _artifact_pointer(call_path, output_dir),
        "failed_decision_artifact": _artifact_pointer(decision_path, output_dir),
        "source_state_at_failure": (
            _capture_source_state(repo_root)
            if failure_class == "source_integrity_failure"
            else None
        ),
    }


class FactorialRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        output_dir: Path,
        ask_fn: Callable[..., str] = ask_hive,
        require_committed: bool = True,
        progress_stream: Any | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.output_dir = output_dir
        self.ask_fn = ask_fn
        self.require_committed = require_committed
        self.progress_stream = sys.stderr if progress_stream is None else progress_stream
        self._progress_line_length = 0
        self.scores: dict[int, dict[str, list[grading.LabelScore]]] = {
            replication: {condition: [] for condition in CONDITIONS}
            for replication in range(1, REPLICATION_COUNT + 1)
        }
        self.response_ids: set[str] = set()
        self.audits: dict[str, frontier.OpenAIAuditStore] = {}

    def _show_progress(
        self,
        completed: int,
        *,
        detail: str = "",
        finish_line: bool = False,
    ) -> None:
        if self.progress_stream is False:
            return
        line = render_progress(completed, MAX_GENERATION_CALLS, detail=detail)
        padding = " " * max(0, self._progress_line_length - len(line))
        try:
            self.progress_stream.write("\r" + line + padding)
            if finish_line:
                self.progress_stream.write("\n")
            self.progress_stream.flush()
        except (AttributeError, OSError, ValueError):
            self.progress_stream = False
            return
        self._progress_line_length = 0 if finish_line else len(line)

    def _run_call(
        self,
        planned: PlannedCall,
        by_case: Mapping[str, worlds.BenchmarkCase],
    ) -> None:
        audit = self.audits[planned.condition]
        response = audit.ask(planned.audit_call())
        record = audit.records[-1]
        artifact = audit_helpers._call_artifact(audit, record)
        config = solver_config(planned.condition)
        response_id = audit_helpers._validate_attempt_contract(
            artifact,
            config,
            require_response_identity=True,
            expected_text_format=planned.text_format,
        )
        if response_id is None or response_id in self.response_ids:
            raise ApparatusFailure("provider response ID is missing or reused")
        self.response_ids.add(response_id)
        selected_cases = [by_case[case_id] for case_id in planned.case_ids]
        try:
            labels = frontier.parse_structured_labels(response, len(selected_cases))
        except grading.ConstrainedInterfaceFailure as exc:
            audit.write_decision(
                record,
                {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "global_sequence": planned.global_sequence,
                    "call_id": record.call_id,
                    "status": "parser_rejected",
                    "replication": planned.replication,
                    "condition_position": planned.condition_position,
                    "batch_id": planned.batch_id,
                    "condition": planned.condition,
                    "parser_status": "failed",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "error": str(exc),
                    "scores": [],
                    "retry_attempted": False,
                    "repair_attempted": False,
                },
            )
            raise ApparatusFailure("strict constrained-output parser rejected a call") from None
        generated = [
            grading.grade_label(case, label, condition=planned.condition)
            for case, label in zip(selected_cases, labels)
        ]
        if any(score.secondary_status != "ran" for score in generated):
            raise ApparatusFailure("deterministic secondary grading failed")
        self.scores[planned.replication][planned.condition].extend(generated)
        audit.write_decision(
            record,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "global_sequence": planned.global_sequence,
                "call_id": record.call_id,
                "status": "graded",
                "replication": planned.replication,
                "condition_position": planned.condition_position,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "response_id": response_id,
                "parser_status": "passed",
                "grader_status": "ran",
                "grader_agreement": True,
                "labels": list(labels),
                "scores": [asdict(score) for score in generated],
                "physical_attempts": 1,
                "retry_attempted": False,
                "repair_attempted": False,
            },
        )

    def _finish(
        self, *, preflight: Mapping[str, Any], result: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        frontier._write_exclusive(
            self.output_dir / "RESULT.json", _pretty_json(_sealed(result))
        )
        usage = result["usage"]
        frontier._write_exclusive(
            self.output_dir / "RUN_STATUS.json",
            _pretty_json(
                _sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "finished_at_utc": frontier._utc_now(),
                        "validity": result["validity"],
                        "result_code": result["result_code"],
                        "call_artifacts": usage["total"]["call_artifacts"],
                        "physical_generation_calls": usage["total"]
                        ["physical_generation_calls"],
                        "unique_response_ids": len(self.response_ids),
                    }
                )
            ),
        )
        _write_evidence_index(
            self.output_dir, source_revision=str(preflight["source_revision"])
        )
        return result

    def _invalid(
        self,
        *,
        preflight: Mapping[str, Any],
        failed_call: PlannedCall,
        exc: BaseException,
    ) -> Mapping[str, Any]:
        reason = study2._safe_reason(exc)
        invalid = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": preflight["source_revision"],
            "validity": "INVALID",
            "result_code": "INVALID_APPARATUS",
            "failed_global_sequence": failed_call.global_sequence,
            "failed_replication": failed_call.replication,
            "failed_condition": failed_call.condition,
            "failed_batch_id": failed_call.batch_id,
            "apparatus_failure": reason,
            "failure_evidence": _failure_evidence(
                output_dir=self.output_dir,
                failed_call=failed_call,
                reason=reason,
                repo_root=self.repo_root,
            ),
            "partial_score_counts": {
                str(replication): {
                    condition: len(self.scores[replication][condition])
                    for condition in CONDITIONS
                }
                for replication in range(1, REPLICATION_COUNT + 1)
            },
            "usage": _usage(self.audits),
            "evidence_interpretation": "No factorial representation claim is licensed.",
            "partial_artifacts_preserved": True,
            "retry_attempted": False,
            "repair_attempted": False,
        }
        return self._finish(preflight=preflight, result=invalid)

    def run(self) -> Mapping[str, Any]:
        expected = (self.repo_root / RUN_DIR).resolve()
        if self.require_committed and self.output_dir.resolve() != expected:
            raise ApparatusFailure("live execution is locked to the frozen run directory")
        if self.output_dir.exists():
            raise ApparatusFailure("run directory already exists; no inference was started")
        payload, cases, calls, preflight = deterministic_preflight(
            self.repo_root, require_committed=self.require_committed
        )
        del payload
        if self.output_dir.exists():
            raise ApparatusFailure("run directory appeared during preflight")
        self.output_dir.mkdir(parents=True, exist_ok=False)
        frontier._write_exclusive(
            self.output_dir / "PRECHECK.json", _pretty_json(preflight)
        )
        protocol = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "mission": "crossed Luna/Sol by Raw/C1 factorial comparison",
            "conditions": list(CONDITIONS),
            "replications": REPLICATION_COUNT,
            "scheduled_calls": MAX_GENERATION_CALLS,
            "schedule_sha256": FROZEN_SCHEDULE_SHA256,
            "request_plan_sha256": FROZEN_REQUEST_PLAN_SHA256,
            "confirmatory_family": [
                "LUNA_C1_MINUS_LUNA_RAW",
                "SOL_C1_MINUS_SOL_RAW",
                "REPRESENTATION_BY_MODEL_INTERACTION",
            ],
            "holm_family_size": 3,
            "one_physical_attempt": True,
            "retry": False,
            "repair": False,
            "fallback": False,
            "fail_closed": True,
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "created_at_utc": frontier._utc_now(),
            "source_revision": preflight["source_revision"],
            "precheck_sha256": preflight["payload_sha256"],
            "solver_config_sha256": preflight["solver_config_sha256"],
            "maximum_physical_generation_calls": MAX_GENERATION_CALLS,
            "no_retry": True,
            "no_resume": True,
            "no_overwrite": True,
        }
        for name, value in (("PROTOCOL.json", protocol), ("MANIFEST.json", manifest)):
            frontier._write_exclusive(
                self.output_dir / name, _pretty_json(_sealed(value))
            )

        self.audits = {
            condition: frontier.OpenAIAuditStore(
                self.output_dir / condition.lower(),
                ask_fn=self.ask_fn,
                config=solver_config(condition),
            )
            for condition in CONDITIONS
        }
        by_case = {case.case_id: case for case in cases}
        self._show_progress(0, detail="ready")
        for planned in calls:
            try:
                if self.require_committed:
                    _assert_sources_unchanged(self.repo_root, preflight)
                self._run_call(planned, by_case)
                self._show_progress(
                    planned.global_sequence,
                    detail=(
                        f"rep {planned.replication}/{REPLICATION_COUNT}  "
                        f"batch {planned.batch_id}/{BATCHES_PER_CONDITION}  "
                        f"{planned.condition}"
                    ),
                    finish_line=planned.global_sequence == MAX_GENERATION_CALLS,
                )
                if self.require_committed:
                    _assert_sources_unchanged(self.repo_root, preflight)
            except BaseException as exc:
                self._show_progress(
                    planned.global_sequence,
                    detail=f"FAILED  {planned.condition}",
                    finish_line=True,
                )
                return self._invalid(
                    preflight=preflight, failed_call=planned, exc=exc
                )
        try:
            if sum(len(audit.records) for audit in self.audits.values()) != MAX_GENERATION_CALLS:
                raise ApparatusFailure("completed schedule has the wrong call count")
            if len(self.response_ids) != MAX_GENERATION_CALLS:
                raise ApparatusFailure("completed schedule reused response identities")
            result = aggregate_valid_result(
                cases=cases,
                scores=self.scores,
                audits=self.audits,
                preflight=preflight,
            )
        except BaseException as exc:
            return self._invalid(preflight=preflight, failed_call=calls[-1], exc=exc)
        return self._finish(preflight=preflight, result=result)


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "RUN_STATUS.json").read_text(encoding="utf-8"))
    preflight = json.loads((run_dir / "PRECHECK.json").read_text(encoding="utf-8"))
    index = json.loads((run_dir / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    for payload in (result, status, preflight, index):
        _verify_seal(payload)

    source_revision = str(preflight.get("source_revision", ""))
    source_check_required = source_revision != "TEST_UNCOMMITTED"
    if source_check_required:
        if not source_revision:
            raise ApparatusFailure("recorded source revision is missing")
        resolved = _git(
            repo_root, "rev-parse", f"{source_revision}^{{commit}}"
        ).stdout.strip()
        if resolved != source_revision:
            raise ApparatusFailure("recorded source revision did not resolve exactly")
        recorded_hashes = preflight.get("source_file_sha256")
        if not isinstance(recorded_hashes, Mapping) or set(recorded_hashes) != set(
            SOURCE_FILES
        ):
            raise ApparatusFailure("recorded source hash set is incomplete")
        for relative in SOURCE_FILES:
            content = subprocess.run(
                ["git", "show", f"{source_revision}:{relative}"],
                cwd=repo_root,
                check=True,
                capture_output=True,
            ).stdout
            if _sha256_bytes(content) != recorded_hashes[relative]:
                raise ApparatusFailure(f"recorded source hash mismatch for {relative}")

    _payload, cases, expected_calls, regenerated_preflight = _derived_preflight(
        repo_root, require_committed=False
    )
    stored_stable = dict(preflight)
    regenerated_stable = dict(regenerated_preflight)
    for payload in (stored_stable, regenerated_stable):
        payload.pop("payload_sha256", None)
        payload.pop("source_revision", None)
        payload.pop("source_file_sha256", None)
        payload.pop("lineage", None)
    if _canonical_json(stored_stable) != _canonical_json(regenerated_stable):
        raise ApparatusFailure("sealed preflight differs from deterministic protocol")

    index_files = index.get("files")
    if not isinstance(index_files, list) or any(
        not isinstance(row, Mapping) for row in index_files
    ):
        raise ApparatusFailure("evidence index file rows are malformed")
    if (
        index.get("schema_version") != SCHEMA_VERSION
        or index.get("protocol_id") != PROTOCOL_ID
        or index.get("source_revision") != preflight.get("source_revision")
        or index.get("file_count") != len(index_files)
        or index.get("total_bytes")
        != sum(row.get("bytes", -1) for row in index_files)
    ):
        raise ApparatusFailure("evidence index metadata is inconsistent")
    indexed = {str(row["path"]): row for row in index_files}
    if len(indexed) != len(index_files):
        raise ApparatusFailure("evidence index contains duplicate paths")
    actual = {
        path.relative_to(run_dir).as_posix(): path
        for path in run_dir.rglob("*")
        if path.is_file() and path.name != "EVIDENCE_INDEX.json"
    }
    if set(indexed) != set(actual):
        raise ApparatusFailure("evidence index file set differs from disk")
    for relative, path in actual.items():
        row = indexed[relative]
        if (
            row["bytes"] != path.stat().st_size
            or row["sha256"] != _sha256_bytes(path.read_bytes())
        ):
            raise ApparatusFailure(f"evidence index mismatch for {relative}")

    call_paths = sorted(run_dir.glob("*/calls/call_*.json"))
    decision_paths = sorted(run_dir.glob("*/decisions/decision_*.json"))
    response_ids: list[str] = []
    returned_models: dict[str, set[str]] = {condition: set() for condition in CONDITIONS}
    returned_tiers: dict[str, set[str]] = {condition: set() for condition in CONDITIONS}
    records_by_condition: dict[str, list[frontier.CallRecord]] = {
        condition: [] for condition in CONDITIONS
    }
    recomputed_scores: dict[int, dict[str, list[grading.LabelScore]]] = {
        replication: {condition: [] for condition in CONDITIONS}
        for replication in range(1, REPLICATION_COUNT + 1)
    }
    by_case = {case.case_id: case for case in cases}
    actual_call_paths = {path.as_posix(): path for path in call_paths}
    actual_decision_paths = {path.as_posix(): path for path in decision_paths}

    validity = result.get("validity")
    if validity not in {"VALID", "INVALID"}:
        raise ApparatusFailure("RESULT has an unknown validity state")

    failed_call: PlannedCall | None = None
    failed_call_path: Path | None = None
    failed_decision_path: Path | None = None
    failed_decision_status: str | None = None
    calls_to_recompute: Sequence[PlannedCall]
    if validity == "VALID":
        calls_to_recompute = expected_calls
    else:
        if result.get("result_code") != "INVALID_APPARATUS":
            raise ApparatusFailure("invalid result lacks INVALID_APPARATUS disposition")
        failed_sequence = result.get("failed_global_sequence")
        if type(failed_sequence) is not int or not 1 <= failed_sequence <= len(
            expected_calls
        ):
            raise ApparatusFailure("invalid result has an impossible failed sequence")
        failed_call = expected_calls[failed_sequence - 1]
        exact_failure_fields = {
            "failed_replication": failed_call.replication,
            "failed_condition": failed_call.condition,
            "failed_batch_id": failed_call.batch_id,
        }
        if any(result.get(name) != value for name, value in exact_failure_fields.items()):
            raise ApparatusFailure("invalid result failure identity differs from the plan")

        def artifact_paths(planned: PlannedCall) -> tuple[Path, Path]:
            root = run_dir / planned.condition.lower()
            return (
                root / "calls" / f"call_{planned.local_sequence:06d}.json",
                root
                / "decisions"
                / f"decision_{planned.local_sequence:06d}.json",
            )

        prior = expected_calls[: failed_sequence - 1]
        prior_call_keys = {artifact_paths(planned)[0].as_posix() for planned in prior}
        prior_decision_keys = {
            artifact_paths(planned)[1].as_posix() for planned in prior
        }
        failed_call_path, failed_decision_path = artifact_paths(failed_call)
        allowed_call_keys = prior_call_keys | {failed_call_path.as_posix()}
        allowed_decision_keys = prior_decision_keys | {
            failed_decision_path.as_posix()
        }
        if not prior_call_keys.issubset(actual_call_paths) or not prior_decision_keys.issubset(
            actual_decision_paths
        ):
            raise ApparatusFailure("invalid run is missing a completed prefix artifact")
        if not set(actual_call_paths).issubset(allowed_call_keys) or not set(
            actual_decision_paths
        ).issubset(allowed_decision_keys):
            raise ApparatusFailure("invalid run contains artifacts after its failed call")
        if failed_decision_path.as_posix() in actual_decision_paths and (
            failed_call_path.as_posix() not in actual_call_paths
        ):
            raise ApparatusFailure("invalid run has a decision without its call artifact")

        if failed_decision_path.as_posix() in actual_decision_paths:
            failed_decision = json.loads(
                failed_decision_path.read_text(encoding="utf-8")
            )
            _verify_seal(failed_decision)
            failed_decision_status = str(failed_decision.get("status", ""))
        calls_to_recompute = (
            expected_calls[:failed_sequence]
            if failed_decision_status == "graded"
            else prior
        )
    for planned in calls_to_recompute:
        call_path = (
            run_dir
            / planned.condition.lower()
            / "calls"
            / f"call_{planned.local_sequence:06d}.json"
        )
        decision_path = (
            run_dir
            / planned.condition.lower()
            / "decisions"
            / f"decision_{planned.local_sequence:06d}.json"
        )
        if call_path.as_posix() not in actual_call_paths:
            raise ApparatusFailure("expected call artifact is missing")
        if decision_path.as_posix() not in actual_decision_paths:
            raise ApparatusFailure("expected decision artifact is missing")
        call = json.loads(call_path.read_text(encoding="utf-8"))
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        _verify_seal(call)
        _verify_seal(decision)
        expected_call_id = f"call_{planned.local_sequence:06d}"
        exact_call_fields = {
            "call_id": expected_call_id,
            "sequence": planned.local_sequence,
            "stage": planned.stage,
            "batch_id": planned.batch_id,
            "condition": planned.condition,
            "case_ids": list(planned.case_ids),
            "status": "completed",
        }
        if any(call.get(name) != value for name, value in exact_call_fields.items()):
            raise ApparatusFailure("call artifact differs from frozen call plan")
        request = call.get("request")
        if not isinstance(request, Mapping):
            raise ApparatusFailure("call request artifact is missing")
        config = solver_config(planned.condition)
        expected_request_fields = {
            "prompt": planned.prompt,
            "prompt_sha256": _sha256_text(planned.prompt),
            "openai_text_format": planned.text_format,
            "openai_text_format_sha256": _sha256_text(
                _canonical_json(planned.text_format)
            ),
            "solver_config": config.to_mapping(),
            "solver_config_sha256": config.configuration_hash,
        }
        if _canonical_json(request) != _canonical_json(expected_request_fields):
            raise ApparatusFailure("call request differs from frozen prompt/schema/config")
        response = call.get("response")
        if not isinstance(response, Mapping) or not isinstance(
            response.get("raw_text"), str
        ):
            raise ApparatusFailure("completed call lacks raw response text")
        raw_text = str(response["raw_text"])
        if response.get("sha256") != _sha256_text(raw_text):
            raise ApparatusFailure("raw response hash is inconsistent")
        response_id = audit_helpers._validate_attempt_contract(
            call,
            config,
            require_response_identity=True,
            expected_text_format=planned.text_format,
        )
        if response_id is None:
            raise ApparatusFailure("provider response identity is missing")
        response_ids.append(response_id)
        metadata = call["transport_metadata"]
        returned_models[planned.condition].add(str(metadata["returned_model"]))
        returned_tiers[planned.condition].add(str(metadata["returned_service_tier"]))
        labels = frontier.parse_structured_labels(raw_text, len(planned.case_ids))
        generated = [
            grading.grade_label(by_case[case_id], label, condition=planned.condition)
            for case_id, label in zip(planned.case_ids, labels)
        ]
        recomputed_scores[planned.replication][planned.condition].extend(generated)
        expected_decision = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "global_sequence": planned.global_sequence,
            "call_id": expected_call_id,
            "status": "graded",
            "replication": planned.replication,
            "condition_position": planned.condition_position,
            "batch_id": planned.batch_id,
            "condition": planned.condition,
            "response_id": response_id,
            "parser_status": "passed",
            "grader_status": "ran",
            "grader_agreement": True,
            "labels": list(labels),
            "scores": [asdict(score) for score in generated],
            "physical_attempts": 1,
            "retry_attempted": False,
            "repair_attempted": False,
        }
        decision_body = {
            key: value for key, value in decision.items() if key != "payload_sha256"
        }
        if _canonical_json(decision_body) != _canonical_json(expected_decision):
            raise ApparatusFailure("decision differs from reparsed and regraded response")
        records_by_condition[planned.condition].append(
            frontier.CallRecord(
                sequence=planned.local_sequence,
                call_id=expected_call_id,
                stage=planned.stage,
                batch_id=planned.batch_id,
                condition=planned.condition,
                artifact_path=call_path.relative_to(
                    run_dir / planned.condition.lower()
                ).as_posix(),
                artifact_file_sha256=_sha256_bytes(call_path.read_bytes()),
                status="completed",
                metadata=copy.deepcopy(metadata),
            )
        )

    if validity == "INVALID":
        assert failed_call is not None
        assert failed_call_path is not None
        assert failed_decision_path is not None
        reason = result.get("apparatus_failure")
        if not isinstance(reason, str) or not reason:
            raise ApparatusFailure("invalid result lacks an apparatus failure reason")

        failed_call_payload: Mapping[str, Any] | None = None
        failed_decision_payload: Mapping[str, Any] | None = None
        failure_reason_from_artifacts: str | None = None
        if failed_call_path.is_file() and failed_decision_status != "graded":
            failed_call_payload = json.loads(
                failed_call_path.read_text(encoding="utf-8")
            )
            _verify_seal(failed_call_payload)
            expected_call_id = f"call_{failed_call.local_sequence:06d}"
            expected_base_fields = {
                "call_id": expected_call_id,
                "sequence": failed_call.local_sequence,
                "stage": failed_call.stage,
                "batch_id": failed_call.batch_id,
                "condition": failed_call.condition,
                "case_ids": list(failed_call.case_ids),
            }
            if any(
                failed_call_payload.get(name) != value
                for name, value in expected_base_fields.items()
            ):
                raise ApparatusFailure("failed call differs from the frozen call plan")
            request = failed_call_payload.get("request")
            config = solver_config(failed_call.condition)
            expected_request = {
                "prompt": failed_call.prompt,
                "prompt_sha256": _sha256_text(failed_call.prompt),
                "openai_text_format": failed_call.text_format,
                "openai_text_format_sha256": _sha256_text(
                    _canonical_json(failed_call.text_format)
                ),
                "solver_config": config.to_mapping(),
                "solver_config_sha256": config.configuration_hash,
            }
            if not isinstance(request, Mapping) or _canonical_json(
                request
            ) != _canonical_json(expected_request):
                raise ApparatusFailure("failed call request differs from the frozen plan")
            metadata = failed_call_payload.get("transport_metadata")
            if not isinstance(metadata, Mapping):
                raise ApparatusFailure("failed call transport metadata is malformed")
            call_status = failed_call_payload.get("status")
            if call_status == "completed":
                response = failed_call_payload.get("response")
                if not isinstance(response, Mapping) or not isinstance(
                    response.get("raw_text"), str
                ):
                    raise ApparatusFailure("failed completed call lacks raw response text")
                raw_text = str(response["raw_text"])
                if response.get("sha256") != _sha256_text(raw_text):
                    raise ApparatusFailure("failed call raw response hash is inconsistent")
                response_id = audit_helpers._validate_attempt_contract(
                    failed_call_payload,
                    config,
                    require_response_identity=True,
                    expected_text_format=failed_call.text_format,
                )
                assert response_id is not None
                response_ids.append(response_id)
                returned_models[failed_call.condition].add(
                    str(metadata["returned_model"])
                )
                returned_tiers[failed_call.condition].add(
                    str(metadata["returned_service_tier"])
                )
                if failed_decision_path.is_file():
                    failed_decision_payload = json.loads(
                        failed_decision_path.read_text(encoding="utf-8")
                    )
                    _verify_seal(failed_decision_payload)
                if failed_decision_status != "parser_rejected":
                    if len(response_ids) != len(set(response_ids)):
                        failure_reason_from_artifacts = (
                            "provider response ID is missing or reused"
                        )
                    else:
                        raise ApparatusFailure(
                            "completed failed call lacks a derivable rejected decision"
                        )
                else:
                    try:
                        frontier.parse_structured_labels(
                            raw_text, len(failed_call.case_ids)
                        )
                    except grading.ConstrainedInterfaceFailure as exc:
                        parser_error = str(exc)
                    else:
                        raise ApparatusFailure(
                            "parser-rejected decision contains an admissible response"
                        )
                    expected_decision = {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "global_sequence": failed_call.global_sequence,
                        "call_id": expected_call_id,
                        "status": "parser_rejected",
                        "replication": failed_call.replication,
                        "condition_position": failed_call.condition_position,
                        "batch_id": failed_call.batch_id,
                        "condition": failed_call.condition,
                        "parser_status": "failed",
                        "grader_status": "not_run",
                        "grader_agreement": None,
                        "error": parser_error,
                        "scores": [],
                        "retry_attempted": False,
                        "repair_attempted": False,
                    }
                    decision_body = {
                        key: value
                        for key, value in failed_decision_payload.items()
                        if key != "payload_sha256"
                    }
                    if _canonical_json(decision_body) != _canonical_json(
                        expected_decision
                    ):
                        raise ApparatusFailure(
                            "parser-rejected decision differs from the raw response"
                        )
                    failure_reason_from_artifacts = (
                        "strict constrained-output parser rejected a call"
                    )
            elif call_status == "transport_error":
                if failed_decision_path.is_file():
                    raise ApparatusFailure("transport failure unexpectedly has a decision")
                if any(
                    metadata.get(name) != value
                    for name, value in config.to_mapping().items()
                ):
                    raise ApparatusFailure(
                        "transport failure changed the frozen solver configuration"
                    )
                transport_error = failed_call_payload.get("transport_error")
                response = failed_call_payload.get("response")
                if (
                    not isinstance(transport_error, Mapping)
                    or not isinstance(transport_error.get("message"), str)
                    or failed_call_payload.get("admission_error") is not None
                    or not isinstance(response, Mapping)
                    or response.get("raw_text") is not None
                    or response.get("sha256") is not None
                ):
                    raise ApparatusFailure("transport-failure envelope is incoherent")
                if metadata.get("physical_attempts") not in {0, 1}:
                    raise ApparatusFailure("transport failure has an impossible attempt count")
                failure_reason_from_artifacts = (
                    f"{expected_call_id} transport failed: "
                    f"{transport_error['message']}"
                )
            elif call_status == "metadata_rejected":
                if failed_decision_path.is_file():
                    raise ApparatusFailure("metadata failure unexpectedly has a decision")
                admission_error = failed_call_payload.get("admission_error")
                if (
                    not isinstance(admission_error, Mapping)
                    or not isinstance(admission_error.get("message"), str)
                    or failed_call_payload.get("transport_error") is not None
                ):
                    raise ApparatusFailure("metadata-failure envelope is incoherent")
                try:
                    frontier._validate_metadata(
                        metadata,
                        config=config,
                        expected_text_format=failed_call.text_format,
                        expected_returned_model=config.model,
                    )
                except BaseException as exc:
                    if str(exc) != admission_error["message"]:
                        raise ApparatusFailure(
                            "metadata rejection reason is not independently reproducible"
                        ) from None
                else:
                    raise ApparatusFailure(
                        "metadata-rejected call passes the frozen metadata validator"
                    )
                response = failed_call_payload.get("response")
                if isinstance(response, Mapping) and isinstance(
                    response.get("raw_text"), str
                ):
                    raw_text = str(response["raw_text"])
                    if response.get("sha256") != _sha256_text(raw_text):
                        raise ApparatusFailure(
                            "metadata-rejected raw response hash is inconsistent"
                        )
                failure_reason_from_artifacts = (
                    f"{expected_call_id} metadata rejected: "
                    f"{admission_error['message']}"
                )
            else:
                raise ApparatusFailure("failed call has an unknown status")

            records_by_condition[failed_call.condition].append(
                frontier.CallRecord(
                    sequence=failed_call.local_sequence,
                    call_id=expected_call_id,
                    stage=failed_call.stage,
                    batch_id=failed_call.batch_id,
                    condition=failed_call.condition,
                    artifact_path=failed_call_path.relative_to(
                        run_dir / failed_call.condition.lower()
                    ).as_posix(),
                    artifact_file_sha256=_sha256_bytes(
                        failed_call_path.read_bytes()
                    ),
                    status=str(failed_call_payload["status"]),
                    metadata=copy.deepcopy(metadata),
                )
            )

        failure_class = _failure_class(
            reason=reason,
            call=failed_call_payload,
            decision=failed_decision_payload,
        )
        duplicate_response_ids = {
            response_id: count
            for response_id, count in Counter(response_ids).items()
            if count > 1
        }
        if failure_class == "response_identity_failure":
            if (
                len(response_ids) < 2
                or len(duplicate_response_ids) != 1
                or next(iter(duplicate_response_ids.values())) != 2
                or response_ids[-1] not in duplicate_response_ids
            ):
                raise ApparatusFailure(
                    "response-identity failure is not the first stopped-prefix reuse"
                )
        elif duplicate_response_ids:
            raise ApparatusFailure("invalid run reused a provider response identity")
        if failure_class == "source_integrity_failure":
            if failed_call_payload is not None and failed_decision_status != "graded":
                raise ApparatusFailure(
                    "source-integrity failure is inconsistent with the call boundary"
                )
            source_state = result.get("failure_evidence", {}).get(
                "source_state_at_failure"
            )
            if not isinstance(source_state, Mapping) or set(source_state) != {
                "head_revision",
                "source_file_sha256",
            }:
                raise ApparatusFailure("source-integrity failure lacks a source snapshot")
            source_hashes = source_state.get("source_file_sha256")
            if not isinstance(source_hashes, Mapping) or set(source_hashes) != set(
                SOURCE_FILES
            ):
                raise ApparatusFailure("source failure snapshot has an incomplete hash set")
            if (
                source_state.get("head_revision") == preflight["source_revision"]
                and dict(source_hashes) == preflight["source_file_sha256"]
            ):
                raise ApparatusFailure("source failure snapshot contains no source drift")
        elif failure_class == "unverified_internal_failure":
            raise ApparatusFailure("invalid run failure is not independently verifiable")
        elif failure_reason_from_artifacts != reason:
            raise ApparatusFailure("invalid result reason differs from failed-call evidence")

        failure_evidence = result.get("failure_evidence")
        if not isinstance(failure_evidence, Mapping):
            raise ApparatusFailure("invalid result lacks structured failure evidence")
        expected_failure_evidence = {
            "failure_class": failure_class,
            "reason_sha256": _sha256_text(reason),
            "failed_call_artifact": _artifact_pointer(
                failed_call_path, run_dir
            ),
            "failed_decision_artifact": _artifact_pointer(
                failed_decision_path, run_dir
            ),
            "source_state_at_failure": (
                failure_evidence.get("source_state_at_failure")
                if failure_class == "source_integrity_failure"
                else None
            ),
        }
        if _canonical_json(failure_evidence) != _canonical_json(
            expected_failure_evidence
        ):
            raise ApparatusFailure("invalid result failure evidence is inconsistent")

        expected_partial_counts = {
            str(replication): {
                condition: len(recomputed_scores[replication][condition])
                for condition in CONDITIONS
            }
            for replication in range(1, REPLICATION_COUNT + 1)
        }
        recomputed_usage = _usage(
            {
                condition: SimpleNamespace(records=records_by_condition[condition])
                for condition in CONDITIONS
            }
        )
        expected_invalid = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": preflight["source_revision"],
            "validity": "INVALID",
            "result_code": "INVALID_APPARATUS",
            "failed_global_sequence": failed_call.global_sequence,
            "failed_replication": failed_call.replication,
            "failed_condition": failed_call.condition,
            "failed_batch_id": failed_call.batch_id,
            "apparatus_failure": reason,
            "failure_evidence": expected_failure_evidence,
            "partial_score_counts": expected_partial_counts,
            "usage": recomputed_usage,
            "evidence_interpretation": (
                "No factorial representation claim is licensed."
            ),
            "partial_artifacts_preserved": True,
            "retry_attempted": False,
            "repair_attempted": False,
        }
        result_body = {
            key: value for key, value in result.items() if key != "payload_sha256"
        }
        if _canonical_json(result_body) != _canonical_json(expected_invalid):
            raise ApparatusFailure("invalid RESULT differs from recomputed partial evidence")
        expected_status = {
            "validity": "INVALID",
            "result_code": "INVALID_APPARATUS",
            "call_artifacts": recomputed_usage["total"]["call_artifacts"],
            "physical_generation_calls": recomputed_usage["total"][
                "physical_generation_calls"
            ],
            "unique_response_ids": len(set(response_ids)),
        }
        if any(status.get(name) != value for name, value in expected_status.items()):
            raise ApparatusFailure("invalid RUN_STATUS differs from partial evidence")

    if validity == "VALID":
        if (
            len(call_paths) != MAX_GENERATION_CALLS
            or len(decision_paths) != MAX_GENERATION_CALLS
        ):
            raise ApparatusFailure("valid run lacks 192 calls or decisions")
        if (
            len(response_ids) != MAX_GENERATION_CALLS
            or len(set(response_ids)) != MAX_GENERATION_CALLS
        ):
            raise ApparatusFailure("valid run response identities are incomplete or reused")
        expected_models = {condition: {MODELS[condition]} for condition in CONDITIONS}
        if returned_models != expected_models:
            raise ApparatusFailure("returned model identities do not match the four arms")
        if returned_tiers != {condition: {"default"} for condition in CONDITIONS}:
            raise ApparatusFailure("returned service tier changed across the factorial run")
        if result["physical_generation_calls"] != MAX_GENERATION_CALLS:
            raise ApparatusFailure("result physical call count is inconsistent")
        recomputed_result = aggregate_valid_result(
            cases=cases,
            scores=recomputed_scores,
            audits={
                condition: SimpleNamespace(records=records_by_condition[condition])
                for condition in CONDITIONS
            },
            preflight=preflight,
        )
        result_body = {
            key: value for key, value in result.items() if key != "payload_sha256"
        }
        if _canonical_json(result_body) != _canonical_json(recomputed_result):
            raise ApparatusFailure("RESULT differs from independent recomputation")
        expected_status = {
            "validity": recomputed_result["validity"],
            "result_code": recomputed_result["result_code"],
            "call_artifacts": MAX_GENERATION_CALLS,
            "physical_generation_calls": MAX_GENERATION_CALLS,
            "unique_response_ids": MAX_GENERATION_CALLS,
        }
        if any(status.get(name) != value for name, value in expected_status.items()):
            raise ApparatusFailure("RUN_STATUS differs from recomputed result")
    return {
        "verified": True,
        "protocol_id": PROTOCOL_ID,
        "validity": result["validity"],
        "result_code": result["result_code"],
        "physical_generation_calls": len(call_paths),
        "decision_artifacts": len(decision_paths),
        "unique_response_ids": len(set(response_ids)),
        "returned_models": {
            condition: sorted(values) for condition, values in returned_models.items()
        },
        "returned_service_tiers": {
            condition: sorted(values) for condition, values in returned_tiers.items()
        },
        "source_revision": index["source_revision"],
        "file_count": index["file_count"],
        "total_bytes": index["total_bytes"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(ACKNOWLEDGEMENT, dest="acknowledge", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--derive-frozen-values", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    if args.verify is not None:
        print(_pretty_json(verify_run(args.verify)), end="")
        return 0
    if args.derive_frozen_values:
        print(_pretty_json(derived_frozen_values(repo_root)), end="")
        return 0
    if not args.acknowledge:
        parser.error(f"{ACKNOWLEDGEMENT} is required")
    frontier._check_live_prerequisites()
    result = FactorialRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(_pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
