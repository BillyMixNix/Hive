"""Hive Experiment 2: frozen Luna semantic-authority decomposition.

This protocol starts from the sealed C1 packet and mechanically deletes every
combination of ``kind``, ``authority``, and ``status``.  It executes eight
counterbalanced stochastic replications over the frozen 20-world benchmark.
"""

from __future__ import annotations

import argparse
import copy
import inspect
import itertools
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hive_llm import FrozenSolverConfig, ask_hive
from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_frontier_luna_v1_3 as luna_v1_3
from kingdom import decompression_test as worlds
from kingdom import decompression_test_v2 as grading


PROTOCOL_ID = "hive-luna-semantic-authority-decomposition-v1"
PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = 1

SEALED_PARENT = "7b13c99c237315fb6a6330f3607c3591edeaa9c5"
SEALED_IMPLEMENTATION_PARENT = "a87e54e1af7960dfb67d55c3f4e6c818bc28983f"
SEALED_V1_3_RESULT_SHA256 = (
    "d709bb64c99fdb970492ce405cdf754d4d72e20615d9bd2de247b2d9b45dc0c0"
)
SEALED_V1_3_INDEX_SHA256 = (
    "7657796fb964d2fcd9ecfa5d97c2be7d3aa4cb7ea68f164ed81e6d073325a7e2"
)
SEALED_V1_3_DIR = Path(
    ".hive/benchmarks/decompression_test/luna-frontier-v1-3-001"
)
RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/luna-semantic-authority-decomposition-v1-001"
)

MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 2_048
TIMEOUT_SECONDS = 900
EXPECTED_OPENAI_SDK = luna_v1.EXPECTED_OPENAI_SDK
AUTHORIZED_COST_CEILING_USD = 100.00
INPUT_USD_PER_MILLION = luna_v1.INPUT_USD_PER_MILLION
OUTPUT_USD_PER_MILLION = luna_v1.OUTPUT_USD_PER_MILLION

REPLICATION_COUNT = 8
BATCHES_PER_CONDITION = 6
CONDITIONS = ("C1", "K-", "A-", "S-", "KA-", "KS-", "AS-", "KAS-")
CALLS_PER_REPLICATION = len(CONDITIONS) * BATCHES_PER_CONDITION
MAX_GENERATION_CALLS = REPLICATION_COUNT * CALLS_PER_REPLICATION
CASES_PER_CONDITION = 20
TRIALS_PER_CONDITION = REPLICATION_COUNT * CASES_PER_CONDITION
BASELINE_STABILITY_MIN_CORRECT = 144

C1_COLUMNS = (
    "ref",
    "effective_t",
    "kind",
    "authority",
    "status",
    "requires",
    "effects",
)
DELETED_COLUMNS = {
    "C1": (),
    "K-": ("kind",),
    "A-": ("authority",),
    "S-": ("status",),
    "KA-": ("kind", "authority"),
    "KS-": ("kind", "status"),
    "AS-": ("authority", "status"),
    "KAS-": ("kind", "authority", "status"),
}
CONDITION_COLUMNS = {
    condition: tuple(name for name in C1_COLUMNS if name not in deleted)
    for condition, deleted in DELETED_COLUMNS.items()
}

# Even-order Williams square.  Every condition occupies every ordinal once;
# the schedule is a frozen input and never depends on outputs.
CONDITION_SCHEDULE = (
    ("C1", "K-", "KAS-", "A-", "AS-", "S-", "KS-", "KA-"),
    ("K-", "A-", "C1", "S-", "KAS-", "KA-", "AS-", "KS-"),
    ("A-", "S-", "K-", "KA-", "C1", "KS-", "KAS-", "AS-"),
    ("S-", "KA-", "A-", "KS-", "K-", "AS-", "C1", "KAS-"),
    ("KA-", "KS-", "S-", "AS-", "A-", "KAS-", "K-", "C1"),
    ("KS-", "AS-", "KA-", "KAS-", "S-", "C1", "A-", "K-"),
    ("AS-", "KAS-", "KS-", "C1", "KA-", "K-", "S-", "A-"),
    ("KAS-", "C1", "AS-", "K-", "KS-", "A-", "KA-", "S-"),
)
FROZEN_SCHEDULE_SHA256 = (
    "9b411628e56d291a26b5a0e44bca54577484957b26adc945f38199fabce596cd"
)
FROZEN_REQUEST_PLAN_SHA256 = (
    "29706dd5d1361f0bdf66a48b58cd00c453850740f740046c169847069a5e6640"
)

PRIOR_C2_MINUS_C1_VECTOR = (-17, -17, -17, -16, -17, -17)
PRIMARY_COMPARISONS = {
    "H_KIND": "K-",
    "H_AUTHORITY": "A-",
    "H_STATUS": "S-",
}
SECONDARY_INTERACTIONS = ("I_KA", "I_KS", "I_AS", "I_KAS")

SOURCE_FILES = tuple(
    dict.fromkeys(
        (
            *luna_v1_3.SOURCE_FILES,
            "kingdom/decompression_semantic_authority_luna.py",
            "benchmarks/decompression_test/PROTOCOL_SEMANTIC_AUTHORITY_LUNA_V1.md",
            "tests/test_decompression_semantic_authority_luna.py",
        )
    )
)


@dataclass(frozen=True)
class ExperimentCall:
    sequence: int
    replication: int
    condition_position: int
    stage: str
    batch_id: int
    condition: str
    case_ids: tuple[str, ...]
    prompt: str
    text_format: Mapping[str, Any]


def solver_config() -> FrozenSolverConfig:
    """Return the exact Experiment-2 solver contract.

    The explicit Experiment-2 allowance is 2,048.  The sealed v1.3 study used
    4,096; this intentional difference is disclosed in the protocol/precheck.
    """

    return FrozenSolverConfig(
        model=MODEL,
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


def project_c1_packet(packet: Mapping[str, Any], condition: str) -> dict[str, Any]:
    """Delete only the condition's named columns from an exact C1 packet.

    This function is deliberately unable to receive a case, question, option,
    oracle, reference role, or prior output.
    """

    if condition not in CONDITIONS:
        raise ValueError(f"unknown semantic-decomposition condition {condition!r}")
    if set(packet) != {"format", "record_columns", "records"}:
        raise ValueError("C1 source packet has missing or unknown fields")
    if packet["format"] != "compact_named_columns_frontier_v1":
        raise ValueError("C1 source packet format changed")
    source_columns = tuple(packet["record_columns"])
    if source_columns != C1_COLUMNS:
        raise ValueError("semantic decomposition must start from exact C1 columns")
    retained = CONDITION_COLUMNS[condition]
    indexes = tuple(source_columns.index(name) for name in retained)
    source_records = packet["records"]
    if not isinstance(source_records, list) or not source_records:
        raise ValueError("C1 records must be a nonempty list")
    projected = {
        "format": "compact_named_columns_frontier_v1",
        "record_columns": list(retained),
        "records": [
            [copy.deepcopy(record[index]) for index in indexes]
            for record in source_records
        ],
    }
    validate_projection(projected, condition=condition)
    return projected


def validate_projection(packet: Mapping[str, Any], *, condition: str) -> None:
    if condition not in CONDITIONS:
        raise ValueError("condition identifier is not canonical")
    if set(packet) != {"format", "record_columns", "records"}:
        raise ValueError("projected packet has missing or unknown fields")
    if packet["format"] != "compact_named_columns_frontier_v1":
        raise ValueError("projected packet format mismatch")
    columns = tuple(packet["record_columns"])
    if columns != CONDITION_COLUMNS[condition]:
        raise ValueError("projected columns do not match the frozen condition")
    records = packet["records"]
    if not isinstance(records, list) or not records:
        raise ValueError("projected records must be a nonempty list")
    seen_refs: set[str] = set()
    for record in records:
        if not isinstance(record, list) or len(record) != len(columns):
            raise ValueError("projected record width differs from named columns")
        row = dict(zip(columns, record))
        ref = row.get("ref")
        if not isinstance(ref, str) or not ref or ref in seen_refs:
            raise ValueError("projected references must be unique nonempty strings")
        seen_refs.add(ref)
        if not isinstance(row.get("effective_t"), int):
            raise ValueError("projected effective time must be an integer")
        if "kind" in row and row["kind"] not in set(worlds._KIND_CODES.values()):
            raise ValueError("projected kind code is invalid")
        if "authority" in row and row["authority"] not in set(
            worlds._AUTHORITY_CODES.values()
        ):
            raise ValueError("projected authority code is invalid")
        if "status" in row and row["status"] not in set(
            worlds._STATUS_CODES.values()
        ):
            raise ValueError("projected status code is invalid")
        for name in ("requires", "effects"):
            atoms = row.get(name)
            if not isinstance(atoms, list) or any(
                not isinstance(atom, list) or len(atom) != 3 for atom in atoms
            ):
                raise ValueError(f"projected {name} atoms are invalid")


def _c1_packet(case: worlds.BenchmarkCase) -> dict[str, Any]:
    return luna_v1.transform_compact_packet(worlds.compressed_packet(case), "C1")


def _case_payload(case: worlds.BenchmarkCase, condition: str) -> dict[str, Any]:
    item = worlds._case_prompt_payload(case, "compressed")
    item["representation"] = project_c1_packet(_c1_packet(case), condition)
    return item


def build_solver_prompt(cases: Sequence[worlds.BenchmarkCase], condition: str) -> str:
    payload = {
        "representation_family": "compact_named_column_records",
        "cases": [_case_payload(case, condition) for case in cases],
    }
    return luna_v1.SOLVER_PROMPT_PREFIX + "\nINPUT:\n" + luna_v1._pretty_json(payload)


def _request_payload(call: ExperimentCall, config: FrozenSolverConfig) -> dict[str, Any]:
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


def build_call_plan(
    payload: Mapping[str, Any], cases: Sequence[worlds.BenchmarkCase]
) -> tuple[ExperimentCall, ...]:
    by_case = {case.case_id: case for case in cases}
    calls: list[ExperimentCall] = []
    sequence = 1
    for replication, condition_order in enumerate(CONDITION_SCHEDULE, start=1):
        for batch in payload["batches"]:
            for position, condition in enumerate(condition_order, start=1):
                batch_cases = tuple(
                    by_case[str(case_id)] for case_id in batch["case_ids"]
                )
                calls.append(
                    ExperimentCall(
                        sequence=sequence,
                        replication=replication,
                        condition_position=position,
                        stage=f"replication_{replication:03d}",
                        batch_id=int(batch["batch_id"]),
                        condition=condition,
                        case_ids=tuple(case.case_id for case in batch_cases),
                        prompt=build_solver_prompt(batch_cases, condition),
                        text_format=luna_v1.openai_text_format(len(batch_cases)),
                    )
                )
                sequence += 1
    if len(calls) != MAX_GENERATION_CALLS:
        raise luna_v1.ApparatusFailure("call plan is not exactly 384 calls")
    return tuple(calls)


def _run_git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
    )


