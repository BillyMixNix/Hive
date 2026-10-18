"""Frozen system comparison: Luna + Hive C1 versus Sol + Raw.

This experiment changes two things together on purpose: solver and
representation.  It estimates the observed accuracy/cost/latency of the two
complete systems on the frozen 20-world decompression benchmark.  It cannot
attribute any difference to the model or representation independently.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from hive_llm import FrozenSolverConfig, ask_hive
from kingdom import decompression_frontier_luna as frontier
from kingdom import decompression_matched_semantic_control_luna as study3
from kingdom import decompression_semantic_authority_luna as study2
from kingdom import decompression_semantic_authority_luna_v1_2 as audit_helpers
from kingdom import decompression_test as worlds
from kingdom import decompression_test_v2 as grading


PROTOCOL_ID = "hive-luna-c1-vs-sol-raw-v1"
PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = 1
RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/luna-c1-vs-sol-raw-v1-001"
)
ACKNOWLEDGEMENT = "--acknowledge-frozen-luna-c1-vs-sol-raw-v1"

SEALED_PARENT = "c4b368bb4b640ebb592f3ba6b900d18a77e8ce76"
SEALED_STUDY3_RESULT_SHA256 = (
    "4c47b12dbea118603ffc7e87fc2bea6fdda20b1837e46019d05a0183f6ea1236"
)
SEALED_STUDY3_INDEX_SHA256 = (
    "b21257bc11e2d50ed0370ec9eba3832f225f8b105af1414bb53f17afd54021b6"
)
SEALED_STUDY3_DIR = study3.RUN_DIR

LUNA_C1 = "LUNA_C1"
SOL_RAW = "SOL_RAW"
CONDITIONS = (LUNA_C1, SOL_RAW)
MODELS = {LUNA_C1: "gpt-5.6-luna", SOL_RAW: "gpt-5.6-sol"}
REPRESENTATIONS = {LUNA_C1: "C1", SOL_RAW: "raw_capability"}
PRICING_USD_PER_MILLION = {
    LUNA_C1: {"input": 0.20, "output": 1.20},
    SOL_RAW: {"input": 4.00, "output": 20.00},
}

REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 16_384
TIMEOUT_SECONDS = 900
AUTHORIZED_COST_CEILING_USD = 100.0
REPLICATION_COUNT = 6
BATCHES_PER_CONDITION = 6
CASES_PER_CONDITION = 20
CALLS_PER_CONDITION = REPLICATION_COUNT * BATCHES_PER_CONDITION
MAX_GENERATION_CALLS = len(CONDITIONS) * CALLS_PER_CONDITION
TRIALS_PER_CONDITION = REPLICATION_COUNT * CASES_PER_CONDITION
CAPABILITY_WARNING_THRESHOLD = 108  # 90% of 120 fixed answers

MODULE_PATH = "kingdom/decompression_luna_hive_vs_sol_raw.py"
TEST_PATH = "tests/test_decompression_luna_hive_vs_sol_raw.py"
PROTOCOL_PATH = (
    "benchmarks/decompression_test/PROTOCOL_LUNA_C1_VS_SOL_RAW_V1.md"
)
SOURCE_FILES = tuple(
    dict.fromkeys((*study3.SOURCE_FILES, MODULE_PATH, TEST_PATH, PROTOCOL_PATH))
)

# Filled from deterministic derivation before the implementation commit.
FROZEN_SCHEDULE_SHA256 = (
    "c35de200f1373ea4e45c5b600df84d465294a6f85d5eb07b0f02d2ebfb9a90e9"
)
FROZEN_REQUEST_PLAN_SHA256 = (
    "2bf15f65258599219fa3fa1e85e8d58cd31fa3abc8177cee9ae2c80ea546eaec"
)
FROZEN_SOLVER_CONFIG_SHA256 = {
    LUNA_C1: "0fa9c5f438388516fd4ac130c44320f08cafb7bddbad6e102444326c56a04b54",
    SOL_RAW: "04b279997f7f4789a57c4c399622eccefe8f4dbfdf368bec404f1c7bba8f2422",
}
FROZEN_INPUT_TOKEN_UPPER_BOUND = {LUNA_C1: 1_022_052, SOL_RAW: 2_097_168}
FROZEN_COST_UPPER_BOUND_USD = 21.097351200000002

_PRIOR_TITLE = "HIVE LUNA COMPRESSION FRONTIER v1 — FROZEN SOLVER"
_NEUTRAL_TITLE = "HIVE SYSTEM COMPARISON v1 — FROZEN SOLVER"
if not frontier.SOLVER_PROMPT_PREFIX.startswith(_PRIOR_TITLE):
    raise RuntimeError("inherited frozen solver title changed unexpectedly")
NEUTRAL_SOLVER_PROMPT_PREFIX = frontier.SOLVER_PROMPT_PREFIX.replace(
    _PRIOR_TITLE, _NEUTRAL_TITLE, 1
)


class ApparatusFailure(RuntimeError):
    """A protocol, transport, parser, or evidence failure."""


def render_progress(
    completed: int,
    total: int,
    *,
    detail: str = "",
    width: int = 28,
) -> str:
    """Render one deterministic ASCII progress line without touching evidence."""

    if total < 1 or width < 1:
        raise ValueError("progress total and width must be positive")
    if completed < 0 or completed > total:
        raise ValueError("progress completed count is outside the scheduled range")
    filled = completed * width // total
    percent = 100 * completed / total
    suffix = f"  {detail}" if detail else ""
    return (
        f"[{'#' * filled}{'-' * (width - filled)}] "
        f"{completed:>2}/{total}  {percent:5.1f}%{suffix}"
    )


@dataclass(frozen=True)
class PlannedCall:
    global_sequence: int
    local_sequence: int
    replication: int
    condition_position: int
    batch_id: int
    condition: str
    case_ids: tuple[str, ...]
    prompt: str
    text_format: Mapping[str, Any]

    @property
    def stage(self) -> str:
        return f"replication_{self.replication:03d}"

    def audit_call(self) -> frontier.PlannedCall:
        return frontier.PlannedCall(
            sequence=self.local_sequence,
            stage=self.stage,
            batch_id=self.batch_id,
            condition=self.condition,
            case_ids=self.case_ids,
            prompt=self.prompt,
            text_format=self.text_format,
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sealed(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(payload))
    body["payload_sha256"] = _sha256_text(_canonical_json(body))
    return body


def _verify_seal(payload: Mapping[str, Any]) -> None:
    claimed = payload.get("payload_sha256")
    body = {key: value for key, value in payload.items() if key != "payload_sha256"}
    if not isinstance(claimed, str) or claimed != _sha256_text(_canonical_json(body)):
        raise ApparatusFailure("sealed JSON payload hash mismatch")


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
    return NEUTRAL_SOLVER_PROMPT_PREFIX + inherited[len(frontier.SOLVER_PROMPT_PREFIX) :]


def _input_payload_text(prompt: str) -> str:
    marker = "\nINPUT:\n"
    if prompt.count(marker) != 1:
        raise ApparatusFailure("solver prompt input boundary changed")
    return prompt.split(marker, 1)[1]


def condition_schedule() -> tuple[tuple[tuple[str, str], ...], ...]:
    """Six balanced replications; every batch sees both orders equally often."""

    return tuple(
        tuple(
            CONDITIONS
            if (replication_index + batch_index) % 2 == 0
            else tuple(reversed(CONDITIONS))
            for batch_index in range(BATCHES_PER_CONDITION)
        )
        for replication_index in range(REPLICATION_COUNT)
    )


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
            batch_cases = tuple(
                by_case[str(case_id)] for case_id in batch["case_ids"]
            )
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
        raise ApparatusFailure("call plan does not contain exactly 72 calls")
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


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
    )


def verify_sealed_parent(repo_root: Path) -> Mapping[str, Any]:
    resolved = _git(repo_root, "rev-parse", f"{SEALED_PARENT}^{{commit}}").stdout.strip()
    if resolved != SEALED_PARENT:
        raise ApparatusFailure("sealed Experiment-3 parent did not resolve exactly")
    current = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if _git(
        repo_root, "merge-base", "--is-ancestor", SEALED_PARENT, current, check=False
    ).returncode != 0:
        raise ApparatusFailure("current source does not descend from sealed Experiment 3")
    result_path = repo_root / SEALED_STUDY3_DIR / "RESULT.json"
    index_path = repo_root / SEALED_STUDY3_DIR / "EVIDENCE_INDEX.json"
    if (
        _sha256_bytes(result_path.read_bytes()) != SEALED_STUDY3_RESULT_SHA256
        or _sha256_bytes(index_path.read_bytes()) != SEALED_STUDY3_INDEX_SHA256
    ):
        raise ApparatusFailure("sealed Experiment-3 evidence hashes changed")
    verified = study3.verify_run(repo_root / SEALED_STUDY3_DIR)
    if (
        verified["validity"] != "VALID"
        or verified["physical_generation_calls"] != 144
        or verified["unique_response_ids"] != 144
        or verified["returned_models"] != ["gpt-5.6-luna"]
    ):
        raise ApparatusFailure("sealed Experiment-3 evidence no longer verifies")
    return {
        "sealed_parent": SEALED_PARENT,
        "current_revision": current,
        "study3_result_sha256": SEALED_STUDY3_RESULT_SHA256,
        "study3_evidence_index_sha256": SEALED_STUDY3_INDEX_SHA256,
        "study3_verification": verified,
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


def _prior_prompt_map(repo_root: Path) -> Mapping[tuple[str, int], str]:
    calls_dir = repo_root / study2.SEALED_V1_3_DIR / "replicate-001" / "calls"
    result: dict[tuple[str, int], str] = {}
    for path in sorted(calls_dir.glob("call_*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        condition = artifact.get("condition")
        if condition not in {"raw_capability", "C1"}:
            continue
        key = (str(condition), int(artifact["batch_id"]))
        if key in result:
            raise ApparatusFailure("sealed prior prompt identity is duplicated")
        result[key] = str(artifact["request"]["prompt"])
    expected = {
        (condition, batch_id)
        for condition in ("raw_capability", "C1")
        for batch_id in range(1, BATCHES_PER_CONDITION + 1)
    }
    if set(result) != expected:
        raise ApparatusFailure("sealed prior Raw/C1 prompt set is incomplete")
    return result


def _load_frozen_cases(
    repo_root: Path,
) -> tuple[Mapping[str, Any], tuple[worlds.BenchmarkCase, ...]]:
    case_path = repo_root / "benchmarks/decompression_test/CASE_PACK.json"
    if _sha256_bytes(case_path.read_bytes()) != frontier.FROZEN_CASE_PACK_SHA256:
        raise ApparatusFailure("frozen CASE_PACK.json changed")
    payload, cases = worlds.load_case_pack(case_path)
    worlds.validate_case_pack(payload, cases)
    if frontier._expanded_pack_hash(cases) != frontier.FROZEN_EXPANDED_PACK_SHA256:
        raise ApparatusFailure("expanded frozen worlds changed")
    return payload, cases


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
            for position in (1, 2)
        }
        for condition in CONDITIONS
    }
    if any(counts != {"1": 18, "2": 18} for counts in position_counts.values()):
        raise ApparatusFailure("condition order is not exactly counterbalanced")

    prior_prompts = _prior_prompt_map(repo_root)
    input_upper = {condition: 0 for condition in CONDITIONS}
    request_rows = []
    for call in calls:
        prior_condition = REPRESENTATIONS[call.condition]
        prior_prompt = prior_prompts[(prior_condition, call.batch_id)]
        if _input_payload_text(call.prompt) != _input_payload_text(prior_prompt):
            raise ApparatusFailure(
                f"{call.condition} input payload is not byte-identical to its sealed input"
            )
        if call.prompt.split("\n", 1)[1] != prior_prompt.split("\n", 1)[1]:
            raise ApparatusFailure("more than the shared solver title changed from v1.3")
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
                "case_ids": list(call.case_ids),
                "prompt_sha256": _sha256_text(call.prompt),
                "prompt_utf8_bytes": len(call.prompt.encode("utf-8")),
                "text_format_sha256": _sha256_text(_canonical_json(call.text_format)),
                "solver_config_sha256": solver_config(call.condition).configuration_hash,
                "request_sha256": _sha256_text(canonical_request),
                "conservative_input_token_upper_bound": byte_upper,
            }
        )

    for replication in range(1, REPLICATION_COUNT + 1):
        selected = [call for call in calls if call.replication == replication]
        if len(selected) != 12:
            raise ApparatusFailure("replication does not contain exactly 12 calls")
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
        raise ApparatusFailure("conservative cost upper bound exceeds $100")

    state_bytes = {
        SOL_RAW: sum(
            len(_canonical_json(worlds.raw_packet(case)).encode("utf-8"))
            for case in cases
        ),
        LUNA_C1: sum(
            len(
                _canonical_json(
                    frontier.transform_compact_packet(
                        worlds.compressed_packet(case), "C1"
                    )
                ).encode("utf-8")
            )
            for case in cases
        ),
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
            "solver_prompt_template_sha256": _sha256_text(NEUTRAL_SOLVER_PROMPT_PREFIX),
            "solver_title_change_from_sealed_v1_3": {
                "prior": _PRIOR_TITLE,
                "current_shared_neutral_title": _NEUTRAL_TITLE,
                "only_first_line_changed": True,
                "reason": "avoid naming Luna inside the prompt shown to Sol",
            },
            "conditions": {
                LUNA_C1: {
                    "model": MODELS[LUNA_C1],
                    "representation": "compact C1 semantic ledger",
                    "columns": list(frontier.LEVEL_COLUMNS["C1"]),
                },
                SOL_RAW: {
                    "model": MODELS[SOL_RAW],
                    "representation": "full verbose authoritative history",
                },
            },
            "solver_configs": {
                condition: solver_config(condition).to_mapping()
                for condition in CONDITIONS
            },
            "solver_config_sha256": config_hashes,
            "intentional_differences": ["model", "representation"],
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
                LUNA_C1: True,
                SOL_RAW: True,
            },
            "estimand": (
                "Observed accuracy, API token cost, and latency of Luna+C1 versus "
                "Sol+Raw on these fixed 20 worlds under repeated stochastic inference."
            ),
            "causal_claim_boundary": (
                "This joint system comparison cannot attribute differences separately "
                "to solver or representation."
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
            "ordinal_position_counts": position_counts,
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
                "primary_difference": "LUNA_C1_correct_minus_SOL_RAW_correct_out_of_20",
                "test": "exact_two_sided_replication_sign_flip_2^6",
                "alpha": 0.05,
                "non_rejection_is_equivalence": False,
                "case_rows_are_not_independent_inferential_samples": True,
            },
            "frozen_interpretation": {
                "either_arm_below_90_percent": "VALID_CAPABILITY_WARNING",
                "equal_aggregate_accuracy": "VALID_OBSERVED_ACCURACY_TIE",
                "luna_c1_higher": "VALID_OBSERVED_LUNA_HIVE_HIGHER_ACCURACY",
                "sol_raw_higher": "VALID_OBSERVED_SOL_RAW_HIGHER_ACCURACY",
                "any_apparatus_failure": "INVALID_APPARATUS",
                "accuracy_tie_does_not_prove_equivalence": True,
                "cost_and_latency_are_descriptive_system_metrics": True,
            },
            "cost": {
                "pricing_usd_per_million": PRICING_USD_PER_MILLION,
                "request_utf8_bytes_input_token_upper_bound": input_upper,
                "output_token_upper_bound": output_upper,
                "condition_cost_upper_bound_usd": cost_upper_by_condition,
                "conservative_generation_cost_upper_bound_usd": cost_upper,
                "authorized_cost_ceiling_usd": AUTHORIZED_COST_CEILING_USD,
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
        raise ValueError("exact sign-flip test requires six replication differences")
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
        "non_rejection_is_equivalence": False,
    }


def _measured_int(metadata: Mapping[str, Any], name: str) -> int:
    value = metadata.get(name)
    return value if type(value) is int and value >= 0 else 0


def _measured_float(metadata: Mapping[str, Any], name: str) -> float:
    value = metadata.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _usage(
    audits: Mapping[str, frontier.OpenAIAuditStore]
) -> Mapping[str, Any]:
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


def aggregate_valid_result(
    *,
    cases: Sequence[worlds.BenchmarkCase],
    scores: Mapping[int, Mapping[str, Sequence[grading.LabelScore]]],
    audits: Mapping[str, frontier.OpenAIAuditStore],
    preflight: Mapping[str, Any],
) -> Mapping[str, Any]:
    by_case = {case.case_id: case for case in cases}
    vectors = {condition: [] for condition in CONDITIONS}
    replication_scores: dict[str, Mapping[str, int]] = {}
    for replication in range(1, REPLICATION_COUNT + 1):
        row: dict[str, int] = {}
        for condition in CONDITIONS:
            selected = list(scores[replication][condition])
            if (
                len(selected) != CASES_PER_CONDITION
                or len({score.case_id for score in selected}) != CASES_PER_CONDITION
            ):
                raise ApparatusFailure("replication is not one complete 20-world pair")
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

    differences = [
        luna - sol
        for luna, sol in zip(vectors[LUNA_C1], vectors[SOL_RAW])
    ]
    comparison = {
        **exact_two_sided_sign_flip(differences),
        "comparison_id": "LUNA_C1_VS_SOL_RAW",
        "left": LUNA_C1,
        "right": SOL_RAW,
        "left_scores": list(vectors[LUNA_C1]),
        "right_scores": list(vectors[SOL_RAW]),
        "difference_definition": "LUNA_C1_correct_minus_SOL_RAW_correct_out_of_20",
        "mean_difference_answers_out_of_20": sum(differences) / REPLICATION_COUNT,
        "aggregate_difference_answers_out_of_120": sum(differences),
        "alpha": 0.05,
    }

    if any(totals[condition] < CAPABILITY_WARNING_THRESHOLD for condition in CONDITIONS):
        result_code = "VALID_CAPABILITY_WARNING"
    elif totals[LUNA_C1] == totals[SOL_RAW]:
        result_code = "VALID_OBSERVED_ACCURACY_TIE"
    elif totals[LUNA_C1] > totals[SOL_RAW]:
        result_code = "VALID_OBSERVED_LUNA_HIVE_HIGHER_ACCURACY"
    else:
        result_code = "VALID_OBSERVED_SOL_RAW_HIGHER_ACCURACY"

    usage = _usage(audits)
    luna_usage = usage["by_condition"][LUNA_C1]
    sol_usage = usage["by_condition"][SOL_RAW]
    state = preflight["representation_utf8_bytes_per_20_world_replication"]
    system_efficiency = {
        "luna_c1_state_bytes_percentage_of_sol_raw": 100
        * state[LUNA_C1]
        / state[SOL_RAW],
        "luna_c1_input_tokens_percentage_of_sol_raw": 100
        * luna_usage["input_tokens"]
        / sol_usage["input_tokens"],
        "luna_c1_cost_percentage_of_sol_raw": 100
        * luna_usage["estimated_generation_cost_usd"]
        / sol_usage["estimated_generation_cost_usd"],
        "luna_c1_latency_percentage_of_sol_raw": 100
        * luna_usage["latency_seconds"]
        / sol_usage["latency_seconds"],
        "observed_accuracy_noninferiority_is_not_established": True,
        "joint_system_comparison_not_causal_attribution": True,
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
        "evidence_label": "OBSERVED_BENCHMARK_RESULT",
        "estimand": preflight["estimand"],
        "replication_count": REPLICATION_COUNT,
        "fixed_world_count": CASES_PER_CONDITION,
        "replication_scores": replication_scores,
        "conditions": summaries,
        "primary_comparison": comparison,
        "representation_utf8_bytes_per_20_world_replication": state,
        "usage": usage,
        "system_efficiency": system_efficiency,
        "returned_models": returned_models,
        "returned_service_tiers": returned_tiers,
        "physical_generation_calls": usage["total"]["physical_generation_calls"],
        "unique_response_ids": MAX_GENERATION_CALLS,
        "claim_boundary": preflight["causal_claim_boundary"],
        "non_claims": [
            "No representation-only effect is identified.",
            "No model-only effect is identified.",
            "An observed tie is not proof of statistical equivalence.",
            "No claim extends beyond this fixed benchmark and frozen configuration.",
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


class ComparisonRunner:
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
            # Presentation must never change experimental validity.
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
            "apparatus_failure": study2._safe_reason(exc),
            "partial_score_counts": {
                str(replication): {
                    condition: len(self.scores[replication][condition])
                    for condition in CONDITIONS
                }
                for replication in range(1, REPLICATION_COUNT + 1)
            },
            "usage": _usage(self.audits),
            "evidence_interpretation": "No Luna+C1 versus Sol+Raw claim is licensed.",
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
            "mission": "system comparison of Luna+C1 and Sol+Raw",
            "conditions": list(CONDITIONS),
            "replications": REPLICATION_COUNT,
            "scheduled_calls": MAX_GENERATION_CALLS,
            "schedule_sha256": FROZEN_SCHEDULE_SHA256,
            "request_plan_sha256": FROZEN_REQUEST_PLAN_SHA256,
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
    if not source_revision or source_revision == "TEST_UNCOMMITTED":
        source_check_required = source_revision != "TEST_UNCOMMITTED"
    else:
        source_check_required = True
    if source_check_required:
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

    indexed = {str(row["path"]): row for row in index["files"]}
    actual = {
        path.relative_to(run_dir).as_posix(): path
        for path in run_dir.rglob("*")
        if path.is_file() and path.name != "EVIDENCE_INDEX.json"
    }
    if set(indexed) != set(actual):
        raise ApparatusFailure("evidence index file set differs from disk")
    for relative, path in actual.items():
        row = indexed[relative]
        if row["bytes"] != path.stat().st_size or row["sha256"] != _sha256_bytes(path.read_bytes()):
            raise ApparatusFailure(f"evidence index mismatch for {relative}")
    call_paths = sorted(run_dir.glob("*/calls/call_*.json"))
    decision_paths = sorted(run_dir.glob("*/decisions/decision_*.json"))
    response_ids = []
    returned_models: dict[str, set[str]] = {condition: set() for condition in CONDITIONS}
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

    if result["validity"] != "VALID":
        for path in call_paths:
            call = json.loads(path.read_text(encoding="utf-8"))
            _verify_seal(call)
            condition = str(call.get("condition", ""))
            if condition not in CONDITIONS:
                raise ApparatusFailure("invalid run contains an unknown condition")
            metadata = call.get("transport_metadata", {})
            if not isinstance(metadata, Mapping):
                raise ApparatusFailure("invalid run call metadata is malformed")
            response_id = metadata.get("response_id")
            if isinstance(response_id, str) and response_id:
                response_ids.append(response_id)
            returned_model = metadata.get("returned_model")
            if isinstance(returned_model, str) and returned_model:
                returned_models[condition].add(returned_model)
        for path in decision_paths:
            _verify_seal(json.loads(path.read_text(encoding="utf-8")))

    calls_to_recompute = expected_calls if result["validity"] == "VALID" else ()
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
        labels = frontier.parse_structured_labels(raw_text, len(planned.case_ids))
        generated = [
            grading.grade_label(
                by_case[case_id], label, condition=planned.condition
            )
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

    if result["validity"] == "VALID":
        if len(call_paths) != MAX_GENERATION_CALLS or len(decision_paths) != MAX_GENERATION_CALLS:
            raise ApparatusFailure("valid run lacks 72 calls or decisions")
        if len(response_ids) != MAX_GENERATION_CALLS or len(set(response_ids)) != MAX_GENERATION_CALLS:
            raise ApparatusFailure("valid run response identities are incomplete or reused")
        if returned_models != {
            LUNA_C1: {MODELS[LUNA_C1]},
            SOL_RAW: {MODELS[SOL_RAW]},
        }:
            raise ApparatusFailure("returned model identities do not match the two arms")
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
    result = ComparisonRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(_pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
