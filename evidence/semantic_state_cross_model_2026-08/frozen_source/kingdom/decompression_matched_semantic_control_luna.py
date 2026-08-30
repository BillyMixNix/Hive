"""Hive Experiment 3: matched-size nonsemantic control for K/A/S semantics.

The experiment compares the exact Study-2 C1 and KAS- packets with M3, a
query-blind packet that restores three opaque columns and exactly the same
serialized byte count as C1 without retaining any kind/authority/status value.
"""

from __future__ import annotations

import argparse
import copy
import inspect
import json
import re
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_semantic_authority_luna as study2_v1
from kingdom import decompression_semantic_authority_luna_v1_1 as study2_v11
from kingdom import decompression_semantic_authority_luna_v1_2 as study2
from kingdom import decompression_test as worlds
from kingdom import decompression_test_v2 as grading


PROTOCOL_ID = "hive-luna-matched-size-semantic-control-v1"
PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = 1
RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/"
    "luna-matched-size-semantic-control-v1-001"
)
ACKNOWLEDGEMENT = "--acknowledge-frozen-matched-semantic-control-v1"

SEALED_STUDY2_CHECKPOINT = "7b13c99c237315fb6a6330f3607c3591edeaa9c5"
SEALED_STUDY2_IMPLEMENTATION = "7e3f35e1d8b135fa2cfc7a6e36090b68a7e60e82"
SEALED_STUDY2_EVIDENCE = "3e3a746061bc72f3b052c607259178c262bd952a"
SEALED_STUDY2_TREE = "f0db41367d55f4ea8ad063abeabc07b395c1f157"
SEALED_STUDY2_RESULT_SHA256 = (
    "f92398a86d513d1dd8bbc66184e4d57dfd6f770b3e51b2ac078341868d092dbd"
)
SEALED_STUDY2_INDEX_SHA256 = (
    "1b99589d6ef9c1c3341c3e45531cec77a7670b68830d6ed2e1fa5c955d7361ec"
)
SEALED_STUDY2_RUN_DIR = Path(
    ".hive/benchmarks/decompression_test/"
    "luna-semantic-authority-decomposition-v1-2-001"
)

MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 16_384
TIMEOUT_SECONDS = 900
AUTHORIZED_COST_CEILING_USD = 100.0
INPUT_USD_PER_MILLION = study2_v1.INPUT_USD_PER_MILLION
OUTPUT_USD_PER_MILLION = study2_v1.OUTPUT_USD_PER_MILLION

REPLICATION_COUNT = 8
BATCHES_PER_CONDITION = 6
CONDITIONS = ("C1", "M3", "KAS-")
CASES_PER_CONDITION = 20
TRIALS_PER_CONDITION = REPLICATION_COUNT * CASES_PER_CONDITION
CALLS_PER_REPLICATION = len(CONDITIONS) * BATCHES_PER_CONDITION
MAX_GENERATION_CALLS = REPLICATION_COUNT * CALLS_PER_REPLICATION
BASELINE_STABILITY_MIN_CORRECT = 144
APPROXIMATE_C1_MAX_AGGREGATE_DEFICIT = 4

C1_COLUMNS = (
    "ref",
    "effective_t",
    "kind",
    "authority",
    "status",
    "requires",
    "effects",
)
KAS_COLUMNS = ("ref", "effective_t", "requires", "effects")

# These identifiers are deliberately punctuation-only.  Their combined UTF-8
# length is 19 bytes, matching kind/authority/status in aggregate, but their
# individual 1/7/11 lengths do not reveal the semantic names' 4/9/6 fingerprint.
# Their values are fixed one-byte punctuation, matching the aggregate size—but
# never the meaning—of every frozen K/A/S row.  Positions mirror C1 so M3 is the
# strongest formatting-only control without an opaque substitution cipher.
M3_FIELDS = ("_", "_______", "___________")
M3_VALUES = ("~", "^", "%")
M3_COLUMNS = (
    "ref",
    "effective_t",
    M3_FIELDS[0],
    M3_FIELDS[1],
    M3_FIELDS[2],
    "requires",
    "effects",
)
CONDITION_COLUMNS = {
    "C1": C1_COLUMNS,
    "M3": M3_COLUMNS,
    "KAS-": KAS_COLUMNS,
}

# Each replication uses all six permutations once.  Consequently every
# condition occupies every ordinal position exactly twice per replication and
# each pair precedes the other exactly three times.  Replication rotations
# prevent a frozen batch from always receiving the same first permutation.
_ORDER_CYCLE = (
    ("C1", "M3", "KAS-"),
    ("M3", "KAS-", "C1"),
    ("KAS-", "C1", "M3"),
    ("KAS-", "M3", "C1"),
    ("C1", "KAS-", "M3"),
    ("M3", "C1", "KAS-"),
)
CONDITION_SCHEDULE = tuple(
    tuple(
        _ORDER_CYCLE[(batch_index + replication_index) % len(_ORDER_CYCLE)]
        for batch_index in range(BATCHES_PER_CONDITION)
    )
    for replication_index in range(REPLICATION_COUNT)
)

# Filled from deterministic preflight before the implementation commit.
FROZEN_SCHEDULE_SHA256 = (
    "3263572168bdf2d2b1f5dad34441aa9bdf09ed1c9faff6a6a694dabf72f4ce58"
)
FROZEN_M3_CONSTRUCTION_SHA256 = (
    "0f0b82917eb89aefd7905cc711a68c2478c060fb0b99611a1e254fe43f4e2b74"
)
FROZEN_REQUEST_PLAN_SHA256 = (
    "56fd5abc0c8625d3c7e46022b3959ef49c9ec4a62191441b1a47768a0c631a46"
)
FROZEN_SOLVER_CONFIG_SHA256 = (
    "0fa9c5f438388516fd4ac130c44320f08cafb7bddbad6e102444326c56a04b54"
)
FROZEN_INPUT_TOKEN_UPPER_BOUND = 3_886_160
FROZEN_OUTPUT_TOKEN_UPPER_BOUND = MAX_GENERATION_CALLS * MAX_OUTPUT_TOKENS
FROZEN_COST_UPPER_BOUND_USD = 3.6083871999999997

MODULE_PATH = "kingdom/decompression_matched_semantic_control_luna.py"
TEST_PATH = "tests/test_decompression_matched_semantic_control_luna.py"
PROTOCOL_PATH = (
    "benchmarks/decompression_test/PROTOCOL_MATCHED_SEMANTIC_CONTROL_LUNA_V1.md"
)
SOURCE_FILES = tuple(
    dict.fromkeys((*study2.SOURCE_FILES, MODULE_PATH, TEST_PATH, PROTOCOL_PATH))
)

PRIMARY_COMPARISON = "H_M3_VS_C1"
SECONDARY_COMPARISON = "E_M3_VS_KAS"
CONTROL_COMPARISON = "G_C1_VS_KAS"

VALID_DISPOSITIONS = (
    "VALID_SUPPORTED_SEMANTIC_CONTROL",
    "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED",
    "VALID_MIXED_RESULT",
    "VALID_INCONCLUSIVE",
    "INVALID_APPARATUS",
)