def verify_sealed_parent(repo_root: Path) -> Mapping[str, Any]:
    try:
        resolved_parent = _run_git(repo_root, "rev-parse", f"{SEALED_PARENT}^{{commit}}")
        resolved_impl = _run_git(
            repo_root, "rev-parse", f"{SEALED_IMPLEMENTATION_PARENT}^{{commit}}"
        )
    except subprocess.CalledProcessError as exc:
        raise luna_v1.ApparatusFailure("sealed parent commit cannot be resolved") from exc
    if resolved_parent.stdout.strip() != SEALED_PARENT:
        raise luna_v1.ApparatusFailure("sealed parent resolved to an unexpected commit")
    if resolved_impl.stdout.strip() != SEALED_IMPLEMENTATION_PARENT:
        raise luna_v1.ApparatusFailure(
            "sealed implementation parent resolved to an unexpected commit"
        )
    parent_line = _run_git(repo_root, "show", "-s", "--format=%P", SEALED_PARENT)
    if parent_line.stdout.strip().split() != [SEALED_IMPLEMENTATION_PARENT]:
        raise luna_v1.ApparatusFailure(
            "sealed evidence commit does not have the expected implementation parent"
        )
    current = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    ancestor = _run_git(
        repo_root, "merge-base", "--is-ancestor", SEALED_PARENT, current, check=False
    )
    if ancestor.returncode != 0:
        raise luna_v1.ApparatusFailure("current source does not descend from sealed parent")
    sealed_dir = repo_root / SEALED_V1_3_DIR
    result_path = sealed_dir / "RESULT.json"
    index_path = sealed_dir / "EVIDENCE_INDEX.json"
    if (
        not result_path.is_file()
        or luna_v1._sha256_bytes(result_path.read_bytes())
        != SEALED_V1_3_RESULT_SHA256
        or not index_path.is_file()
        or luna_v1._sha256_bytes(index_path.read_bytes())
        != SEALED_V1_3_INDEX_SHA256
    ):
        raise luna_v1.ApparatusFailure("sealed v1.3 root evidence hashes changed")
    verified = luna_v1_3.verify_run(sealed_dir)
    if (
        verified["validity"] != "VALID"
        or verified["physical_generation_calls"] != 144
        or verified["unique_response_ids"] != 144
        or verified["source_revision"] != SEALED_IMPLEMENTATION_PARENT
    ):
        raise luna_v1.ApparatusFailure("sealed v1.3 evidence verification failed")
    return {
        "sealed_parent": SEALED_PARENT,
        "sealed_implementation_parent": SEALED_IMPLEMENTATION_PARENT,
        "current_revision": current,
        "v1_3_result_sha256": SEALED_V1_3_RESULT_SHA256,
        "v1_3_evidence_index_sha256": SEALED_V1_3_INDEX_SHA256,
        "v1_3_verification": verified,
    }


def _git_revision_and_sources(repo_root: Path) -> tuple[str, dict[str, str]]:
    revision = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    hashes: dict[str, str] = {}
    for relative in SOURCE_FILES:
        tracked = _run_git(
            repo_root, "ls-files", "--error-unmatch", "--", relative, check=False
        )
        if tracked.returncode != 0:
            raise luna_v1.ApparatusFailure(f"experiment source is not committed: {relative}")
        head_object = _run_git(repo_root, "rev-parse", f"HEAD:{relative}").stdout.strip()
        working_object = _run_git(
            repo_root, "hash-object", "--path", relative, "--", relative
        ).stdout.strip()
        if working_object != head_object:
            raise luna_v1.ApparatusFailure(
                f"experiment source differs from HEAD: {relative}"
            )
        content = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        hashes[relative] = luna_v1._sha256_bytes(content)
    return revision, dict(sorted(hashes.items()))


def _prior_prompt_map(repo_root: Path) -> Mapping[tuple[str, int], str]:
    calls_dir = repo_root / SEALED_V1_3_DIR / "replicate-001" / "calls"
    result: dict[tuple[str, int], str] = {}
    for path in sorted(calls_dir.glob("call_*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact.get("condition") not in {"C1", "C2"}:
            continue
        key = (str(artifact["condition"]), int(artifact["batch_id"]))
        if key in result:
            raise luna_v1.ApparatusFailure("prior C1/C2 prompt identity is duplicated")
        result[key] = str(artifact["request"]["prompt"])
    if set(result) != {
        (condition, batch_id)
        for condition in ("C1", "C2")
        for batch_id in range(1, BATCHES_PER_CONDITION + 1)
    }:
        raise luna_v1.ApparatusFailure("prior C1/C2 prompt set is incomplete")
    return result


def _verify_projection_source_contract() -> Mapping[str, Any]:
    signature = inspect.signature(project_c1_packet)
    if tuple(signature.parameters) != ("packet", "condition"):
        raise luna_v1.ApparatusFailure("projection function gained a leakage input")
    forbidden = {
        "question",
        "options",
        "oracle",
        "correct_choice",
        "required_references",
        "error_category",
        "event_role",
        "decoy",
        "model_output",
    }
    referenced = set(project_c1_packet.__code__.co_names) | set(
        project_c1_packet.__code__.co_varnames
    )
    leaked = sorted(forbidden & referenced)
    if leaked:
        raise luna_v1.ApparatusFailure(
            f"projection implementation references forbidden inputs: {leaked}"
        )
    source = inspect.getsource(project_c1_packet)
    return {
        "callable_parameters": list(signature.parameters),
        "forbidden_identifiers_absent": True,
        "source_sha256": luna_v1._sha256_text(source),
    }


def _prior_c2_minus_c1_vector(repo_root: Path) -> tuple[int, ...]:
    result = []
    for replication in range(1, 7):
        path = (
            repo_root
            / SEALED_V1_3_DIR
            / f"replicate-{replication:03d}"
            / "RESULT.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        result.append(
            int(payload["frontier"]["C2"]["exact_correct"])
            - int(payload["frontier"]["C1"]["exact_correct"])
        )
    vector = tuple(result)
    if vector != PRIOR_C2_MINUS_C1_VECTOR:
        raise luna_v1.ApparatusFailure("sealed prior C2-C1 behavior changed")
    return vector


def deterministic_preflight(
    repo_root: Path, *, require_committed: bool = True
) -> tuple[
    Mapping[str, Any],
    tuple[worlds.BenchmarkCase, ...],
    tuple[ExperimentCall, ...],
    Mapping[str, Any],
]:
    lineage = verify_sealed_parent(repo_root)
    case_path = repo_root / "benchmarks/decompression_test/CASE_PACK.json"
    if luna_v1._sha256_bytes(case_path.read_bytes()) != luna_v1.FROZEN_CASE_PACK_SHA256:
        raise luna_v1.ApparatusFailure("frozen CASE_PACK.json changed")
    payload, cases = worlds.load_case_pack(case_path)
    worlds.validate_case_pack(payload, cases)
    expanded_hash = luna_v1._expanded_pack_hash(cases)
    if expanded_hash != luna_v1.FROZEN_EXPANDED_PACK_SHA256:
        raise luna_v1.ApparatusFailure("expanded frozen worlds changed")
    if len(payload["batches"]) != BATCHES_PER_CONDITION:
        raise luna_v1.ApparatusFailure("frozen benchmark no longer has six batches")

    schedule_hash = luna_v1._sha256_text(luna_v1._canonical_json(CONDITION_SCHEDULE))
    if schedule_hash != FROZEN_SCHEDULE_SHA256:
        raise luna_v1.ApparatusFailure("condition schedule hash drifted")
    if any(set(row) != set(CONDITIONS) or len(row) != len(CONDITIONS) for row in CONDITION_SCHEDULE):
        raise luna_v1.ApparatusFailure("a schedule row is not one permutation")
    if any(
        {CONDITION_SCHEDULE[row][position] for row in range(REPLICATION_COUNT)}
        != set(CONDITIONS)
        for position in range(len(CONDITIONS))
    ):
        raise luna_v1.ApparatusFailure(
            "conditions do not occupy every ordinal position exactly once"
        )

    projection_contract = _verify_projection_source_contract()
    prior_prompts = _prior_prompt_map(repo_root)
    representation_by_case: dict[str, dict[str, int]] = {}
    for case in cases:
        source = _c1_packet(case)
        source_before = copy.deepcopy(source)
        representation_by_case[case.case_id] = {}
        for condition in CONDITIONS:
            projected = project_c1_packet(source, condition)
            if source != source_before:
                raise luna_v1.ApparatusFailure("projection mutated its C1 input")
            expected_columns = CONDITION_COLUMNS[condition]
            indexes = tuple(C1_COLUMNS.index(name) for name in expected_columns)
            expected_records = [
                [copy.deepcopy(record[index]) for index in indexes]
                for record in source["records"]
            ]
            if projected["records"] != expected_records:
                raise luna_v1.ApparatusFailure("projection is not pure column deletion")
            representation_by_case[case.case_id][condition] = len(
                luna_v1._canonical_json(projected).encode("utf-8")
            )

    calls = build_call_plan(payload, cases)
    config = solver_config()
    request_rows = []
    input_upper = 0
    for call in calls:
        request = _request_payload(call, config)
        canonical_request = luna_v1._canonical_json(request)
        byte_upper = len(canonical_request.encode("utf-8"))
        input_upper += byte_upper
        request_rows.append(
            {
                "sequence": call.sequence,
                "replication": call.replication,
                "condition_position": call.condition_position,
                "stage": call.stage,
                "batch_id": call.batch_id,
                "condition": call.condition,
                "case_ids": list(call.case_ids),
                "prompt_sha256": luna_v1._sha256_text(call.prompt),
                "prompt_utf8_bytes": len(call.prompt.encode("utf-8")),
                "text_format_sha256": luna_v1._sha256_text(
                    luna_v1._canonical_json(call.text_format)
                ),
                "request_sha256": luna_v1._sha256_text(canonical_request),
                "conservative_input_token_upper_bound": byte_upper,
            }
        )
        prior_condition = "C1" if call.condition == "C1" else "C2" if call.condition == "KAS-" else None
        if prior_condition is not None and call.prompt != prior_prompts[(prior_condition, call.batch_id)]:
            raise luna_v1.ApparatusFailure(
                f"{call.condition} prompt is not byte-equivalent to prior {prior_condition}"
            )
    plan_hash = luna_v1._sha256_text(luna_v1._canonical_json(request_rows))
    if plan_hash != FROZEN_REQUEST_PLAN_SHA256:
        raise luna_v1.ApparatusFailure("request plan hash drifted")

    for replication in range(1, REPLICATION_COUNT + 1):
        selected = [call for call in calls if call.replication == replication]
        if len(selected) != CALLS_PER_REPLICATION:
            raise luna_v1.ApparatusFailure("replication does not have exactly 48 calls")
        for condition in CONDITIONS:
            condition_calls = [call for call in selected if call.condition == condition]
            if [call.batch_id for call in condition_calls] != list(
                range(1, BATCHES_PER_CONDITION + 1)
            ):
                raise luna_v1.ApparatusFailure(
                    "within-condition frozen batch order changed"
                )
            if sum(len(call.case_ids) for call in condition_calls) != CASES_PER_CONDITION:
                raise luna_v1.ApparatusFailure("condition does not cover all 20 cases")

    output_upper = MAX_GENERATION_CALLS * MAX_OUTPUT_TOKENS
    cost_upper = (
        input_upper * INPUT_USD_PER_MILLION / 1_000_000
        + output_upper * OUTPUT_USD_PER_MILLION / 1_000_000
    )
    if cost_upper > AUTHORIZED_COST_CEILING_USD:
        raise luna_v1.ApparatusFailure("cost upper bound exceeds $100 authorization")
    if require_committed:
        revision, sources = _git_revision_and_sources(repo_root)
    else:
        revision, sources = "TEST_UNCOMMITTED", {}

    prior_result = json.loads(
        (repo_root / SEALED_V1_3_DIR / "RESULT.json").read_text(encoding="utf-8")
    )
    prior_raw_state = int(prior_result["representation_utf8_bytes"]["raw"])
    prior_raw_input_total = int(
        prior_result["usage"]["by_condition"]["raw_capability"]["input_tokens"]
    )
    prior_raw_replications = int(prior_result["replication_count"])
    state_totals = {
        condition: sum(row[condition] for row in representation_by_case.values())
        for condition in CONDITIONS
    }
    preflight = luna_v1._sealed(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": revision,
            "source_file_sha256": sources,
            "lineage": lineage,
            "case_pack_sha256": luna_v1.FROZEN_CASE_PACK_SHA256,
            "expanded_pack_sha256": expanded_hash,
            "solver_prompt_template_sha256": luna_v1._sha256_text(
                luna_v1.SOLVER_PROMPT_PREFIX
            ),
            "solver_config": config.to_mapping(),
            "solver_config_sha256": config.configuration_hash,
            "intentional_solver_difference_from_sealed_v1_3": {
                "field": "max_output_tokens",
                "sealed_v1_3": 4_096,
                "experiment_2": MAX_OUTPUT_TOKENS,
                "reason": "explicit Experiment-2 protocol requirement",
            },
            "estimand": (
                "Expected solver accuracy on these fixed 20 frozen benchmark "
                "worlds under repeated stochastic inference with the specified "
                "Luna solver configuration."
            ),
            "inferential_unit": "complete_20_world_stochastic_replication",
            "fixed_worlds_not_independent_population_samples": True,
            "within_call_batch_dependence_disclosed": True,
            "conditions": {
                condition: {
                    "retained_columns": list(CONDITION_COLUMNS[condition]),
                    "deleted_columns": list(DELETED_COLUMNS[condition]),
                }
                for condition in CONDITIONS
            },
            "projection_contract": projection_contract,
            "c1_prior_byte_equivalence": True,
            "kas_prior_c2_byte_equivalence": True,
            "equivalence_exclusions": [],
            "condition_schedule": [list(row) for row in CONDITION_SCHEDULE],
            "condition_schedule_sha256": schedule_hash,
            "request_plan_sha256": plan_hash,
            "call_plan": request_rows,
            "replication_count": REPLICATION_COUNT,
            "conditions_per_replication": len(CONDITIONS),
            "batches_per_condition": BATCHES_PER_CONDITION,
            "maximum_physical_generation_calls": MAX_GENERATION_CALLS,
            "attempts_per_scheduled_call": 1,
            "retry": False,
            "repair": False,
            "fallback": False,
            "tools": False,
            "storage": False,
            "previous_response_id": False,
            "conversation_carry_over": False,
            "resume": False,
            "overwrite": False,
            "representation_utf8_bytes_by_case": representation_by_case,
            "representation_utf8_bytes_per_20_world_replication": state_totals,
            "frozen_raw_reference": {
                "representation_utf8_bytes_per_replication": prior_raw_state,
                "input_tokens_across_six_v1_3_replications": prior_raw_input_total,
                "replication_count": prior_raw_replications,
                "input_tokens_per_replication_mean": (
                    prior_raw_input_total / prior_raw_replications
                ),
                "comparison_note": (
                    "Visible-state byte ratios are deterministic. API input-token "
                    "ratios use the sealed noncontemporaneous v1.3 Raw reference."
                ),
            },
            "prior_c2_minus_c1_vector": list(
                _prior_c2_minus_c1_vector(repo_root)
            ),
            "statistics": {
                "primary_hypotheses": PRIMARY_COMPARISONS,
                "primary_test": "exact_two_sided_replication_sign_flip_2^8",
                "primary_multiplicity": "Holm correction across exactly three singles",
                "secondary_interactions": list(SECONDARY_INTERACTIONS),
                "secondary_multiplicity": "separate Holm correction across four interactions",
                "kas_replication_test": "exact_two_sample_permutation_C(14,6)=3003",
                "alpha": 0.05,
                "baseline_drift_trigger": "C1 exact_correct < 144/160",
            },
            "cost": {
                "pricing_usd_per_million": {
                    "input": INPUT_USD_PER_MILLION,
                    "output_including_reasoning": OUTPUT_USD_PER_MILLION,
                },
                "request_utf8_bytes_input_token_upper_bound": input_upper,
                "output_token_upper_bound": output_upper,
                "conservative_generation_cost_upper_bound_usd": cost_upper,
                "authorized_cost_ceiling_usd": AUTHORIZED_COST_CEILING_USD,
                "note": (
                    "UTF-8 bytes of every exact serialized request are treated as "
                    "a conservative tokenizer-independent input-token upper bound; "
                    "actual API usage is authoritative."
                ),
            },
        }
    )
    return payload, cases, calls, preflight


def exact_two_sided_sign_flip(differences: Sequence[int]) -> Mapping[str, Any]:
    if len(differences) != REPLICATION_COUNT:
        raise ValueError("sign-flip analysis requires exactly eight replications")
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
        "permutations": permutations,
        "extreme_permutations": extreme,
        "p_value": extreme / permutations,
        "alpha": 0.05,
    }