def solver_config():
    return study2_v1.FrozenSolverConfig(
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


def _canonical_detached(value: Any) -> Any:
    """Return a recursively detached, insertion-order-independent JSON value."""

    return json.loads(luna_v1._canonical_json(value))


def _m3_filler_rows(record_count: int) -> tuple[tuple[str, str, str], ...]:
    """Generate filler using only a nonsemantic structural row count."""

    if type(record_count) is not int or record_count <= 0:
        raise ValueError("record_count must be a positive integer")
    return tuple(tuple(M3_VALUES) for _row_ordinal in range(record_count))


def _validate_source_packet(packet: Mapping[str, Any]) -> None:
    if set(packet) != {"format", "record_columns", "records"}:
        raise ValueError("C1 source packet has missing or unknown fields")
    if packet["format"] != "compact_named_columns_frontier_v1":
        raise ValueError("C1 source packet format changed")
    if tuple(packet["record_columns"]) != C1_COLUMNS:
        raise ValueError("projection must start from exact C1 columns")
    records = packet["records"]
    if not isinstance(records, list) or not records:
        raise ValueError("C1 source records must be a nonempty list")
    if any(not isinstance(row, list) or len(row) != len(C1_COLUMNS) for row in records):
        raise ValueError("C1 source record width changed")


def project_packet(packet: Mapping[str, Any], condition: str) -> dict[str, Any]:
    """Create C1, KAS-, or M3 using no query, oracle, or model information."""

    if condition not in CONDITIONS:
        raise ValueError(f"unknown matched-control condition {condition!r}")
    _validate_source_packet(packet)
    source = _canonical_detached(packet)
    if condition == "C1":
        projected = source
    else:
        keep = tuple(C1_COLUMNS.index(name) for name in KAS_COLUMNS)
        kas_records = [
            [_canonical_detached(row[index]) for index in keep]
            for row in source["records"]
        ]
        if condition == "KAS-":
            projected = {
                "format": source["format"],
                "record_columns": list(KAS_COLUMNS),
                "records": kas_records,
            }
        else:
            fillers = _m3_filler_rows(len(kas_records))
            projected = {
                "format": source["format"],
                "record_columns": list(M3_COLUMNS),
                "records": [
                    [
                        _canonical_detached(row[0]),
                        _canonical_detached(row[1]),
                        filler[0],
                        filler[1],
                        filler[2],
                        _canonical_detached(row[2]),
                        _canonical_detached(row[3]),
                    ]
                    for row, filler in zip(kas_records, fillers)
                ],
            }
    detached = _canonical_detached(projected)
    validate_projection(detached, condition=condition)
    return detached


def validate_projection(packet: Mapping[str, Any], *, condition: str) -> None:
    if condition not in CONDITIONS:
        raise ValueError("condition identifier is not canonical")
    if set(packet) != {"format", "record_columns", "records"}:
        raise ValueError("projected packet has missing or unknown fields")
    if packet["format"] != "compact_named_columns_frontier_v1":
        raise ValueError("projected packet format mismatch")
    columns = tuple(packet["record_columns"])
    if columns != CONDITION_COLUMNS[condition]:
        raise ValueError("projected columns differ from the frozen condition")
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
        if condition == "C1":
            if row["kind"] not in set(worlds._KIND_CODES.values()):
                raise ValueError("projected kind code is invalid")
            if row["authority"] not in set(worlds._AUTHORITY_CODES.values()):
                raise ValueError("projected authority code is invalid")
            if row["status"] not in set(worlds._STATUS_CODES.values()):
                raise ValueError("projected status code is invalid")
        if condition == "M3" and tuple(row[name] for name in M3_FIELDS) != M3_VALUES:
            raise ValueError("M3 filler values differ from the frozen opaque tuple")
        for name in ("requires", "effects"):
            atoms = row.get(name)
            if not isinstance(atoms, list) or any(
                not isinstance(atom, list) or len(atom) != 3 for atom in atoms
            ):
                raise ValueError(f"projected {name} atoms are invalid")


def _c1_packet(case: worlds.BenchmarkCase) -> dict[str, Any]:
    return luna_v1.transform_compact_packet(worlds.compressed_packet(case), "C1")


def batch_representations(
    cases: Sequence[worlds.BenchmarkCase], condition: str
) -> tuple[dict[str, Any], ...]:
    return tuple(project_packet(_c1_packet(case), condition) for case in cases)


def build_solver_prompt(
    cases: Sequence[worlds.BenchmarkCase], condition: str
) -> str:
    representations = batch_representations(cases, condition)
    items = []
    for case, representation in zip(cases, representations):
        item = worlds._case_prompt_payload(case, "compressed")
        item["representation"] = representation
        items.append(item)
    payload = {
        "representation_family": "compact_named_column_records",
        "cases": items,
    }
    return luna_v1.SOLVER_PROMPT_PREFIX + "\nINPUT:\n" + luna_v1._pretty_json(payload)


def build_call_plan(
    payload: Mapping[str, Any], cases: Sequence[worlds.BenchmarkCase]
) -> tuple[study2_v1.ExperimentCall, ...]:
    by_case = {case.case_id: case for case in cases}
    calls: list[study2_v1.ExperimentCall] = []
    sequence = 1
    for replication in range(1, REPLICATION_COUNT + 1):
        for batch_index, batch in enumerate(payload["batches"]):
            condition_order = CONDITION_SCHEDULE[replication - 1][batch_index]
            batch_cases = tuple(by_case[str(case_id)] for case_id in batch["case_ids"])
            for position, condition in enumerate(condition_order, start=1):
                calls.append(
                    study2_v1.ExperimentCall(
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
        raise luna_v1.ApparatusFailure("call plan is not exactly 144 calls")
    return tuple(calls)


def _request_payload(call: study2_v1.ExperimentCall, config) -> dict[str, Any]:
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


def _git(repo_root: Path, *args: str, check: bool = True):
    return study2_v11._git(repo_root, *args, check=check)


def verify_sealed_study2(repo_root: Path) -> Mapping[str, Any]:
    resolved = {
        "starting_checkpoint": _git(
            repo_root, "rev-parse", f"{SEALED_STUDY2_CHECKPOINT}^{{commit}}"
        ).stdout.strip(),
        "implementation": _git(
            repo_root, "rev-parse", f"{SEALED_STUDY2_IMPLEMENTATION}^{{commit}}"
        ).stdout.strip(),
        "evidence": _git(
            repo_root, "rev-parse", f"{SEALED_STUDY2_EVIDENCE}^{{commit}}"
        ).stdout.strip(),
    }
    if resolved != {
        "starting_checkpoint": SEALED_STUDY2_CHECKPOINT,
        "implementation": SEALED_STUDY2_IMPLEMENTATION,
        "evidence": SEALED_STUDY2_EVIDENCE,
    }:
        raise luna_v1.ApparatusFailure("Study-2 lineage commits did not resolve")
    parents = _git(
        repo_root, "show", "-s", "--format=%P", SEALED_STUDY2_EVIDENCE
    ).stdout.strip().split()
    if parents != [SEALED_STUDY2_IMPLEMENTATION]:
        raise luna_v1.ApparatusFailure("Study-2 evidence parent changed")
    if _git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        SEALED_STUDY2_CHECKPOINT,
        SEALED_STUDY2_IMPLEMENTATION,
        check=False,
    ).returncode != 0:
        raise luna_v1.ApparatusFailure("Study-2 implementation lost checkpoint ancestry")
    current = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if _git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        SEALED_STUDY2_EVIDENCE,
        current,
        check=False,
    ).returncode != 0:
        raise luna_v1.ApparatusFailure("current work does not descend from sealed Study 2")
    tree = _git(
        repo_root,
        "rev-parse",
        f"{SEALED_STUDY2_EVIDENCE}:{SEALED_STUDY2_RUN_DIR.as_posix()}",
    ).stdout.strip()
    if tree != SEALED_STUDY2_TREE:
        raise luna_v1.ApparatusFailure("sealed Study-2 evidence tree changed")
    run_dir = repo_root / SEALED_STUDY2_RUN_DIR
    result_hash = luna_v1._sha256_bytes((run_dir / "RESULT.json").read_bytes())
    index_hash = luna_v1._sha256_bytes((run_dir / "EVIDENCE_INDEX.json").read_bytes())
    if (
        result_hash != SEALED_STUDY2_RESULT_SHA256
        or index_hash != SEALED_STUDY2_INDEX_SHA256
    ):
        raise luna_v1.ApparatusFailure("sealed Study-2 physical hashes changed")
    verified = study2.verify_run(run_dir)
    prior = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    if (
        not verified.get("verified")
        or verified.get("validity") != "VALID"
        or verified.get("result_code") != "VALID_SUPPORTED_MULTIFIELD_INTERACTION"
        or prior["conditions"]["C1"]["exact_correct"] != 160
        or prior["conditions"]["KAS-"]["exact_correct"] != 26
        or prior["secondary_interactions"]["I_KAS"]["p_value"] != 0.0078125
        or prior["secondary_interactions"]["I_KAS"]["holm_adjusted_p_value"]
        != 0.03125
    ):
        raise luna_v1.ApparatusFailure("sealed Study-2 result no longer verifies")
    return {
        **resolved,
        "current_revision": current,
        "evidence_tree": tree,
        "result_sha256": result_hash,
        "evidence_index_sha256": index_hash,
        "verification": verified,
    }


def _freeze_chronology(repo_root: Path) -> Mapping[str, Any]:
    protocol_commit = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    implementation_commit = _git(repo_root, "rev-parse", "HEAD^").stdout.strip()
    implementation_parent = _git(repo_root, "rev-parse", "HEAD^^").stdout.strip()
    protocol_paths = _git(
        repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).stdout.splitlines()
    implementation_paths = _git(
        repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD^"
    ).stdout.splitlines()
    if implementation_parent != SEALED_STUDY2_EVIDENCE:
        raise luna_v1.ApparatusFailure("Experiment-3 implementation parent is not Study 2")
    if sorted(implementation_paths) != sorted((MODULE_PATH, TEST_PATH)):
        raise luna_v1.ApparatusFailure("implementation commit is not code/tests only")
    if protocol_paths != [PROTOCOL_PATH]:
        raise luna_v1.ApparatusFailure("freeze commit is not protocol-only")
    return {
        "implementation_commit": implementation_commit,
        "implementation_parent": implementation_parent,
        "implementation_paths": sorted(implementation_paths),
        "protocol_commit": protocol_commit,
        "protocol_parent": implementation_commit,
        "protocol_paths": protocol_paths,
    }


def _git_revision_and_sources(repo_root: Path):
    revision, sha256, blob_oids = study2_v11._source_maps(repo_root, SOURCE_FILES)
    return revision, sha256, blob_oids


def _assert_sources_unchanged(repo_root: Path, preflight: Mapping[str, Any]) -> None:
    if preflight.get("source_revision") == "TEST_UNCOMMITTED":
        return
    study2_v11._assert_sources_unchanged(repo_root, preflight, SOURCE_FILES)


def _prior_prompt_map(repo_root: Path) -> Mapping[tuple[str, int], str]:
    prompts: dict[tuple[str, int], set[str]] = {
        (condition, batch_id): set()
        for condition in ("C1", "KAS-")
        for batch_id in range(1, BATCHES_PER_CONDITION + 1)
    }
    for path in sorted((repo_root / SEALED_STUDY2_RUN_DIR / "calls").glob("call_*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        key = (str(artifact["condition"]), int(artifact["batch_id"]))
        if key in prompts:
            prompts[key].add(str(artifact["request"]["prompt"]))
    if any(len(values) != 1 for values in prompts.values()):
        raise luna_v1.ApparatusFailure("Study-2 control prompts are missing or unstable")
    return {key: next(iter(values)) for key, values in prompts.items()}


def _m3_construction_contract() -> Mapping[str, Any]:
    signature = inspect.signature(_m3_filler_rows)
    if tuple(signature.parameters) != ("record_count",):
        raise luna_v1.ApparatusFailure("M3 filler generator gained a semantic input")
    source = inspect.getsource(_m3_filler_rows)
    forbidden = {
        "kind",
        "authority",
        "status",
        "question",
        "options",
        "oracle",
        "correct_choice",
        "required_event_refs",
        "requires",
        "effects",
        "model_output",
        "grader",
        "decoy",
    }
    identifiers = {
        token.casefold() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", source)
    }
    leaked = sorted(forbidden & identifiers)
    if leaked:
        raise luna_v1.ApparatusFailure(f"M3 generator references forbidden inputs: {leaked}")
    semantic_names = ("kind", "authority", "status")
    all_codes = tuple(
        dict.fromkeys(
            (
                *worlds._KIND_CODES.values(),
                *worlds._AUTHORITY_CODES.values(),
                *worlds._STATUS_CODES.values(),
            )
        )
    )
    control_name_lengths = [len(name.encode("utf-8")) for name in M3_FIELDS]
    semantic_name_lengths = [len(name.encode("utf-8")) for name in semantic_names]
    if (
        sum(control_name_lengths) != sum(semantic_name_lengths)
        or control_name_lengths == semantic_name_lengths
        or len(set(M3_FIELDS)) != 3
    ):
        raise luna_v1.ApparatusFailure(
            "opaque M3 names must match only the aggregate semantic-name budget"
        )
    if any(
        len(value.encode("utf-8")) != 1
        or len(json.dumps(value, ensure_ascii=False).encode("utf-8")) != 3
        for value in (*all_codes, *M3_VALUES)
    ):
        raise luna_v1.ApparatusFailure("frozen semantic/control values are not one raw byte")
    generated = (*M3_FIELDS, *M3_VALUES)
    if any(any(character.isalnum() for character in value) for value in generated):
        raise luna_v1.ApparatusFailure("M3 keys or values contain semantic-vocabulary tokens")
    payload = {
        "generator_parameters": list(signature.parameters),
        "field_names": list(M3_FIELDS),
        "field_name_utf8_lengths": control_name_lengths,
        "field_name_length_matching": "aggregate_only_not_positionwise",
        "field_name_total_utf8_bytes": sum(control_name_lengths),
        "values": list(M3_VALUES),
        "value_utf8_lengths": [len(value.encode("utf-8")) for value in M3_VALUES],
        "semantic_field_name_utf8_lengths": semantic_name_lengths,
        "semantic_field_name_total_utf8_bytes": sum(semantic_name_lengths),
        "all_frozen_semantic_codes_are_one_unescaped_ascii_byte": True,
        "semantic_vocabulary_rule": (
            "generated keys/values must contain zero Unicode alphanumeric characters; "
            "therefore every benchmark/category token including one-character codes is excluded"
        ),
        "generated_alphanumeric_tokens": [],
        "source_sha256": luna_v1._sha256_text(source),
    }
    return payload


def _representation_batch_bytes(packets: Sequence[Mapping[str, Any]]) -> int:
    return len(luna_v1._canonical_json(list(packets)).encode("utf-8"))


def _derive_preflight(
    repo_root: Path, *, require_committed: bool
) -> tuple[
    Mapping[str, Any],
    tuple[worlds.BenchmarkCase, ...],
    tuple[study2_v1.ExperimentCall, ...],
    Mapping[str, Any],
]:
    lineage = verify_sealed_study2(repo_root)
    freeze = _freeze_chronology(repo_root) if require_committed else {
        "implementation_commit": "TEST_UNCOMMITTED",
        "protocol_commit": "TEST_UNCOMMITTED",
    }
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
    positional_counts = {
        condition: [0, 0, 0] for condition in CONDITIONS
    }
    precedence = {
        f"{left}_before_{right}": 0
        for left in CONDITIONS
        for right in CONDITIONS
        if left != right
    }
    for replication_schedule in CONDITION_SCHEDULE:
        if sorted(replication_schedule) != sorted(_ORDER_CYCLE):
            raise luna_v1.ApparatusFailure("a replication does not use all six permutations")
        for order in replication_schedule:
            if len(order) != 3 or set(order) != set(CONDITIONS):
                raise luna_v1.ApparatusFailure("condition schedule contains a non-permutation")
            for position, condition in enumerate(order):
                positional_counts[condition][position] += 1
            for left in CONDITIONS:
                for right in CONDITIONS:
                    if left != right and order.index(left) < order.index(right):
                        precedence[f"{left}_before_{right}"] += 1
    if any(counts != [16, 16, 16] for counts in positional_counts.values()):
        raise luna_v1.ApparatusFailure("condition ordinal positions are not exactly balanced")
    if any(value != 24 for value in precedence.values()):
        raise luna_v1.ApparatusFailure("pairwise condition precedence is not exactly balanced")

    construction = _m3_construction_contract()
    construction_hash = luna_v1._sha256_text(luna_v1._canonical_json(construction))
    prior_prompts = _prior_prompt_map(repo_root)
    by_case = {case.case_id: case for case in cases}
    size_rows = []
    representation_by_case: dict[str, dict[str, int]] = {
        case.case_id: {} for case in cases
    }
    prompt_equivalence = []
    for batch in payload["batches"]:
        batch_cases = tuple(by_case[str(case_id)] for case_id in batch["case_ids"])
        batch_id = int(batch["batch_id"])
        packets = {
            condition: batch_representations(batch_cases, condition)
            for condition in CONDITIONS
        }
        for case_index, case in enumerate(batch_cases):
            source = _c1_packet(case)
            source_before = _canonical_detached(source)
            outputs = {
                condition: project_packet(source, condition) for condition in CONDITIONS
            }
            if source != source_before:
                raise luna_v1.ApparatusFailure("condition projection mutated its source")
            # Arbitrary K/A/S changes cannot affect M3 because the three values
            # are deleted before fixed opaque fields are attached.
            mutated = _canonical_detached(source)
            for row_index, row in enumerate(mutated["records"]):
                row[2] = f"arbitrary_kind_{row_index}"
                row[3] = f"arbitrary_authority_{row_index}"
                row[4] = f"arbitrary_status_{row_index}"
            if project_packet(mutated, "M3") != outputs["M3"]:
                raise luna_v1.ApparatusFailure("M3 changed under counterfactual K/A/S values")
            kas_from_m3 = {
                "format": outputs["M3"]["format"],
                "record_columns": list(KAS_COLUMNS),
                "records": [
                    [row[0], row[1], row[5], row[6]]
                    for row in outputs["M3"]["records"]
                ],
            }
            if _canonical_detached(kas_from_m3) != outputs["KAS-"]:
                raise luna_v1.ApparatusFailure("M3 differs from KAS- beyond opaque fields")
            for condition, packet in outputs.items():
                representation_by_case[case.case_id][condition] = len(
                    luna_v1._canonical_json(packet).encode("utf-8")
                )
            if representation_by_case[case.case_id]["M3"] != representation_by_case[
                case.case_id
            ]["C1"]:
                raise luna_v1.ApparatusFailure("M3 and C1 case bytes are not exactly equal")
            if packets["M3"][case_index] != outputs["M3"]:
                raise luna_v1.ApparatusFailure("M3 projection is nondeterministic")
        batch_bytes = {
            condition: _representation_batch_bytes(packets[condition])
            for condition in CONDITIONS
        }
        prompts = {
            condition: build_solver_prompt(batch_cases, condition)
            for condition in CONDITIONS
        }
        prompt_bytes = {
            condition: len(prompt.encode("utf-8"))
            for condition, prompt in prompts.items()
        }
        if batch_bytes["M3"] != batch_bytes["C1"] or prompt_bytes["M3"] != prompt_bytes["C1"]:
            raise luna_v1.ApparatusFailure("M3/C1 exact size match failed")
        if prompts["C1"] != prior_prompts[("C1", batch_id)]:
            raise luna_v1.ApparatusFailure("C1 prompt differs from sealed Study 2")
        if prompts["KAS-"] != prior_prompts[("KAS-", batch_id)]:
            raise luna_v1.ApparatusFailure("KAS- prompt differs from sealed Study 2")
        for condition, prompt in prompts.items():
            if any(marker in prompt for marker in ('"condition":', '"C1"', '"M3"', '"KAS-"')):
                raise luna_v1.ApparatusFailure("solver prompt exposes condition identity")
        size_rows.append(
            {
                "batch_id": batch_id,
                "case_ids": list(batch["case_ids"]),
                "canonical_representation_list_utf8_bytes": batch_bytes,
                "complete_prompt_utf8_bytes": prompt_bytes,
                "m3_minus_c1_absolute_bytes": batch_bytes["M3"] - batch_bytes["C1"],
                "m3_minus_c1_percentage": 100
                * (batch_bytes["M3"] - batch_bytes["C1"])
                / batch_bytes["C1"],
            }
        )
        prompt_equivalence.append(
            {
                "batch_id": batch_id,
                "c1_equals_study2": True,
                "kas_equals_study2": True,
                "m3_prompt_bytes_equal_c1": True,
            }
        )

    # Query-blind projection: replace every query/grading/decoy-facing field
    # while holding events fixed and compare representation bytes only.
    from dataclasses import replace

    for case in cases:
        altered = replace(
            case,
            question="query-blindness sentinel",
            options={"A": "x", "B": "y", "C": "z", "D": "w"},
            correct_choice="D" if case.correct_choice != "D" else "A",
            reasoning_code="query_blindness_sentinel",
            required_event_refs=("changed",),
            allowed_event_refs=("changed",),
            rejected_event_refs=("changed",),
            current_claim_ids=("changed",),
        )
        for condition in CONDITIONS:
            if batch_representations((case,), condition) != batch_representations(
                (altered,), condition
            ):
                raise luna_v1.ApparatusFailure(
                    f"{condition} projection depends on query/grading metadata"
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
    plan_hash = luna_v1._sha256_text(luna_v1._canonical_json(request_rows))
    for replication in range(1, REPLICATION_COUNT + 1):
        selected = [call for call in calls if call.replication == replication]
        if len(selected) != CALLS_PER_REPLICATION:
            raise luna_v1.ApparatusFailure("replication does not contain exactly 18 calls")
        for condition in CONDITIONS:
            condition_calls = [call for call in selected if call.condition == condition]
            if [call.batch_id for call in condition_calls] != list(
                range(1, BATCHES_PER_CONDITION + 1)
            ):
                raise luna_v1.ApparatusFailure("within-condition batch order changed")
            if sum(len(call.case_ids) for call in condition_calls) != CASES_PER_CONDITION:
                raise luna_v1.ApparatusFailure("condition does not cover all 20 worlds")

    output_upper = MAX_GENERATION_CALLS * MAX_OUTPUT_TOKENS
    cost_upper = (
        input_upper * INPUT_USD_PER_MILLION / 1_000_000
        + output_upper * OUTPUT_USD_PER_MILLION / 1_000_000
    )
    if cost_upper > AUTHORIZED_COST_CEILING_USD:
        raise luna_v1.ApparatusFailure("cost upper bound exceeds $100 authorization")
    if require_committed:
        revision, sources, blob_oids = _git_revision_and_sources(repo_root)
    else:
        revision = "TEST_UNCOMMITTED"
        sources = {relative: "TEST_UNCOMMITTED" for relative in SOURCE_FILES}
        blob_oids = {relative: "TEST_UNCOMMITTED" for relative in SOURCE_FILES}

    prior_result = json.loads(
        (repo_root / study2_v1.SEALED_V1_3_DIR / "RESULT.json").read_text(
            encoding="utf-8"
        )
    )
    raw_state = int(prior_result["representation_utf8_bytes"]["raw"])
    raw_input_total = int(
        prior_result["usage"]["by_condition"]["raw_capability"]["input_tokens"]
    )
    raw_replications = int(prior_result["replication_count"])
    state_totals = {
        condition: sum(row[condition] for row in representation_by_case.values())
        for condition in CONDITIONS
    }
    preflight = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "source_revision": revision,
        "source_file_sha256": sources,
        "source_file_git_blob_oid": blob_oids,
        "source_guard": {
            "version": "direct-crlf-normalized-bytes-v1.1",
            "head_revision_required": True,
            "head_blob_must_match_preflight": True,
            "direct_worktree_crlf_to_lf_must_equal_committed_bytes": True,
            "canonical_git_show_sha256_must_match_preflight": True,
        },
        "lineage": lineage,
        "freeze_chronology": freeze,
        "case_pack_sha256": luna_v1.FROZEN_CASE_PACK_SHA256,
        "expanded_pack_sha256": expanded_hash,
        "solver_prompt_template_sha256": luna_v1._sha256_text(
            luna_v1.SOLVER_PROMPT_PREFIX
        ),
        "solver_config": config.to_mapping(),
        "solver_config_sha256": config.configuration_hash,
        "estimand": (
            "Expected solver accuracy on these fixed 20 benchmark worlds under "
            "repeated stochastic inference using the frozen Luna configuration."
        ),
        "inferential_unit": "complete_20_world_stochastic_replication",
        "fixed_worlds_not_independent_population_samples": True,
        "within_call_batch_dependence_disclosed": True,
        "conditions": {
            "C1": {"columns": list(C1_COLUMNS), "role": "semantic_control"},
            "KAS-": {"columns": list(KAS_COLUMNS), "role": "bundle_removed"},
            "M3": {
                "columns": list(M3_COLUMNS),
                "role": "matched_size_nonsemantic_control",
            },
        },
        "m3_construction": construction,
        "m3_construction_sha256": construction_hash,
        "semantic_independence": True,
        "query_blindness": True,
        "recursive_detachment_and_canonicalization": True,
        "condition_isolation": True,
        "size_match_boundary": (
            "canonical UTF-8 JSON of ordered representation-object list per batch"
        ),
        "size_match_tolerance_bytes": 0,
        "size_rows": size_rows,
        "prompt_equivalence": prompt_equivalence,
        "representation_utf8_bytes_by_case": representation_by_case,
        "representation_utf8_bytes_per_20_world_replication": state_totals,
        "condition_schedule": [
            [list(order) for order in replication]
            for replication in CONDITION_SCHEDULE
        ],
        "condition_schedule_sha256": schedule_hash,
        "ordinal_position_counts": positional_counts,
        "pairwise_precedence_counts": precedence,
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
        "fail_closed_on_any_call_failure": True,
        "statistics": {
            "primary": {
                "id": PRIMARY_COMPARISON,
                "difference": "M3_correct_minus_C1_correct_out_of_20",
                "test": "exact_two_sided_replication_sign_flip_2^8",
                "alpha": 0.05,
                "multiplicity_adjustment": None,
                "requires_all_eight_complete_pairs": True,
            },
            "secondary": {
                "id": SECONDARY_COMPARISON,
                "difference": "M3_correct_minus_KAS_correct_out_of_20",
                "test": "exact_two_sided_replication_sign_flip_2^8",
                "role": "preregistered_secondary_mechanistic",
                "multiplicity_adjustment": None,
                "may_inform_frozen_outcome_classification": True,
                "requires_all_eight_complete_pairs": True,
            },
            "control_gate": {
                "id": CONTROL_COMPARISON,
                "difference": "KAS_correct_minus_C1_correct_out_of_20",
                "requires_harmful_two_sided_p_at_most": 0.05,
            },
            "sign_flip_assumption": (
                "paired condition-label differences are exchangeable under the sharp null; "
                "the target is these fixed worlds/calls, with within-batch dependence absorbed "
                "inside each complete 20-world replication"
            ),
            "zero_differences_remain_in_all_256_assignments": True,
            "case_rows_are_not_inferential_samples": True,
            "baseline_drift_trigger": "C1 exact_correct < 144/160",
            "non_rejection_is_not_equivalence": True,
            "approximately_c1_descriptive_rule": (
                "C1_correct_minus_M3_correct <= 4 answers across 160; this is not "
                "a statistical equivalence test"
            ),
            "approximately_c1_max_aggregate_deficit_answers": (
                APPROXIMATE_C1_MAX_AGGREGATE_DEFICIT
            ),
        },
        "frozen_interpretation": {
            "control_or_baseline_failure": "VALID_INCONCLUSIVE",
            "m3_aggregate_below_kas": {
                "result_code": "VALID_INCONCLUSIVE",
                "outcome": "CONTROL_DISTRACTION_M3_BELOW_KAS",
            },
            "harmful_primary_and_positive_secondary": "VALID_MIXED_RESULT",
            "harmful_primary_otherwise": "VALID_SUPPORTED_SEMANTIC_CONTROL",
            "nonharmful_primary_positive_secondary_and_m3_within_four_of_c1": (
                "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED"
            ),
            "nonharmful_primary_positive_secondary_but_m3_more_than_four_below_c1": (
                "VALID_INCONCLUSIVE"
            ),
            "significantly_positive_primary": "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED",
            "otherwise": "VALID_INCONCLUSIVE",
        },
        "frozen_raw_reference": {
            "representation_utf8_bytes_per_replication": raw_state,
            "input_tokens_across_six_v1_3_replications": raw_input_total,
            "replication_count": raw_replications,
            "input_tokens_per_replication_mean": raw_input_total / raw_replications,
            "comparison_note": (
                "State byte ratios are deterministic; API token ratios use a sealed "
                "noncontemporaneous Raw reference."
            ),
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
                "Exact serialized request UTF-8 bytes are a conservative tokenizer-independent "
                "input-token upper bound; provider usage is authoritative."
            ),
        },
    }
    return payload, cases, calls, luna_v1._sealed(preflight)


def derived_frozen_values(repo_root: Path) -> Mapping[str, Any]:
    """Return deterministic constants used once while freezing implementation."""

    _payload, _cases, _calls, preflight = _derive_preflight(
        repo_root, require_committed=False
    )
    return {
        "schedule_sha256": preflight["condition_schedule_sha256"],
        "m3_construction_sha256": preflight["m3_construction_sha256"],
        "request_plan_sha256": preflight["request_plan_sha256"],
        "solver_config_sha256": preflight["solver_config_sha256"],
        "input_token_upper_bound": preflight["cost"][
            "request_utf8_bytes_input_token_upper_bound"
        ],
        "output_token_upper_bound": preflight["cost"]["output_token_upper_bound"],
        "cost_upper_bound_usd": preflight["cost"][
            "conservative_generation_cost_upper_bound_usd"
        ],
    }


def deterministic_preflight(
    repo_root: Path, *, require_committed: bool = True
):
    payload, cases, calls, preflight = _derive_preflight(
        repo_root, require_committed=require_committed
    )
    frozen = derived_frozen_values(repo_root) if require_committed else {
        "schedule_sha256": preflight["condition_schedule_sha256"],
        "m3_construction_sha256": preflight["m3_construction_sha256"],
        "request_plan_sha256": preflight["request_plan_sha256"],
        "solver_config_sha256": preflight["solver_config_sha256"],
        "input_token_upper_bound": preflight["cost"][
            "request_utf8_bytes_input_token_upper_bound"
        ],
        "output_token_upper_bound": preflight["cost"]["output_token_upper_bound"],
        "cost_upper_bound_usd": preflight["cost"][
            "conservative_generation_cost_upper_bound_usd"
        ],
    }
    expected = {
        "schedule_sha256": FROZEN_SCHEDULE_SHA256,
        "m3_construction_sha256": FROZEN_M3_CONSTRUCTION_SHA256,
        "request_plan_sha256": FROZEN_REQUEST_PLAN_SHA256,
        "solver_config_sha256": FROZEN_SOLVER_CONFIG_SHA256,
        "input_token_upper_bound": FROZEN_INPUT_TOKEN_UPPER_BOUND,
        "output_token_upper_bound": FROZEN_OUTPUT_TOKEN_UPPER_BOUND,
        "cost_upper_bound_usd": FROZEN_COST_UPPER_BOUND_USD,
    }
    if frozen != expected:
        raise luna_v1.ApparatusFailure(
            f"frozen Experiment-3 derived constants drifted: {frozen!r}"
        )
    return payload, cases, calls, preflight


def exact_comparison(
    left_scores: Sequence[int],
    right_scores: Sequence[int],
    *,
    comparison_id: str,
    difference_definition: str,
    inferential_role: str,
) -> Mapping[str, Any]:
    if len(left_scores) != REPLICATION_COUNT or len(right_scores) != REPLICATION_COUNT:
        raise ValueError("comparison requires eight complete replication scores per arm")
    differences = [
        int(left) - int(right) for left, right in zip(left_scores, right_scores)
    ]
    exact = study2_v1.exact_two_sided_sign_flip(differences)
    return {
        **exact,
        "comparison_id": comparison_id,
        "left_scores": list(left_scores),
        "right_scores": list(right_scores),
        "difference_definition": difference_definition,
        "effect": study2_v1._effect_summary(
            differences, definition=difference_definition
        ),
        "inferential_role": inferential_role,
        "alpha": 0.05,
        "multiplicity_adjustment": None,
        "requires_all_eight_complete_replications": True,
        "non_rejection_is_equivalence": False,
    }


def _usage_from_records(records: Sequence[Any]) -> Mapping[str, Any]:
    """Aggregate measured usage without inheriting Study 2's eight arms."""

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
        input_tokens = sum(
            measured_int(metadata(record), "input_tokens") for record in selected
        )
        output_tokens = sum(
            measured_int(metadata(record), "output_tokens") for record in selected
        )
        by_condition[condition_id] = {
            "call_artifacts": len(selected),
            "physical_generation_calls": sum(
                measured_int(metadata(record), "physical_attempts")
                for record in selected
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": sum(
                measured_int(metadata(record), "reasoning_tokens")
                for record in selected
            ),
            "total_tokens": input_tokens + output_tokens,
            "latency_seconds": sum(
                measured_float(metadata(record), "latency_seconds")
                for record in selected
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


def _classify_result(
    *,
    totals: Mapping[str, int],
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
    control: Mapping[str, Any],
) -> Mapping[str, Any]:
    baseline_drift = int(totals["C1"]) < BASELINE_STABILITY_MIN_CORRECT
    primary_mean = float(primary["effect"]["mean_answers_out_of_20"])
    secondary_mean = float(secondary["effect"]["mean_answers_out_of_20"])
    control_mean = float(control["effect"]["mean_answers_out_of_20"])
    primary_significant = float(primary["p_value"]) <= 0.05
    secondary_significant = float(secondary["p_value"]) <= 0.05
    control_adequate = float(control["p_value"]) <= 0.05 and control_mean < 0
    distraction = int(totals["M3"]) < int(totals["KAS-"])
    c1_minus_m3 = int(totals["C1"]) - int(totals["M3"])
    approximately_c1 = c1_minus_m3 <= APPROXIMATE_C1_MAX_AGGREGATE_DEFICIT

    if baseline_drift:
        code = "VALID_INCONCLUSIVE"
        outcome = "BASELINE_DRIFT"
        evidence = "INCONCLUSIVE"
    elif not control_adequate:
        code = "VALID_INCONCLUSIVE"
        outcome = "CONTEMPORANEOUS_CONTROL_NOT_REPLICATED"
        evidence = "INCONCLUSIVE"
    elif distraction:
        code = "VALID_INCONCLUSIVE"
        outcome = "CONTROL_DISTRACTION_M3_BELOW_KAS"
        evidence = "INCONCLUSIVE"
    elif primary_significant and primary_mean < 0 and secondary_significant and secondary_mean > 0:
        code = "VALID_MIXED_RESULT"
        outcome = "BOTH_STRUCTURE_AND_SEMANTICS_CONTRIBUTE"
        evidence = "SUPPORTED"
    elif primary_significant and primary_mean < 0:
        code = "VALID_SUPPORTED_SEMANTIC_CONTROL"
        outcome = "M3_FAILED_TO_RECOVER_C1"
        evidence = "SUPPORTED"
    elif primary_significant and primary_mean > 0:
        code = "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED"
        outcome = "M3_EXCEEDED_C1"
        evidence = "SUPPORTED"
    elif (
        not primary_significant
        and secondary_significant
        and secondary_mean > 0
        and approximately_c1
    ):
        code = "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED"
        outcome = "M3_NEAR_C1_AND_IMPROVED_OVER_KAS"
        evidence = "SUPPORTED"
    else:
        code = "VALID_INCONCLUSIVE"
        outcome = "NO_PREREGISTERED_INTERPRETATION_CLEARED"
        evidence = "INCONCLUSIVE"
    return {
        "result_code": code,
        "evidence_label": evidence,
        "outcome": outcome,
        "baseline_drift": baseline_drift,
        "baseline_threshold": "C1 exact_correct < 144/160",
        "contemporaneous_control_adequate": control_adequate,
        "primary_significant": primary_significant,
        "secondary_significant": secondary_significant,
        "m3_aggregate_below_kas": distraction,
        "c1_minus_m3_aggregate_correct": c1_minus_m3,
        "approximately_c1": approximately_c1,
        "approximately_c1_rule": (
            "C1_correct_minus_M3_correct <= 4 answers across 160; descriptive "
            "recovery criterion only, not a statistical equivalence test"
        ),
        "non_rejection_is_equivalence": False,
        "classification_was_frozen_before_inference": True,
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
    vectors = {condition: [] for condition in CONDITIONS}
    condition_summaries: dict[str, Mapping[str, Any]] = {}
    totals: dict[str, int] = {}
    for replication in range(1, REPLICATION_COUNT + 1):
        replication_scores[str(replication)] = {}
        for condition in CONDITIONS:
            selected = list(scores[replication][condition])
            if (
                len(selected) != CASES_PER_CONDITION
                or len({row.case_id for row in selected}) != CASES_PER_CONDITION
            ):
                raise luna_v1.ApparatusFailure(
                    f"replication {replication} {condition} is not one complete 20-world unit"
                )
            correct = sum(row.answer_correct is True for row in selected)
            replication_scores[str(replication)][condition] = correct
            vectors[condition].append(correct)

    for condition in CONDITIONS:
        all_scores = [
            score
            for replication in range(1, REPLICATION_COUNT + 1)
            for score in scores[replication][condition]
        ]
        summary = dict(
            study2_v1._score_summary(
                all_scores, by_case, expected_total=TRIALS_PER_CONDITION
            )
        )
        summary["exact_correct_by_replication"] = list(vectors[condition])
        summary["mean_correct_out_of_20"] = sum(vectors[condition]) / 8
        summary["parser_failures"] = 0
        summary["incomplete_responses"] = 0
        summary["transport_failures"] = 0
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

    primary = exact_comparison(
        vectors["M3"],
        vectors["C1"],
        comparison_id=PRIMARY_COMPARISON,
        difference_definition="M3_correct_minus_C1_correct_out_of_20",
        inferential_role="single_confirmatory_primary",
    )
    secondary = exact_comparison(
        vectors["M3"],
        vectors["KAS-"],
        comparison_id=SECONDARY_COMPARISON,
        difference_definition="M3_correct_minus_KAS_correct_out_of_20",
        inferential_role="preregistered_secondary_mechanistic",
    )
    control = exact_comparison(
        vectors["KAS-"],
        vectors["C1"],
        comparison_id=CONTROL_COMPARISON,
        difference_definition="KAS_correct_minus_C1_correct_out_of_20",
        inferential_role="contemporaneous_control_adequacy_gate",
    )
    classification = _classify_result(
        totals=totals, primary=primary, secondary=secondary, control=control
    )
    usage = _usage_from_records(records)
    state = preflight["representation_utf8_bytes_per_20_world_replication"]
    raw_state = preflight["frozen_raw_reference"][
        "representation_utf8_bytes_per_replication"
    ]
    raw_input_reference = (
        preflight["frozen_raw_reference"]["input_tokens_per_replication_mean"]
        * REPLICATION_COUNT
    )
    representation_metrics = {}
    for condition in CONDITIONS:
        condition_usage = usage["by_condition"][condition]
        visible = int(state[condition])
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
            "actual_api_cost_usd": condition_usage["estimated_generation_cost_usd"],
            "physical_generation_calls": condition_usage["physical_generation_calls"],
        }
    def record_metadata(record: Any) -> Mapping[str, Any]:
        return record.metadata if hasattr(record, "metadata") else record["metadata"]

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
        "primary_m3_vs_c1": primary,
        "secondary_m3_vs_kas": secondary,
        "control_c1_vs_kas": control,
        "classification": classification,
        "representation_metrics": representation_metrics,
        "size_match_rows": preflight["size_rows"],
        "usage": usage,
        "returned_model": sorted(
            {
                str(record_metadata(row).get("returned_model"))
                for row in records
                if record_metadata(row).get("returned_model")
            }
        ),
        "returned_service_tier": sorted(
            {
                str(record_metadata(row).get("returned_service_tier"))
                for row in records
                if record_metadata(row).get("returned_service_tier")
            }
        ),
        "claim_scope": (
            "only this frozen 20-world benchmark, exact C1/KAS-/M3 grammar, "
            "and frozen Luna solver configuration under eight stochastic replications"
        ),
        "evidence_interpretation": {
            "PROVEN": [
                "M3 is byte-matched, deterministic, query-blind, and semantically independent by construction"
            ],
            "SUPPORTED": [],
            "PLAUSIBLE": [],
            "SPECULATIVE": [
                "generalization beyond this benchmark, representation grammar, or solver"
            ],
            "NOT_ESTABLISHED": [
                "Hive generally",
                "learned abstraction",
                "transfer",
                "universal authority semantics",
                "AGI",
                "recursive improvement",
            ],
        },
    }


_PATCHED_V1_NAMES = (
    "PROTOCOL_ID",
    "PROTOCOL_VERSION",
    "SCHEMA_VERSION",
    "RUN_DIR",
    "MODEL",
    "REASONING_EFFORT",
    "MAX_OUTPUT_TOKENS",
    "TIMEOUT_SECONDS",
    "AUTHORIZED_COST_CEILING_USD",
    "REPLICATION_COUNT",
    "BATCHES_PER_CONDITION",
    "CONDITIONS",
    "CALLS_PER_REPLICATION",
    "MAX_GENERATION_CALLS",
    "CASES_PER_CONDITION",
    "TRIALS_PER_CONDITION",
    "BASELINE_STABILITY_MIN_CORRECT",
    "C1_COLUMNS",
    "CONDITION_COLUMNS",
    "CONDITION_SCHEDULE",
    "FROZEN_SCHEDULE_SHA256",
    "FROZEN_REQUEST_PLAN_SHA256",
    "SOURCE_FILES",
    "solver_config",
    "project_c1_packet",
    "validate_projection",
    "build_solver_prompt",
    "build_call_plan",
    "deterministic_preflight",
    "aggregate_valid_result",
    "_git_revision_and_sources",
    "_assert_sources_unchanged",
)


@contextmanager
def _activated_study2_core() -> Iterator[None]:
    replacements = {
        "PROTOCOL_ID": PROTOCOL_ID,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "SCHEMA_VERSION": SCHEMA_VERSION,
        "RUN_DIR": RUN_DIR,
        "MODEL": MODEL,
        "REASONING_EFFORT": REASONING_EFFORT,
        "MAX_OUTPUT_TOKENS": MAX_OUTPUT_TOKENS,
        "TIMEOUT_SECONDS": TIMEOUT_SECONDS,
        "AUTHORIZED_COST_CEILING_USD": AUTHORIZED_COST_CEILING_USD,
        "REPLICATION_COUNT": REPLICATION_COUNT,
        "BATCHES_PER_CONDITION": BATCHES_PER_CONDITION,
        "CONDITIONS": CONDITIONS,
        "CALLS_PER_REPLICATION": CALLS_PER_REPLICATION,
        "MAX_GENERATION_CALLS": MAX_GENERATION_CALLS,
        "CASES_PER_CONDITION": CASES_PER_CONDITION,
        "TRIALS_PER_CONDITION": TRIALS_PER_CONDITION,
        "BASELINE_STABILITY_MIN_CORRECT": BASELINE_STABILITY_MIN_CORRECT,
        "C1_COLUMNS": C1_COLUMNS,
        "CONDITION_COLUMNS": CONDITION_COLUMNS,
        "CONDITION_SCHEDULE": CONDITION_SCHEDULE,
        "FROZEN_SCHEDULE_SHA256": FROZEN_SCHEDULE_SHA256,
        "FROZEN_REQUEST_PLAN_SHA256": FROZEN_REQUEST_PLAN_SHA256,
        "SOURCE_FILES": SOURCE_FILES,
        "solver_config": solver_config,
        "project_c1_packet": project_packet,
        "validate_projection": validate_projection,
        "build_solver_prompt": build_solver_prompt,
        "build_call_plan": build_call_plan,
        "deterministic_preflight": deterministic_preflight,
        "aggregate_valid_result": aggregate_valid_result,
        "_git_revision_and_sources": lambda root: _git_revision_and_sources(root)[:2],
        "_assert_sources_unchanged": _assert_sources_unchanged,
    }
    originals = {name: getattr(study2_v1, name) for name in replacements}
    for name, value in replacements.items():
        setattr(study2_v1, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(study2_v1, name, value)


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


class MatchedSemanticControlRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        output_dir: Path,
        ask_fn: Callable[..., str] = study2_v1.ask_hive,
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
        planned: study2_v1.ExperimentCall,
        by_case: Mapping[str, worlds.BenchmarkCase],
    ) -> None:
        response = audit.ask(planned)
        record = audit.records[-1]
        call = study2._call_artifact(audit, record)
        response_id = study2._validate_attempt_contract(
            call,
            self.config,
            require_response_identity=True,
            expected_text_format=planned.text_format,
        )
        assert response_id is not None
        if response_id in self.response_ids:
            raise luna_v1.ApparatusFailure("response ID was reused")
        self.response_ids.add(response_id)
        selected_cases = [by_case[case_id] for case_id in planned.case_ids]
        try:
            labels = luna_v1.parse_structured_labels(response, len(selected_cases))
        except grading.ConstrainedInterfaceFailure as exc:
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
                    "scores": [],
                    "retry_attempted": False,
                    "repair_attempted": False,
                },
            )
            raise luna_v1.ApparatusFailure(
                f"{record.call_id} strict parser rejected output"
            ) from None
        generated_scores = [
            grading.grade_label(case, label, condition=planned.condition)
            for case, label in zip(selected_cases, labels)
        ]
        if any(score.secondary_status != "ran" for score in generated_scores):
            raise luna_v1.ApparatusFailure(
                f"{record.call_id} deterministic secondary evaluation failed"
            )
        self.scores[planned.replication][planned.condition].extend(generated_scores)
        audit.write_decision(
            record,
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "call_id": record.call_id,
                "status": "graded",
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
                "scores": [asdict(score) for score in generated_scores],
                "physical_attempts": 1,
                "retry_attempted": False,
                "repair_attempted": False,
            },
        )

    def _finish(
        self,
        audit: luna_v1.OpenAIAuditStore,
        *,
        preflight: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        luna_v1._write_exclusive(
            self.output_dir / "RESULT.json",
            luna_v1._pretty_json(luna_v1._sealed(result)),
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
        failed_call: study2_v1.ExperimentCall,
        exc: BaseException,
    ) -> Mapping[str, Any]:
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
            "apparatus_failure": study2_v1._safe_reason(exc),
            "partial_score_counts": {
                str(replication): {
                    condition: len(self.scores[replication][condition])
                    for condition in CONDITIONS
                }
                for replication in range(1, REPLICATION_COUNT + 1)
            },
            "usage": _usage_from_records(audit.records),
            "returned_model": audit.returned_model,
            "evidence_interpretation": "No matched-semantic-control claim is licensed.",
            "partial_artifacts_preserved": True,
            "retry_attempted": False,
            "repair_attempted": False,
        }
        return self._finish(audit, preflight=preflight, result=invalid)

    def run(self) -> Mapping[str, Any]:
        expected = (self.repo_root / RUN_DIR).resolve()
        if self.require_committed and self.output_dir.resolve() != expected:
            raise luna_v1.ApparatusFailure(
                "live Experiment-3 execution is locked to the frozen directory"
            )
        if self.output_dir.exists():
            raise luna_v1.ApparatusFailure(
                "Experiment-3 run directory already exists; inference was not started"
            )
        payload, cases, calls, preflight = deterministic_preflight(
            self.repo_root, require_committed=self.require_committed
        )
        del payload
        if self.output_dir.exists():
            raise luna_v1.ApparatusFailure("run directory appeared during preflight")
        audit = luna_v1.OpenAIAuditStore(
            self.output_dir, ask_fn=self.ask_fn, config=self.config
        )
        luna_v1._write_exclusive(
            self.output_dir / "PRECHECK.json", luna_v1._pretty_json(preflight)
        )
        protocol = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "mission": "matched-size nonsemantic control for the K/A/S semantic bundle",
            "conditions": list(CONDITIONS),
            "replications": REPLICATION_COUNT,
            "calls": MAX_GENERATION_CALLS,
            "schedule_sha256": FROZEN_SCHEDULE_SHA256,
            "request_plan_sha256": FROZEN_REQUEST_PLAN_SHA256,
            "m3_construction_sha256": FROZEN_M3_CONSTRUCTION_SHA256,
            "primary_comparison": PRIMARY_COMPARISON,
            "secondary_comparison": SECONDARY_COMPARISON,
            "control_comparison": CONTROL_COMPARISON,
            "valid_dispositions": list(VALID_DISPOSITIONS),
            "fail_closed_on_any_call_failure": True,
            "no_query_or_semantic_dependent_m3_generation": True,
            "size_match_tolerance_bytes": 0,
            "one_physical_attempt": True,
            "retry": False,
            "repair": False,
            "fallback": False,
        }
        manifest = {
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
        for name, content in (("PROTOCOL.json", protocol), ("MANIFEST.json", manifest)):
            luna_v1._write_exclusive(
                self.output_dir / name,
                luna_v1._pretty_json(luna_v1._sealed(content)),
            )
        by_case = {case.case_id: case for case in cases}
        for planned in calls:
            try:
                _assert_sources_unchanged(self.repo_root, preflight)
                self._run_call(audit, planned, by_case)
                _assert_sources_unchanged(self.repo_root, preflight)
            except BaseException as exc:
                return self._invalid(
                    audit, preflight=preflight, failed_call=planned, exc=exc
                )
        try:
            if len(audit.records) != MAX_GENERATION_CALLS:
                raise luna_v1.ApparatusFailure("completed schedule has wrong call count")
            if len(self.response_ids) != MAX_GENERATION_CALLS:
                raise luna_v1.ApparatusFailure("completed schedule reused response IDs")
            result = aggregate_valid_result(
                cases=cases,
                scores=self.scores,
                records=audit.records,
                preflight=preflight,
            )
        except BaseException as exc:
            return self._invalid(
                audit, preflight=preflight, failed_call=calls[-1], exc=exc
            )
        return self._finish(audit, preflight=preflight, result=result)


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    index = study2_v1._verify_index(run_dir)
    preflight = json.loads((run_dir / "PRECHECK.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "RESULT.json").read_text(encoding="utf-8"))
    protocol = json.loads((run_dir / "PROTOCOL.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "RUN_STATUS.json").read_text(encoding="utf-8"))
    for payload in (index, preflight, result, protocol, manifest, status):
        if payload.get("protocol_id") != PROTOCOL_ID:
            raise luna_v1.ApparatusFailure("artifact protocol identity mismatch")
    if (
        preflight.get("condition_schedule_sha256") != FROZEN_SCHEDULE_SHA256
        or preflight.get("m3_construction_sha256") != FROZEN_M3_CONSTRUCTION_SHA256
        or preflight.get("request_plan_sha256") != FROZEN_REQUEST_PLAN_SHA256
        or preflight.get("solver_config_sha256") != FROZEN_SOLVER_CONFIG_SHA256
        or preflight.get("source_revision") != index.get("source_revision")
        or manifest.get("source_revision") != index.get("source_revision")
    ):
        raise luna_v1.ApparatusFailure("sealed preflight/source bindings changed")
    cost = preflight.get("cost", {})
    if (
        cost.get("request_utf8_bytes_input_token_upper_bound")
        != FROZEN_INPUT_TOKEN_UPPER_BOUND
        or cost.get("output_token_upper_bound") != FROZEN_OUTPUT_TOKEN_UPPER_BOUND
        or cost.get("conservative_generation_cost_upper_bound_usd")
        != FROZEN_COST_UPPER_BOUND_USD
        or cost.get("authorized_cost_ceiling_usd") != AUTHORIZED_COST_CEILING_USD
    ):
        raise luna_v1.ApparatusFailure("frozen cost tuple changed")
    with _activated_study2_core():
        core = study2_v1.verify_run(run_dir)
    if result.get("validity") == "VALID":
        if (
            core.get("physical_generation_calls") != MAX_GENERATION_CALLS
            or core.get("unique_response_ids") != MAX_GENERATION_CALLS
            or core.get("returned_models") != [MODEL]
            or core.get("returned_service_tiers") != ["default"]
            or status.get("physical_generation_calls") != MAX_GENERATION_CALLS
            or status.get("unique_response_ids") != MAX_GENERATION_CALLS
            or result.get("result_code") not in VALID_DISPOSITIONS
        ):
            raise luna_v1.ApparatusFailure("valid run is not 144 exact Luna calls")
        if any(
            row["m3_minus_c1_absolute_bytes"] != 0
            or row["m3_minus_c1_percentage"] != 0
            for row in preflight["size_rows"]
        ):
            raise luna_v1.ApparatusFailure("sealed M3 size match is not exact")
        primary = result.get("primary_m3_vs_c1", {})
        if (
            primary.get("multiplicity_adjustment") is not None
            or len(primary.get("differences", [])) != 8
            or primary.get("replication_unit") != "complete_20_world_run"
        ):
            raise luna_v1.ApparatusFailure("primary statistical contract changed")
    elif result.get("result_code") != "INVALID_APPARATUS":
        raise luna_v1.ApparatusFailure("invalid run has a semantic disposition")
    return {
        "verified": True,
        "protocol_id": PROTOCOL_ID,
        "validity": result["validity"],
        "result_code": result["result_code"],
        "call_artifacts": core["call_artifacts"],
        "decision_artifacts": core["decision_artifacts"],
        "physical_generation_calls": core["physical_generation_calls"],
        "unique_response_ids": core["unique_response_ids"],
        "returned_models": core["returned_models"],
        "returned_service_tiers": core["returned_service_tiers"],
        "source_revision": index["source_revision"],
        "file_count": index["file_count"],
        "total_bytes": index["total_bytes"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(ACKNOWLEDGEMENT, dest="acknowledge", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(luna_v1._pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge:
        parser.error(f"{ACKNOWLEDGEMENT} is required")
    luna_v1._check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = MatchedSemanticControlRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(luna_v1._pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