def holm_adjust(tests: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    ordered = sorted(tests, key=lambda name: (float(tests[name]["p_value"]), name))
    total = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, name in enumerate(ordered, start=1):
        candidate = min(1.0, (total - rank + 1) * float(tests[name]["p_value"]))
        running = max(running, candidate)
        adjusted[name] = running
    return {
        name: {
            **dict(tests[name]),
            "holm_family_size": total,
            "holm_adjusted_p_value": adjusted[name],
            "holm_reject_at_0_05": adjusted[name] <= 0.05,
        }
        for name in tests
    }


def exact_kas_replication_permutation(
    new_kas_minus_c1: Sequence[int],
) -> Mapping[str, Any]:
    if len(new_kas_minus_c1) != 8:
        raise ValueError("KAS replication comparison requires eight new differences")
    prior = PRIOR_C2_MINUS_C1_VECTOR
    new = tuple(int(value) for value in new_kas_minus_c1)
    combined = prior + new
    # abs(mean(group6)-mean(group8)); denominator 48 is common to every split.
    observed_numerator = abs(8 * sum(prior) - 6 * sum(new))
    extreme = 0
    allocations = 0
    all_indices = set(range(14))
    for first_indices in itertools.combinations(range(14), 6):
        first_set = set(first_indices)
        second_indices = all_indices - first_set
        numerator = abs(
            8 * sum(combined[index] for index in first_indices)
            - 6 * sum(combined[index] for index in second_indices)
        )
        allocations += 1
        if numerator >= observed_numerator:
            extreme += 1
    if allocations != math.comb(14, 6):
        raise RuntimeError("KAS permutation enumeration is incomplete")
    return {
        "test": "exact_two_sample_permutation_absolute_mean_difference",
        "prior_C2_minus_C1": list(prior),
        "new_KAS_minus_C1": list(new),
        "observed_absolute_mean_difference": observed_numerator / 48,
        "allocations": allocations,
        "extreme_allocations": extreme,
        "p_value": extreme / allocations,
        "alpha": 0.05,
        "replication_failure": extreme / allocations <= 0.05,
        "non_rejection_is_equivalence": False,
    }


def _score_summary(
    scores: Sequence[grading.LabelScore],
    by_case: Mapping[str, worlds.BenchmarkCase],
    *,
    expected_total: int | None = None,
) -> Mapping[str, Any]:
    if expected_total is not None and len(scores) != expected_total:
        raise luna_v1.ApparatusFailure(
            f"score collection contains {len(scores)} rather than {expected_total} rows"
        )
    rows = []
    error_counts: dict[str, int] = {}
    errors = []
    for score in scores:
        if score.case_id not in by_case:
            raise luna_v1.ApparatusFailure("score contains an unknown frozen case")
        row = asdict(score)
        row["failure_reasons"] = list(row["failure_reasons"])
        row["family"] = by_case[score.case_id].family
        row["load"] = by_case[score.case_id].load
        rows.append(row)
        if score.answer_correct is not True:
            error_counts[score.case_id] = error_counts.get(score.case_id, 0) + 1
            errors.append(
                {
                    "case_id": score.case_id,
                    "selected_label": score.selected_label,
                    "expected_label": score.expected_label,
                    "truth_class": score.truth_class,
                    "failure_reasons": list(score.failure_reasons),
                }
            )
    historical_errors = sum(score.truth_class == "historical" for score in scores)
    authority_errors = sum(
        score.truth_class in {"planned", "hallucinated"} for score in scores
    )
    return {
        "total": len(scores),
        "admissible": sum(score.admissible for score in scores),
        "exact_correct": sum(score.answer_correct is True for score in scores),
        "insufficient_responses": sum(
            score.selected_label == "INSUFFICIENT" for score in scores
        ),
        "chronology_errors": historical_errors,
        "authority_errors": authority_errors,
        "chronology_authority_errors": sum(
            score.chronology_authority_error is True for score in scores
        ),
        "illegal_state_promotions": sum(
            score.illegal_state_promotions or 0 for score in scores
        ),
        "grader_failures": sum(score.grader_status != "ran" for score in scores),
        "secondary_failures": sum(score.secondary_status != "ran" for score in scores),
        "world_error_counts": dict(sorted(error_counts.items())),
        "errors": errors,
        "scores": rows,
        "chronology_error_definition": "selected frozen truth_class == historical",
        "authority_error_definition": (
            "selected frozen truth_class is planned or hallucinated"
        ),
    }


def _usage_from_records(records: Sequence[Any]) -> Mapping[str, Any]:
    def metadata(record: Any) -> Mapping[str, Any]:
        return record.metadata if hasattr(record, "metadata") else record["metadata"]

    def condition(record: Any) -> str:
        return record.condition if hasattr(record, "condition") else str(record["condition"])

    def measured_int(item: Mapping[str, Any], name: str) -> int:
        value = item.get(name)
        return value if type(value) is int and value >= 0 else 0

    def measured_float(item: Mapping[str, Any], name: str) -> float:
        value = item.get(name)
        return (
            float(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else 0.0
        )

    by_condition: dict[str, dict[str, Any]] = {}
    for condition_id in CONDITIONS:
        selected = [record for record in records if condition(record) == condition_id]
        input_tokens = sum(measured_int(metadata(record), "input_tokens") for record in selected)
        output_tokens = sum(measured_int(metadata(record), "output_tokens") for record in selected)
        by_condition[condition_id] = {
            "call_artifacts": len(selected),
            "physical_generation_calls": sum(
                measured_int(metadata(record), "physical_attempts") for record in selected
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": sum(
                measured_int(metadata(record), "reasoning_tokens") for record in selected
            ),
            "total_tokens": input_tokens + output_tokens,
            "latency_seconds": sum(
                measured_float(metadata(record), "latency_seconds") for record in selected
            ),
            "estimated_generation_cost_usd": (
                input_tokens * INPUT_USD_PER_MILLION / 1_000_000
                + output_tokens * OUTPUT_USD_PER_MILLION / 1_000_000
            ),
        }
    total = {
        name: sum(row[name] for row in by_condition.values())
        for name in (
            "call_artifacts",
            "physical_generation_calls",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "latency_seconds",
            "estimated_generation_cost_usd",
        )
    }
    return {"by_condition": by_condition, "total": total}


def _effect_summary(
    differences: Sequence[int],
    *,
    definition: str = "condition_correct_minus_C1_correct_out_of_20",
) -> Mapping[str, Any]:
    values = [int(value) for value in differences]
    ordered = sorted(values)
    median = (ordered[3] + ordered[4]) / 2
    return {
        "difference_definition": definition,
        "differences": values,
        "mean_answers_out_of_20": sum(values) / len(values),
        "mean_accuracy_percentage_points": 5 * sum(values) / len(values),
        "median_answers_out_of_20": median,
        "minimum": min(values),
        "maximum": max(values),
        "negative_replications": sum(value < 0 for value in values),
        "tie_replications": sum(value == 0 for value in values),
        "positive_replications": sum(value > 0 for value in values),
        "aggregate_correct_delta_out_of_160": sum(values),
    }


def _interaction_vectors(scores: Mapping[str, Sequence[int]]) -> Mapping[str, list[int]]:
    result = {name: [] for name in SECONDARY_INTERACTIONS}
    for index in range(REPLICATION_COUNT):
        c1 = int(scores["C1"][index])
        kind = int(scores["K-"][index])
        authority = int(scores["A-"][index])
        status = int(scores["S-"][index])
        ka = int(scores["KA-"][index])
        ks = int(scores["KS-"][index])
        ass = int(scores["AS-"][index])
        kas = int(scores["KAS-"][index])
        result["I_KA"].append(ka - kind - authority + c1)
        result["I_KS"].append(ks - kind - status + c1)
        result["I_AS"].append(ass - authority - status + c1)
        result["I_KAS"].append(
            kas - ka - ks - ass + kind + authority + status - c1
        )
    return result


def _classify(
    *,
    totals: Mapping[str, int],
    primary: Mapping[str, Mapping[str, Any]],
    interactions: Mapping[str, Mapping[str, Any]],
    kas_replication: Mapping[str, Any],
) -> Mapping[str, Any]:
    harmful_singles = [
        name
        for name, test in primary.items()
        if test["holm_adjusted_p_value"] <= 0.05
        and test["effect"]["mean_answers_out_of_20"] < 0
    ]
    harmful_interactions = [
        name
        for name, test in interactions.items()
        if test["holm_adjusted_p_value"] <= 0.05
        and test["effect"]["mean_answers_out_of_20"] < 0
    ]
    baseline_drift = int(totals["C1"]) < BASELINE_STABILITY_MIN_CORRECT
    if baseline_drift:
        code = "VALID_BASELINE_DRIFT"
        evidence = "INCONCLUSIVE"
        licensed = False
    elif kas_replication["p_value"] <= 0.05:
        code = "VALID_KAS_REPLICATION_FAILURE"
        evidence = "INCONCLUSIVE"
        licensed = False
    elif len(harmful_singles) >= 2:
        code = "VALID_SUPPORTED_DISTRIBUTED_BUNDLE"
        evidence = "SUPPORTED"
        licensed = True
    elif len(harmful_singles) == 1:
        code = {
            "H_KIND": "VALID_SUPPORTED_KIND_LOAD_BEARING",
            "H_AUTHORITY": "VALID_SUPPORTED_AUTHORITY_LOAD_BEARING",
            "H_STATUS": "VALID_SUPPORTED_STATUS_LOAD_BEARING",
        }[harmful_singles[0]]
        evidence = "SUPPORTED"
        licensed = True
    elif harmful_interactions:
        code = "VALID_SUPPORTED_MULTIFIELD_INTERACTION"
        evidence = "SUPPORTED"
        licensed = True
    elif all(test["holm_adjusted_p_value"] > 0.05 for test in primary.values()):
        code = "VALID_NO_SINGLE_FIELD_EFFECT"
        evidence = "NOT_SUPPORTED"
        licensed = True
    else:
        code = "VALID_NOT_SUPPORTED"
        evidence = "NOT_SUPPORTED"
        licensed = True
    return {
        "result_code": code,
        "evidence_label": evidence,
        "baseline_drift": baseline_drift,
        "baseline_threshold": "C1 exact_correct < 144/160",
        "harmful_single_field_hypotheses": harmful_singles,
        "harmful_secondary_interactions": harmful_interactions,
        "semantic_conclusion_licensed": licensed,
        "no_detected_single_effect_is_equivalence": False,
    }


def aggregate_valid_result(
    *,
    cases: Sequence[worlds.BenchmarkCase],
    scores: Mapping[int, Mapping[str, Sequence[grading.LabelScore]]],
    records: Sequence[Any],
    preflight: Mapping[str, Any],
) -> Mapping[str, Any]:
    by_case = {case.case_id: case for case in cases}
    replication_scores: dict[str, dict[str, int]] = {}
    condition_summaries: dict[str, Mapping[str, Any]] = {}
    totals: dict[str, int] = {}
    for replication in range(1, REPLICATION_COUNT + 1):
        replication_scores[str(replication)] = {}
        for condition in CONDITIONS:
            selected = list(scores[replication][condition])
            if len(selected) != CASES_PER_CONDITION:
                raise luna_v1.ApparatusFailure(
                    f"replication {replication} {condition} lacks 20 scores"
                )
            replication_scores[str(replication)][condition] = sum(
                score.answer_correct is True for score in selected
            )
    score_vectors = {
        condition: [
            replication_scores[str(replication)][condition]
            for replication in range(1, REPLICATION_COUNT + 1)
        ]
        for condition in CONDITIONS
    }
    for condition in CONDITIONS:
        all_scores = [
            score
            for replication in range(1, REPLICATION_COUNT + 1)
            for score in scores[replication][condition]
        ]
        summary = dict(
            _score_summary(all_scores, by_case, expected_total=TRIALS_PER_CONDITION)
        )
        summary["exact_correct_by_replication"] = score_vectors[condition]
        summary["mean_correct_out_of_20"] = sum(score_vectors[condition]) / 8
        summary["errors"] = [
            {
                "replication": replication,
                "case_id": score.case_id,
                "selected_label": score.selected_label,
                "expected_label": score.expected_label,
                "truth_class": score.truth_class,
                "failure_reasons": list(score.failure_reasons),
            }
            for replication in range(1, REPLICATION_COUNT + 1)
            for score in scores[replication][condition]
            if score.answer_correct is not True
        ]
        condition_summaries[condition] = summary
        totals[condition] = int(summary["exact_correct"])

    primary_unadjusted: dict[str, Mapping[str, Any]] = {}
    for hypothesis, condition in PRIMARY_COMPARISONS.items():
        differences = [
            score_vectors[condition][index] - score_vectors["C1"][index]
            for index in range(REPLICATION_COUNT)
        ]
        primary_unadjusted[hypothesis] = {
            **exact_two_sided_sign_flip(differences),
            "control": "C1",
            "condition": condition,
            "effect": _effect_summary(differences),
        }
    primary = holm_adjust(primary_unadjusted)

    interaction_vectors = _interaction_vectors(score_vectors)
    interaction_unadjusted = {
        name: {
            **exact_two_sided_sign_flip(vector),
            "effect": _effect_summary(
                vector,
                definition=f"{name}_factorial_accuracy_contrast_out_of_20",
            ),
            "inferential_role": "secondary_mechanistic_separate_Holm_family",
        }
        for name, vector in interaction_vectors.items()
    }
    interactions = holm_adjust(interaction_unadjusted)
    kas_delta = [
        score_vectors["KAS-"][index] - score_vectors["C1"][index]
        for index in range(REPLICATION_COUNT)
    ]
    kas_replication = exact_kas_replication_permutation(kas_delta)
    classification = _classify(
        totals=totals,
        primary=primary,
        interactions=interactions,
        kas_replication=kas_replication,
    )
    usage = _usage_from_records(records)
    state_per_replication = preflight[
        "representation_utf8_bytes_per_20_world_replication"
    ]
    raw_state = preflight["frozen_raw_reference"][
        "representation_utf8_bytes_per_replication"
    ]
    raw_input_reference = (
        preflight["frozen_raw_reference"]["input_tokens_per_replication_mean"]
        * REPLICATION_COUNT
    )
    representation_metrics = {}
    for condition in CONDITIONS:
        visible = int(state_per_replication[condition])
        condition_usage = usage["by_condition"][condition]
        representation_metrics[condition] = {
            "canonical_serialized_utf8_bytes_per_20_world_replication": visible,
            "canonical_serialized_utf8_bytes_across_eight_replications": (
                visible * REPLICATION_COUNT
            ),
            "visible_state_percentage_of_frozen_raw": 100 * visible / raw_state,
            "actual_api_input_tokens": condition_usage["input_tokens"],
            "input_tokens_percentage_of_scaled_prior_raw_reference": (
                100 * condition_usage["input_tokens"] / raw_input_reference
            ),
            "prior_raw_reference_is_contemporaneous": False,
            "actual_api_output_tokens": condition_usage["output_tokens"],
            "actual_api_reasoning_tokens": condition_usage["reasoning_tokens"],
            "actual_api_total_tokens": condition_usage["total_tokens"],
            "actual_latency_seconds": condition_usage["latency_seconds"],
            "actual_api_cost_usd": condition_usage[
                "estimated_generation_cost_usd"
            ],
            "physical_generation_calls": condition_usage[
                "physical_generation_calls"
            ],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "source_revision": preflight["source_revision"],
        "validity": "VALID",
        "result_code": classification["result_code"],
        "evidence_label": classification["evidence_label"],
        "estimand": preflight["estimand"],
        "replication_count": REPLICATION_COUNT,
        "fixed_world_count": CASES_PER_CONDITION,
        "fixed_worlds_reused_across_replications": True,
        "batch_dependence_disclosed": True,
        "replication_scores": replication_scores,
        "conditions": condition_summaries,
        "primary_single_field_hypotheses": primary,
        "secondary_interactions": interactions,
        "kas_behavioral_replication": kas_replication,
        "classification": classification,
        "representation_metrics": representation_metrics,
        "visible_state_definition": (
            "canonical serialized UTF-8 bytes of only the representation object "
            "supplied for all 20 frozen worlds; bytes are not tokens"
        ),
        "usage": usage,
        "returned_model": sorted(
            {
                record.metadata.get("returned_model")
                if hasattr(record, "metadata")
                else record["metadata"].get("returned_model")
                for record in records
                if (
                    record.metadata.get("returned_model")
                    if hasattr(record, "metadata")
                    else record["metadata"].get("returned_model")
                )
            }
        ),
        "returned_service_tier": sorted(
            {
                record.metadata.get("returned_service_tier")
                if hasattr(record, "metadata")
                else record["metadata"].get("returned_service_tier")
                for record in records
                if (
                    record.metadata.get("returned_service_tier")
                    if hasattr(record, "metadata")
                    else record["metadata"].get("returned_service_tier")
                )
            }
        ),
        "claim_scope": (
            "only this frozen 20-world benchmark, representation grammar, Luna "
            "solver configuration, named-column projections, and stochastic protocol"
        ),
        "explicit_non_claims": [
            "Hive generally",
            "transfer",
            "learned abstraction",
            "universal authority semantics",
            "model capability substitution",
            "Sol equivalence",
            "general causal necessity",
            "AGI",
            "recursive improvement",
        ],
    }


def _assert_sources_unchanged(repo_root: Path, preflight: Mapping[str, Any]) -> None:
    expected = preflight.get("source_file_sha256", {})
    if not expected:
        return
    revision = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if revision != preflight["source_revision"]:
        raise luna_v1.ApparatusFailure("source revision changed after preflight")
    for relative, digest in expected.items():
        path = repo_root / relative
        if not path.is_file() or luna_v1._sha256_bytes(path.read_bytes()) != digest:
            raise luna_v1.ApparatusFailure(
                f"committed experiment source changed after preflight: {relative}"
            )


def _safe_reason(exc: BaseException) -> str:
    safe = luna_v1._safe_error(exc)
    assert safe is not None
    return str(safe["message"])


def _write_evidence_index(
    output_dir: Path, *, source_revision: str
) -> Mapping[str, Any]:
    index_path = output_dir / "EVIDENCE_INDEX.json"
    rows = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        if path == index_path:
            continue
        rows.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": luna_v1._sha256_bytes(path.read_bytes()),
            }
        )
    index = luna_v1._sealed(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "source_revision": source_revision,
            "file_count": len(rows),
            "total_bytes": sum(row["bytes"] for row in rows),
            "files": rows,
        }
    )
    luna_v1._write_exclusive(index_path, luna_v1._pretty_json(index))
    return index


class SemanticDecompositionRunner:
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
        self.config = solver_config()
        self.scores: dict[int, dict[str, list[grading.LabelScore]]] = {
            replication: {condition: [] for condition in CONDITIONS}
            for replication in range(1, REPLICATION_COUNT + 1)
        }
        self.response_ids: set[str] = set()

    def _run_call(
        self,
        audit: luna_v1.OpenAIAuditStore,
        planned: ExperimentCall,
        by_case: Mapping[str, worlds.BenchmarkCase],
    ) -> None:
        response = audit.ask(planned)
        record = audit.records[-1]
        response_id = record.metadata.get("response_id")
        if not isinstance(response_id, str) or not response_id:
            raise luna_v1.ApparatusFailure("response identity is missing")
        if response_id in self.response_ids:
            audit.write_decision(
                record,
                {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "call_id": record.call_id,
                    "status": "response_identity_reused",
                    "replication": planned.replication,
                    "condition_position": planned.condition_position,
                    "stage": planned.stage,
                    "batch_id": planned.batch_id,
                    "condition": planned.condition,
                    "parser_status": "not_run",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "response_sha256": luna_v1._sha256_text(response),
                    "scores": [],
                },
            )
            raise luna_v1.ApparatusFailure("response ID was reused")
        self.response_ids.add(response_id)
        cases = [by_case[case_id] for case_id in planned.case_ids]
        try:
            labels = luna_v1.parse_structured_labels(response, len(cases))
        except grading.ConstrainedInterfaceFailure as exc:
            rejected = [
                grading.rejected_score(case, planned.condition) for case in cases
            ]
            self.scores[planned.replication][planned.condition].extend(rejected)
            audit.write_decision(
                record,
                {
                    "schema_version": SCHEMA_VERSION,
                    "protocol_id": PROTOCOL_ID,
                    "call_id": record.call_id,
                    "status": "parser_rejected",
                    "replication": planned.replication,
                    "condition_position": planned.condition_position,
                    "stage": planned.stage,
                    "batch_id": planned.batch_id,
                    "condition": planned.condition,
                    "response_sha256": luna_v1._sha256_text(response),
                    "parser_status": "failed",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "error": str(exc),
                    "scores": [asdict(score) for score in rejected],
                },
            )
            raise luna_v1.ApparatusFailure(
                f"{record.call_id} strict parser rejected output"
            ) from None
        scores = [
            grading.grade_label(case, label, condition=planned.condition)
            for case, label in zip(cases, labels)
        ]
        self.scores[planned.replication][planned.condition].extend(scores)
        secondary_failed = any(score.secondary_status != "ran" for score in scores)
        audit.write_decision(
            record,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "call_id": record.call_id,
                "status": "secondary_failed" if secondary_failed else "graded",
                "replication": planned.replication,
                "condition_position": planned.condition_position,
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "response_sha256": luna_v1._sha256_text(response),
                "parser_status": "passed",
                "grader_status": "ran",
                "grader_agreement": True,
                "labels": list(labels),
                "scores": [asdict(score) for score in scores],
            },
        )
        if secondary_failed:
            raise luna_v1.ApparatusFailure(
                f"{record.call_id} deterministic secondary evaluation failed"
            )

    def _finish(
        self,
        audit: luna_v1.OpenAIAuditStore,
        *,
        preflight: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        sealed_result = luna_v1._sealed(result)
        luna_v1._write_exclusive(
            self.output_dir / "RESULT.json", luna_v1._pretty_json(sealed_result)
        )
        usage = result["usage"]
        luna_v1._write_exclusive(
            self.output_dir / "RUN_STATUS.json",
            luna_v1._pretty_json(
                luna_v1._sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "finished_at_utc": luna_v1._utc_now(),
                        "validity": result["validity"],
                        "result_code": result["result_code"],
                        "call_artifacts": len(audit.records),
                        "physical_generation_calls": usage["total"][
                            "physical_generation_calls"
                        ],
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
        audit: luna_v1.OpenAIAuditStore,
        *,
        preflight: Mapping[str, Any],
        failed_call: ExperimentCall,
        exc: BaseException,
    ) -> Mapping[str, Any]:
        partial = {
            str(replication): {
                condition: len(self.scores[replication][condition])
                for condition in CONDITIONS
            }
            for replication in range(1, REPLICATION_COUNT + 1)
        }
        invalid = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": preflight["source_revision"],
            "validity": "INVALID",
            "result_code": "INVALID_APPARATUS",
            "failed_sequence": failed_call.sequence,
            "failed_replication": failed_call.replication,
            "failed_condition": failed_call.condition,
            "failed_batch_id": failed_call.batch_id,
            "apparatus_failure": _safe_reason(exc),
            "partial_score_counts": partial,
            "usage": _usage_from_records(audit.records),
            "returned_model": audit.returned_model,
            "evidence_interpretation": "No semantic-decomposition claim is licensed.",
            "partial_artifacts_preserved": True,
            "retry_attempted": False,
            "repair_attempted": False,
        }
        return self._finish(audit, preflight=preflight, result=invalid)

    def run(self) -> Mapping[str, Any]:
        expected_live_dir = (self.repo_root / RUN_DIR).resolve()
        if self.require_committed and self.output_dir.resolve() != expected_live_dir:
            raise luna_v1.ApparatusFailure(
                "live Experiment-2 execution is locked to the preregistered directory"
            )
        if self.output_dir.exists():
            raise luna_v1.ApparatusFailure(
                "Experiment-2 run directory already exists; no inference was started"
            )
        payload, cases, calls, preflight = deterministic_preflight(
            self.repo_root, require_committed=self.require_committed
        )
        del payload
        if self.output_dir.exists():
            raise luna_v1.ApparatusFailure(
                "Experiment-2 run directory appeared during preflight"
            )
        by_case = {case.case_id: case for case in cases}
        audit = luna_v1.OpenAIAuditStore(
            self.output_dir, ask_fn=self.ask_fn, config=self.config
        )
        luna_v1._write_exclusive(
            self.output_dir / "PRECHECK.json", luna_v1._pretty_json(preflight)
        )
        luna_v1._write_exclusive(
            self.output_dir / "PROTOCOL.json",
            luna_v1._pretty_json(
                luna_v1._sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "protocol_version": PROTOCOL_VERSION,
                        "mission": (
                            "mechanically decompose kind/authority/status from exact C1"
                        ),
                        "conditions": list(CONDITIONS),
                        "replications": REPLICATION_COUNT,
                        "calls": MAX_GENERATION_CALLS,
                        "schedule_sha256": preflight[
                            "condition_schedule_sha256"
                        ],
                        "request_plan_sha256": preflight["request_plan_sha256"],
                        "primary_hypotheses": PRIMARY_COMPARISONS,
                        "dispositions_frozen_before_inference": [
                            "VALID_SUPPORTED_KIND_LOAD_BEARING",
                            "VALID_SUPPORTED_AUTHORITY_LOAD_BEARING",
                            "VALID_SUPPORTED_STATUS_LOAD_BEARING",
                            "VALID_SUPPORTED_MULTIFIELD_INTERACTION",
                            "VALID_SUPPORTED_DISTRIBUTED_BUNDLE",
                            "VALID_NO_SINGLE_FIELD_EFFECT",
                            "VALID_KAS_REPLICATION_FAILURE",
                            "VALID_BASELINE_DRIFT",
                            "VALID_NOT_SUPPORTED",
                            "INVALID_APPARATUS",
                        ],
                        "no_query_aware_selection": True,
                        "no_post_output_tuning": True,
                        "one_physical_attempt": True,
                        "retry": False,
                        "repair": False,
                        "fallback": False,
                    }
                )
            ),
        )
        luna_v1._write_exclusive(
            self.output_dir / "MANIFEST.json",
            luna_v1._pretty_json(
                luna_v1._sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "protocol_version": PROTOCOL_VERSION,
                        "created_at_utc": luna_v1._utc_now(),
                        "source_revision": preflight["source_revision"],
                        "precheck_sha256": preflight["payload_sha256"],
                        "solver_config": self.config.to_mapping(),
                        "solver_config_sha256": self.config.configuration_hash,
                        "maximum_physical_generation_calls": MAX_GENERATION_CALLS,
                        "attempts_per_call": 1,
                        "no_retry": True,
                        "no_resume": True,
                        "no_overwrite": True,
                    }
                )
            ),
        )
        for planned in calls:
            try:
                _assert_sources_unchanged(self.repo_root, preflight)
                self._run_call(audit, planned, by_case)
                _assert_sources_unchanged(self.repo_root, preflight)
            except BaseException as exc:
                return self._invalid(
                    audit,
                    preflight=preflight,
                    failed_call=planned,
                    exc=exc,
                )
        try:
            if len(audit.records) != MAX_GENERATION_CALLS:
                raise luna_v1.ApparatusFailure("completed schedule has wrong call count")
            if len(self.response_ids) != MAX_GENERATION_CALLS:
                raise luna_v1.ApparatusFailure(
                    "completed schedule has reused response IDs"
                )
            result = aggregate_valid_result(
                cases=cases,
                scores=self.scores,
                records=audit.records,
                preflight=preflight,
            )
        except BaseException as exc:
            return self._invalid(
                audit,
                preflight=preflight,
                failed_call=calls[-1],
                exc=exc,
            )
        return self._finish(audit, preflight=preflight, result=result)


def _verify_index(run_dir: Path) -> Mapping[str, Any]:
    index_path = run_dir / "EVIDENCE_INDEX.json"
    if not index_path.is_file():
        raise luna_v1.ApparatusFailure("EVIDENCE_INDEX.json is missing")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    luna_v1._verify_seal(index)
    expected_paths = {row["path"] for row in index["files"]}
    actual_paths = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path != index_path
    }
    if expected_paths != actual_paths:
        raise luna_v1.ApparatusFailure("evidence file set differs from sealed index")
    for row in index["files"]:
        path = run_dir / row["path"]
        if (
            path.stat().st_size != row["bytes"]
            or luna_v1._sha256_bytes(path.read_bytes()) != row["sha256"]
        ):
            raise luna_v1.ApparatusFailure(f"sealed evidence changed: {row['path']}")
        if path.suffix == ".json":
            luna_v1._verify_seal(json.loads(path.read_text(encoding="utf-8")))
    return index


def _score_from_mapping(payload: Mapping[str, Any]) -> grading.LabelScore:
    values = dict(payload)
    values["failure_reasons"] = tuple(values["failure_reasons"])
    return grading.LabelScore(**values)


def _score_mapping(score: grading.LabelScore) -> Mapping[str, Any]:
    payload = asdict(score)
    payload["failure_reasons"] = list(payload["failure_reasons"])
    return payload


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    index = _verify_index(run_dir)
    preflight = json.loads((run_dir / "PRECHECK.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    if (
        preflight.get("protocol_id") != PROTOCOL_ID
        or result.get("protocol_id") != PROTOCOL_ID
        or index.get("protocol_id") != PROTOCOL_ID
    ):
        raise luna_v1.ApparatusFailure("artifact protocol identity mismatch")
    if preflight.get("source_revision") != index.get("source_revision"):
        raise luna_v1.ApparatusFailure("artifact source revision binding mismatch")
    if (
        preflight.get("condition_schedule_sha256") != FROZEN_SCHEDULE_SHA256
        or luna_v1._sha256_text(
            luna_v1._canonical_json(preflight.get("condition_schedule"))
        )
        != FROZEN_SCHEDULE_SHA256
        or preflight.get("request_plan_sha256") != FROZEN_REQUEST_PLAN_SHA256
        or luna_v1._sha256_text(luna_v1._canonical_json(preflight.get("call_plan")))
        != FROZEN_REQUEST_PLAN_SHA256
    ):
        raise luna_v1.ApparatusFailure("sealed schedule or request-plan hash drifted")
    call_paths = sorted((run_dir / "calls").glob("call_*.json"))
    decision_paths = sorted((run_dir / "decisions").glob("decision_*.json"))
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    if len(events) != 2 * len(call_paths):
        raise luna_v1.ApparatusFailure("audit journal does not contain two events per call")
    if len(decision_paths) > len(call_paths) or len(call_paths) - len(decision_paths) > 1:
        raise luna_v1.ApparatusFailure("call/decision artifact counts are inconsistent")
    plan = {int(row["sequence"]): row for row in preflight["call_plan"]}
    repo_root = Path(__file__).resolve().parents[1]
    frozen_payload, cases = worlds.load_case_pack(
        repo_root / "benchmarks/decompression_test/CASE_PACK.json"
    )
    worlds.validate_case_pack(frozen_payload, cases)
    frozen_calls = {
        call.sequence: call for call in build_call_plan(frozen_payload, cases)
    }
    try:
        event_payloads = [json.loads(line) for line in events]
    except json.JSONDecodeError as exc:
        raise luna_v1.ApparatusFailure("audit journal contains invalid JSON") from exc
    record_rows = []
    physical_attempt_values = []
    response_ids = []
    response_hashes = []
    returned_models = set()
    service_tiers = set()
    call_artifacts = []
    for sequence, path in enumerate(call_paths, start=1):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if (
            artifact.get("sequence") != sequence
            or sequence not in plan
            or sequence not in frozen_calls
        ):
            raise luna_v1.ApparatusFailure("call sequence is not contiguous or planned")
        expected = plan[sequence]
        frozen_call = frozen_calls[sequence]
        expected_call_id = f"call_{sequence:06d}"
        if any(
            artifact.get(name) != expected[name]
            for name in ("stage", "batch_id", "condition", "case_ids")
        ) or artifact.get("call_id") != expected_call_id:
            raise luna_v1.ApparatusFailure("call identity differs from frozen plan")
        request = artifact["request"]
        prompt = request.get("prompt")
        prompt_sha256 = (
            luna_v1._sha256_text(prompt) if isinstance(prompt, str) else None
        )
        if (
            prompt != frozen_call.prompt
            or prompt_sha256 != expected["prompt_sha256"]
            or request.get("prompt_sha256") != prompt_sha256
            or request.get("openai_text_format") != frozen_call.text_format
            or luna_v1._sha256_text(
                luna_v1._canonical_json(request.get("openai_text_format"))
            )
            != expected["text_format_sha256"]
            or request.get("openai_text_format_sha256")
            != expected["text_format_sha256"]
            or request.get("solver_config_sha256")
            != preflight["solver_config_sha256"]
            or request.get("solver_config") != preflight["solver_config"]
        ):
            raise luna_v1.ApparatusFailure("call request differs from frozen plan")
        response = artifact.get("response")
        if not isinstance(response, Mapping):
            raise luna_v1.ApparatusFailure("call response envelope is missing")
        raw_response = response.get("raw_text")
        if raw_response is not None and not isinstance(raw_response, str):
            raise luna_v1.ApparatusFailure("call raw response is not text or null")
        response_sha256 = (
            luna_v1._sha256_text(raw_response)
            if isinstance(raw_response, str)
            else None
        )
        if response.get("sha256") != response_sha256:
            raise luna_v1.ApparatusFailure("stored raw response SHA is invalid")
        response_hashes.append(response_sha256)
        started_event = event_payloads[2 * (sequence - 1)]
        finished_event = event_payloads[2 * (sequence - 1) + 1]
        if (
            not isinstance(started_event, Mapping)
            or started_event.get("event") != "call_started"
            or started_event.get("call_id") != expected_call_id
            or started_event.get("sequence") != sequence
            or started_event.get("stage") != expected["stage"]
            or started_event.get("batch_id") != expected["batch_id"]
            or started_event.get("condition") != expected["condition"]
            or started_event.get("prompt_sha256") != prompt_sha256
        ):
            raise luna_v1.ApparatusFailure(
                "call_started journal event differs from frozen request identity"
            )
        artifact_relative = path.relative_to(run_dir).as_posix()
        artifact_file_sha256 = luna_v1._sha256_bytes(path.read_bytes())
        if (
            not isinstance(finished_event, Mapping)
            or finished_event.get("event") != "call_finished"
            or finished_event.get("call_id") != expected_call_id
            or finished_event.get("sequence") != sequence
            or finished_event.get("status") != artifact.get("status")
            or finished_event.get("artifact_path") != artifact_relative
            or finished_event.get("artifact_file_sha256")
            != artifact_file_sha256
        ):
            raise luna_v1.ApparatusFailure(
                "call_finished journal event differs from sealed call artifact"
            )
        metadata = artifact.get("transport_metadata", {})
        attempts = metadata.get("physical_attempts")
        physical_attempt_values.append(attempts)
        if type(attempts) is int and attempts not in {0, 1}:
            raise luna_v1.ApparatusFailure("a call used more than one physical attempt")
        response_id = metadata.get("response_id")
        if isinstance(response_id, str) and response_id:
            response_ids.append(response_id)
        returned_model = metadata.get("returned_model")
        if isinstance(returned_model, str) and returned_model:
            returned_models.add(returned_model)
        service_tier = metadata.get("returned_service_tier")
        if isinstance(service_tier, str) and service_tier:
            service_tiers.add(service_tier)
        if metadata.get("cached_input_tokens") not in {None, 0}:
            raise luna_v1.ApparatusFailure("cache use was detected")
        record_rows.append({"condition": artifact["condition"], "metadata": metadata})
        call_artifacts.append(artifact)
    response_id_reuse_observed = len(response_ids) != len(set(response_ids))
    identity_drift_observed = len(returned_models) > 1 or len(service_tiers) > 1
    decision_artifacts = []
    for sequence, path in enumerate(decision_paths, start=1):
        decision = json.loads(path.read_text(encoding="utf-8"))
        if decision.get("response_sha256") != response_hashes[sequence - 1]:
            raise luna_v1.ApparatusFailure(
                "decision response SHA differs from sealed raw response"
            )
        decision_artifacts.append(decision)

    if result["validity"] == "VALID":
        config = solver_config()
        expected_returned_model = None
        for sequence, (artifact, frozen_call) in enumerate(
            zip(call_artifacts, frozen_calls.values()), start=1
        ):
            if (
                artifact.get("status") != "completed"
                or artifact.get("transport_error") is not None
                or artifact.get("admission_error") is not None
            ):
                raise luna_v1.ApparatusFailure(
                    "valid call envelope is not completed and error-free"
                )
            metadata = artifact.get("transport_metadata", {})
            for name, value in config.to_mapping().items():
                if metadata.get(name) != value:
                    raise luna_v1.ApparatusFailure(
                        f"valid call metadata contradicts frozen {name} contract"
                    )
            if metadata.get("openai_text_format") != frozen_call.text_format:
                raise luna_v1.ApparatusFailure(
                    "valid call metadata contains a different output schema"
                )
            for carryover_name in (
                "previous_response_id",
                "conversation_id",
                "conversation_carry_over",
            ):
                if metadata.get(carryover_name) not in {None, False, ""}:
                    raise luna_v1.ApparatusFailure(
                        "valid call metadata contradicts current-turn isolation"
                    )
            for forbidden_activity in (
                "retry",
                "retry_attempted",
                "fallback",
                "fallback_used",
                "tool_used",
                "tools_used",
                "storage_used",
            ):
                if metadata.get(forbidden_activity) not in {None, False, "", 0}:
                    raise luna_v1.ApparatusFailure(
                        "valid call metadata records forbidden retry/fallback/tool/storage activity"
                    )
            returned_model, _ = luna_v1._validate_metadata(
                metadata,
                config=config,
                expected_text_format=frozen_call.text_format,
                expected_returned_model=expected_returned_model,
            )
            if expected_returned_model is None:
                expected_returned_model = returned_model
        if (
            len(call_paths) != MAX_GENERATION_CALLS
            or len(decision_paths) != MAX_GENERATION_CALLS
            or len(response_ids) != MAX_GENERATION_CALLS
            or response_id_reuse_observed
            or any(attempts != 1 for attempts in physical_attempt_values)
            or _usage_from_records(record_rows)["total"][
                "physical_generation_calls"
            ]
            != MAX_GENERATION_CALLS
            or len(returned_models) != 1
            or service_tiers != {"default"}
            or identity_drift_observed
        ):
            raise luna_v1.ApparatusFailure("valid run is not 384 complete unique calls")
        scores: dict[int, dict[str, list[grading.LabelScore]]] = {
            replication: {condition: [] for condition in CONDITIONS}
            for replication in range(1, REPLICATION_COUNT + 1)
        }
        by_case = {case.case_id: case for case in cases}
        for sequence, decision in enumerate(decision_artifacts, start=1):
            expected = plan[sequence]
            if (
                decision.get("status") != "graded"
                or decision.get("parser_status") != "passed"
                or decision.get("grader_status") != "ran"
                or decision.get("condition") != expected["condition"]
                or decision.get("replication") != expected["replication"]
            ):
                raise luna_v1.ApparatusFailure("valid decision differs from plan")
            raw_response = call_artifacts[sequence - 1].get("response", {}).get(
                "raw_text"
            )
            try:
                reparsed_labels = luna_v1.parse_structured_labels(
                    raw_response, len(expected["case_ids"])
                )
            except grading.ConstrainedInterfaceFailure as exc:
                raise luna_v1.ApparatusFailure(
                    "sealed raw response failed independent strict parsing"
                ) from exc
            if decision.get("labels") != list(reparsed_labels):
                raise luna_v1.ApparatusFailure(
                    "stored decision labels differ from reparsed raw labels"
                )
            stored_scores = decision.get("scores")
            if not isinstance(stored_scores, list) or [
                row.get("case_id") if isinstance(row, Mapping) else None
                for row in stored_scores
            ] != expected["case_ids"]:
                raise luna_v1.ApparatusFailure(
                    "stored score case IDs/order differ from frozen planned batch"
                )
            regenerated = [
                grading.grade_label(
                    by_case[case_id], label, condition=decision["condition"]
                )
                for case_id, label in zip(expected["case_ids"], reparsed_labels)
            ]
            if stored_scores != [_score_mapping(score) for score in regenerated]:
                raise luna_v1.ApparatusFailure(
                    "stored scores differ from independent deterministic regrading"
                )
            scores[int(decision["replication"])][decision["condition"]].extend(
                regenerated
            )
        expected_result = aggregate_valid_result(
            cases=cases,
            scores=scores,
            records=record_rows,
            preflight=preflight,
        )
        observed = dict(result)
        observed.pop("payload_sha256", None)
        if observed != expected_result:
            raise luna_v1.ApparatusFailure("result is not derivable from sealed decisions")
    elif result.get("result_code") != "INVALID_APPARATUS":
        raise luna_v1.ApparatusFailure("invalid evidence has a semantic disposition")

    return {
        "verified": True,
        "protocol_id": PROTOCOL_ID,
        "validity": result["validity"],
        "result_code": result["result_code"],
        "file_count": index["file_count"],
        "total_bytes": index["total_bytes"],
        "call_artifacts": len(call_paths),
        "decision_artifacts": len(decision_paths),
        "physical_generation_calls": _usage_from_records(record_rows)["total"][
            "physical_generation_calls"
        ],
        "unique_response_ids": len(set(response_ids)),
        "returned_models": sorted(returned_models),
        "returned_service_tiers": sorted(service_tiers),
        "source_revision": index["source_revision"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acknowledge-frozen-semantic-authority-decomposition-v1",
        action="store_true",
        help="required acknowledgement for the one frozen 384-call run",
    )
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(luna_v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge_frozen_semantic_authority_decomposition_v1:
        parser.error(
            "--acknowledge-frozen-semantic-authority-decomposition-v1 is required"
        )
    luna_v1._check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = SemanticDecompositionRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(luna_v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
