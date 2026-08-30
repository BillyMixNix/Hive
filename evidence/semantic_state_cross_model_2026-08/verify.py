#!/usr/bin/env python3
"""Fail-closed, offline verifier for the public Raw-vs-C1 evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parent
BUNDLE_ID = "semantic_state_cross_model_2026-08"
VALID_DIR = ROOT / "valid_run"
INVALID_DIR = ROOT / "invalid_first_attempt"
FROZEN_SOURCE_DIR = ROOT / "frozen_source"

CONDITIONS = ("LUNA_RAW", "LUNA_C1", "SOL_RAW", "SOL_C1")
CONDITION_DIRS = {
    "LUNA_RAW": "luna_raw",
    "LUNA_C1": "luna_c1",
    "SOL_RAW": "sol_raw",
    "SOL_C1": "sol_c1",
}
MODELS = {
    "LUNA_RAW": "gpt-5.6-luna",
    "LUNA_C1": "gpt-5.6-luna",
    "SOL_RAW": "gpt-5.6-sol",
    "SOL_C1": "gpt-5.6-sol",
}
REPRESENTATIONS = {
    "LUNA_RAW": "RAW",
    "LUNA_C1": "C1",
    "SOL_RAW": "RAW",
    "SOL_C1": "C1",
}
PRICING = {
    "LUNA_RAW": {"input": 0.20, "output": 1.20},
    "LUNA_C1": {"input": 0.20, "output": 1.20},
    "SOL_RAW": {"input": 4.00, "output": 20.00},
    "SOL_C1": {"input": 4.00, "output": 20.00},
}
ALLOWED_LABELS = ("A", "B", "C", "D", "INSUFFICIENT")
C1_COLUMNS = (
    "ref",
    "effective_t",
    "kind",
    "authority",
    "status",
    "requires",
    "effects",
)

VALID_RESULT_SHA256 = (
    "83996a1d9da93ff0e36e7ade87d13fc070e0db9a4f5bb14016a575b5c5506eb0"
)
VALID_INDEX_SHA256 = (
    "24c1de4106c013bed070d7004ebe0a5a15cb04430831e54a5e1efaa8a6b3718f"
)
INVALID_RESULT_SHA256 = (
    "8a032a1116172cfbee796db76031b490365bbaefeec91181de09ebfaf00c199b"
)
INVALID_INDEX_SHA256 = (
    "5921f5829fc56d71253cbcb63edfb3d60602beab9cfba964ce0e8f4c0daae55f"
)
OMITTED_PATH = "sol_raw/calls/call_000006.json"
OMITTED_SHA256 = (
    "1ae785570658d0ccfbdde4a7d6f2b0bdaf74a4607e671c4a3336562b68a7a8f9"
)
OMITTED_BYTES = 66_632

EXPECTED_PROVENANCE = {
    "bundle_id": BUNDLE_ID,
    "schema_version": 1,
    "repository": "BillyMixNix/Hive",
    "issue": 30,
    "source_evidence_directory": (
        ".hive/benchmarks/decompression_test/"
        "luna-sol-raw-c1-factorial-v1-1-001"
    ),
    "source_invalid_directory": (
        ".hive/benchmarks/decompression_test/luna-sol-raw-c1-factorial-v1-001"
    ),
    "implementation_commit": "5aac5eb47dd9b98782a9de2af27afb9ca972453b",
    "protocol_commit": "bfe8cb544d6777fe09e436cf08a3450a7db8b5d5",
    "sealed_evidence_commit": "91c127c351337759baa14a6ce5f2925f08c32a8b",
    "invalid_evidence_commit": "a76e28031321a2b5d255b7df39d0d4db425fce22",
    "canonical_valid_hashes": {
        "RESULT.json": VALID_RESULT_SHA256,
        "EVIDENCE_INDEX.json": VALID_INDEX_SHA256,
    },
    "canonical_invalid_hashes": {
        "RESULT.json": INVALID_RESULT_SHA256,
        "EVIDENCE_INDEX.json": INVALID_INDEX_SHA256,
    },
    "frozen_source_hashes": {
        "CASE_PACK.json": (
            "73e4684c1889a1e0d0a5f084d1e8b29f0241ce332baa4f6c6c5c92b5688ce2ed"
        ),
        "FROZEN_PROTOCOL.md": (
            "5fdf647f10581a8cf21b068f47c357a3188b31cde757077cd5cd6f9b9abf2976"
        ),
    },
    "copy_policy": (
        "Published sealed artifacts are byte-for-byte copies. One INVALID failure "
        "envelope is withheld rather than edited because it contains a private "
        "absolute filesystem path."
    ),
    "benchmark_rerun": False,
    "sealed_evidence_edited": False,
}

EXPECTED_OMISSION = {
    "schema_version": 1,
    "disposition": "WITHHELD_FROM_PUBLIC_MIRROR",
    "run": "invalid_first_attempt",
    "path": OMITTED_PATH,
    "bytes": OMITTED_BYTES,
    "sha256": OMITTED_SHA256,
    "reason": (
        "The sealed transport-failure envelope contains an absolute local "
        "workstation path. It was not edited or regenerated; the original remains "
        "preserved at the sealed evidence commit."
    ),
    "semantic_model_output_withheld": False,
    "source_evidence_commit": "a76e28031321a2b5d255b7df39d0d4db425fce22",
}


class VerificationFailure(RuntimeError):
    """A fail-closed evidence verification error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationFailure(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise VerificationFailure("non-finite JSON number")
    return value


def strict_json_loads(data: bytes | str, label: str) -> Any:
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
    except UnicodeDecodeError as exc:
        raise VerificationFailure(f"{label}: not strict UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_float=_finite_float,
            parse_constant=lambda value: (_ for _ in ()).throw(
                VerificationFailure(f"non-finite JSON constant: {value}")
            ),
        )
    except VerificationFailure:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VerificationFailure(f"{label}: malformed JSON: {exc}") from exc


def load_json(path: Path) -> Any:
    require(path.is_file(), f"missing JSON file: {path.relative_to(ROOT).as_posix()}")
    return strict_json_loads(path.read_bytes(), path.relative_to(ROOT).as_posix())


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_payload_seal(payload: Any, label: str) -> None:
    require(isinstance(payload, dict), f"{label}: sealed payload is not an object")
    claimed = payload.get("payload_sha256")
    require(
        isinstance(claimed, str) and re.fullmatch(r"[0-9a-f]{64}", claimed) is not None,
        f"{label}: missing or malformed payload seal",
    )
    body = dict(payload)
    body.pop("payload_sha256")
    observed = sha256_text(canonical_json(body))
    require(observed == claimed, f"{label}: payload seal mismatch")


def safe_index_path(value: Any, label: str) -> str:
    require(isinstance(value, str) and value, f"{label}: empty index path")
    path = PurePosixPath(value)
    require(not path.is_absolute(), f"{label}: absolute index path")
    require(".." not in path.parts and "." not in path.parts, f"{label}: unsafe index path")
    require(path.as_posix() == value, f"{label}: noncanonical index path")
    return value


def reject_symlinks() -> None:
    require(ROOT.is_dir(), "bundle root is missing")
    for path in ROOT.rglob("*"):
        require(not path.is_symlink(), f"symlink is forbidden: {path.relative_to(ROOT)}")


def verify_public_manifest() -> Mapping[str, Any]:
    path = ROOT / "PUBLIC_MANIFEST.json"
    manifest = load_json(path)
    verify_payload_seal(manifest, "PUBLIC_MANIFEST.json")
    require(manifest.get("schema_version") == 1, "public manifest schema changed")
    require(manifest.get("bundle_id") == BUNDLE_ID, "public manifest bundle ID changed")
    require(manifest.get("algorithm") == "sha256", "public manifest algorithm changed")
    rows = manifest.get("files")
    require(isinstance(rows, list), "public manifest rows are malformed")
    indexed: dict[str, Mapping[str, Any]] = {}
    for number, row in enumerate(rows, start=1):
        require(isinstance(row, dict), f"public manifest row {number} is malformed")
        relative = safe_index_path(row.get("path"), f"public manifest row {number}")
        require(relative != "PUBLIC_MANIFEST.json", "public manifest indexes itself")
        require(relative not in indexed, f"duplicate public manifest path: {relative}")
        indexed[relative] = row
    actual = {
        item.relative_to(ROOT).as_posix(): item
        for item in ROOT.rglob("*")
        if item.is_file() and item != path
    }
    require(set(actual) == set(indexed), "public manifest file set differs from disk")
    total = 0
    for relative, item in actual.items():
        row = indexed[relative]
        size = item.stat().st_size
        total += size
        require(type(row.get("bytes")) is int and row["bytes"] == size,
                f"public manifest size mismatch: {relative}")
        require(row.get("sha256") == sha256_file(item),
                f"public manifest hash mismatch: {relative}")
    require(manifest.get("file_count") == len(indexed), "public manifest count mismatch")
    require(manifest.get("total_bytes") == total, "public manifest byte total mismatch")
    return manifest


def verify_sealed_index(
    run_dir: Path,
    *,
    expected_result_sha256: str,
    expected_index_sha256: str,
    omitted: Mapping[str, tuple[int, str]] | None = None,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Mapping[str, Any]]]:
    omitted = omitted or {}
    result_path = run_dir / "RESULT.json"
    index_path = run_dir / "EVIDENCE_INDEX.json"
    require(sha256_file(result_path) == expected_result_sha256,
            f"{run_dir.name}: canonical RESULT.json hash mismatch")
    require(sha256_file(index_path) == expected_index_sha256,
            f"{run_dir.name}: canonical EVIDENCE_INDEX.json hash mismatch")
    result = load_json(result_path)
    index = load_json(index_path)
    verify_payload_seal(result, f"{run_dir.name}/RESULT.json")
    verify_payload_seal(index, f"{run_dir.name}/EVIDENCE_INDEX.json")
    rows = index.get("files")
    require(isinstance(rows, list), f"{run_dir.name}: index rows are malformed")
    indexed: dict[str, Mapping[str, Any]] = {}
    for number, row in enumerate(rows, start=1):
        require(isinstance(row, dict), f"{run_dir.name}: malformed index row {number}")
        relative = safe_index_path(row.get("path"), f"{run_dir.name} index row {number}")
        require(relative not in indexed, f"{run_dir.name}: duplicate index path {relative}")
        require(type(row.get("bytes")) is int and row["bytes"] >= 0,
                f"{run_dir.name}: invalid indexed size {relative}")
        require(isinstance(row.get("sha256"), str) and
                re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
                f"{run_dir.name}: invalid indexed hash {relative}")
        indexed[relative] = row
    require(index.get("file_count") == len(rows), f"{run_dir.name}: index count mismatch")
    require(index.get("total_bytes") == sum(row["bytes"] for row in rows),
            f"{run_dir.name}: index byte total mismatch")
    for relative, (size, digest) in omitted.items():
        require(relative in indexed, f"{run_dir.name}: omitted row missing from index")
        require(indexed[relative].get("bytes") == size, f"{run_dir.name}: omitted size mismatch")
        require(indexed[relative].get("sha256") == digest, f"{run_dir.name}: omitted hash mismatch")
        require(not (run_dir / PurePosixPath(relative)).exists(),
                f"{run_dir.name}: privacy-withheld file is unexpectedly public")
    actual = {
        item.relative_to(run_dir).as_posix(): item
        for item in run_dir.rglob("*")
        if item.is_file() and item.name != "EVIDENCE_INDEX.json"
    }
    require(set(actual) == set(indexed) - set(omitted),
            f"{run_dir.name}: sealed index file set differs from public disk set")
    for relative, item in actual.items():
        row = indexed[relative]
        require(item.stat().st_size == row["bytes"],
                f"{run_dir.name}: indexed size mismatch {relative}")
        require(sha256_file(item) == row["sha256"],
                f"{run_dir.name}: indexed hash mismatch {relative}")
    return result, index, indexed


def verify_root_seals(run_dir: Path) -> Mapping[str, Any]:
    values: dict[str, Any] = {}
    for name in ("MANIFEST.json", "PRECHECK.json", "PROTOCOL.json", "RUN_STATUS.json"):
        payload = load_json(run_dir / name)
        verify_payload_seal(payload, f"{run_dir.name}/{name}")
        values[name] = payload
    return values


def verify_frozen_sources(precheck: Mapping[str, Any]) -> None:
    source_hashes = precheck.get("source_file_sha256")
    require(isinstance(source_hashes, dict) and len(source_hashes) == 38,
            "precheck frozen-source map is incomplete")
    expected = {safe_index_path(path, "frozen source path"): digest
                for path, digest in source_hashes.items()}
    actual = {
        item.relative_to(FROZEN_SOURCE_DIR).as_posix(): item
        for item in FROZEN_SOURCE_DIR.rglob("*")
        if item.is_file()
    }
    require(set(actual) == set(expected), "frozen-source file set mismatch")
    for relative, item in actual.items():
        require(sha256_file(item) == expected[relative],
                f"frozen-source hash mismatch: {relative}")
    case_hash = expected["benchmarks/decompression_test/CASE_PACK.json"]
    protocol_hash = expected[
        "benchmarks/decompression_test/PROTOCOL_LUNA_SOL_RAW_C1_FACTORIAL_V1_1.md"
    ]
    require(sha256_file(ROOT / "CASE_PACK.json") == case_hash,
            "public CASE_PACK.json differs from frozen source")
    require(sha256_file(ROOT / "FROZEN_PROTOCOL.md") == protocol_hash,
            "public FROZEN_PROTOCOL.md differs from frozen source")
    require(precheck.get("case_pack_sha256") == case_hash,
            "precheck case-pack hash differs from frozen source")


def parse_prompt_input(prompt: str, label: str) -> Mapping[str, Any]:
    marker = "INPUT:\n"
    require(prompt.count(marker) == 1, f"{label}: prompt input marker changed")
    payload = strict_json_loads(prompt.split(marker, 1)[1], f"{label} prompt INPUT")
    require(isinstance(payload, dict) and isinstance(payload.get("cases"), list),
            f"{label}: prompt INPUT shape changed")
    return payload


def request_payload(prompt: str, config: Mapping[str, Any], text_format: Any) -> Mapping[str, Any]:
    return {
        "model": config["model"],
        "input": prompt,
        "reasoning": {
            "effort": config["reasoning_effort"],
            "context": config["reasoning_context"],
        },
        "max_output_tokens": config["max_output_tokens"],
        "tools": [],
        "store": False,
        "truncation": "disabled",
        "service_tier": "default",
        "prompt_cache_options": {"mode": "explicit"},
        "text": {"format": text_format},
    }


def verify_text_format(text_format: Any, expected_count: int, label: str) -> None:
    require(isinstance(text_format, dict), f"{label}: text format is not an object")
    require(text_format.get("type") == "json_schema" and text_format.get("strict") is True,
            f"{label}: constrained-output mode changed")
    schema = text_format.get("schema")
    require(isinstance(schema, dict) and schema.get("additionalProperties") is False,
            f"{label}: strict schema changed")
    require(schema.get("required") == ["answers"], f"{label}: schema required fields changed")
    require(set(schema.get("properties", {})) == {"answers"},
            f"{label}: schema answer field changed")
    answers = schema["properties"]["answers"]
    require(answers.get("type") == "array", f"{label}: answers is not an array")
    require(answers.get("minItems") == expected_count and
            answers.get("maxItems") == expected_count,
            f"{label}: exact batch cardinality changed")
    require(answers.get("items") == {"enum": list(ALLOWED_LABELS), "type": "string"},
            f"{label}: allowed labels changed")


def expected_secondary(label: str, truth: Any) -> tuple[Any, str, Any, int]:
    if label == "INSUFFICIENT":
        return None, "not_assessable_insufficient", None, 0
    statuses = {
        "current": "current",
        "historical": "historical_state_selected",
        "planned": "planned_state_selected",
        "hallucinated": "unsupported_state_selected",
    }
    require(truth in statuses, f"unknown frozen truth class: {truth}")
    return truth, statuses[truth], truth != "current", int(truth != "current")


def verify_score(score: Any, *, case_id: str, condition: str,
                 selected: str, expected: str, label: str) -> None:
    require(isinstance(score, dict), f"{label}: score row is malformed")
    require(score.get("case_id") == case_id and score.get("condition") == condition,
            f"{label}: score identity mismatch")
    require(score.get("selected_label") == selected and score.get("expected_label") == expected,
            f"{label}: score labels mismatch")
    require(score.get("admissible") is True, f"{label}: score was not admissible")
    correct = selected == expected
    require(score.get("answer_correct") is correct, f"{label}: correctness was misgraded")
    require(score.get("grader_status") == "ran" and score.get("grader_agreement") is True,
            f"{label}: primary grader did not agree")
    require(score.get("secondary_status") == "ran", f"{label}: secondary grader failed")
    truth, status, chronology_error, promotions = expected_secondary(
        selected, score.get("truth_class")
    )
    require(score.get("truth_class") == truth, f"{label}: truth class mismatch")
    require(score.get("chronology_authority_status") == status,
            f"{label}: chronology/authority status mismatch")
    require(score.get("chronology_authority_error") is chronology_error,
            f"{label}: chronology/authority error mismatch")
    require(score.get("illegal_state_promotions") == promotions,
            f"{label}: illegal-promotion count mismatch")
    reasons: list[str] = [] if correct else ["answer_incorrect"]
    if chronology_error:
        reasons.append("chronology_or_authority_error")
    if promotions:
        reasons.append("illegal_state_promotion")
    require(score.get("failure_reasons") == reasons, f"{label}: failure reasons mismatch")


def verify_event_log(condition_dir: Path, call_hashes: Mapping[int, str],
                     prompt_hashes: Mapping[int, str]) -> None:
    path = condition_dir / "events.jsonl"
    require(path.is_file(), f"missing event log: {condition_dir.name}")
    rows = [strict_json_loads(line, f"{condition_dir.name}/events line {number}")
            for number, line in enumerate(path.read_bytes().splitlines(), start=1)]
    require(len(rows) == 2 * len(call_hashes), f"{condition_dir.name}: event count mismatch")
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        require(isinstance(row, dict), f"{condition_dir.name}: malformed event row")
        sequence = row.get("sequence")
        require(type(sequence) is int, f"{condition_dir.name}: event sequence is malformed")
        grouped[sequence].append(row)
    require(set(grouped) == set(call_hashes), f"{condition_dir.name}: event sequences mismatch")
    for sequence, pair in grouped.items():
        require(len(pair) == 2, f"{condition_dir.name}: event pair mismatch at {sequence}")
        started = next((row for row in pair if row.get("event") == "call_started"), None)
        finished = next((row for row in pair if row.get("event") == "call_finished"), None)
        require(started is not None and finished is not None,
                f"{condition_dir.name}: incomplete event pair at {sequence}")
        require(started.get("prompt_sha256") == prompt_hashes[sequence],
                f"{condition_dir.name}: start-event prompt hash mismatch")
        require(finished.get("artifact_path") == f"calls/call_{sequence:06d}.json",
                f"{condition_dir.name}: finish-event artifact path mismatch")
        require(finished.get("artifact_file_sha256") == call_hashes[sequence],
                f"{condition_dir.name}: finish-event artifact hash mismatch")


def equivalent(observed: Any, expected: Any, label: str) -> None:
    if isinstance(observed, float) or isinstance(expected, float):
        require(isinstance(observed, (int, float)) and not isinstance(observed, bool) and
                isinstance(expected, (int, float)) and not isinstance(expected, bool) and
                math.isclose(float(observed), float(expected), rel_tol=0.0, abs_tol=1e-12),
                f"{label}: numeric mismatch ({observed!r} != {expected!r})")
        return
    if isinstance(expected, dict):
        require(isinstance(observed, dict) and set(observed) == set(expected),
                f"{label}: object keys mismatch")
        for key in expected:
            equivalent(observed[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, list):
        require(isinstance(observed, list) and len(observed) == len(expected),
                f"{label}: list length mismatch")
        for index, (left, right) in enumerate(zip(observed, expected)):
            equivalent(left, right, f"{label}[{index}]")
        return
    require(observed == expected, f"{label}: value mismatch ({observed!r} != {expected!r})")


def exact_sign_flip(differences: Iterable[int]) -> Mapping[str, Any]:
    values = tuple(int(value) for value in differences)
    require(len(values) == 8, "sign-flip analysis does not contain eight replications")
    observed = abs(sum(values))
    extreme = sum(
        abs(sum(sign * value for sign, value in zip(signs, values))) >= observed
        for signs in itertools.product((-1, 1), repeat=8)
    )
    return {
        "differences": list(values),
        "aggregate_difference_answers": sum(values),
        "observed_absolute_sum": observed,
        "extreme_assignments": extreme,
        "permutations": 256,
        "p_value": extreme / 256,
    }


def holm_adjust(p_values: Mapping[str, float]) -> Mapping[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * value))
        adjusted[name] = running
    return adjusted


def score_summary(scores: list[Mapping[str, Any]], rep_scores: list[int]) -> Mapping[str, Any]:
    world_errors = Counter(score["case_id"] for score in scores
                           if score["answer_correct"] is not True)
    return {
        "correct": sum(score["answer_correct"] is True for score in scores),
        "total": len(scores),
        "replication_scores": rep_scores,
        "admissible": sum(score["admissible"] is True for score in scores),
        "chronology_errors": sum(score["truth_class"] == "historical" for score in scores),
        "authority_errors": sum(score["truth_class"] in {"planned", "hallucinated"}
                                for score in scores),
        "chronology_authority_errors": sum(
            score["chronology_authority_error"] is True for score in scores
        ),
        "illegal_state_promotions": sum(score["illegal_state_promotions"] or 0
                                        for score in scores),
        "insufficient_responses": sum(score["selected_label"] == "INSUFFICIENT"
                                      for score in scores),
        "parser_failures": 0,
        "grader_failures": sum(score["grader_status"] != "ran" for score in scores),
        "secondary_failures": sum(score["secondary_status"] != "ran" for score in scores),
        "incomplete_responses": 0,
        "transport_failures": 0,
        "world_error_counts": dict(sorted(world_errors.items())),
    }


def verify_valid_run(result: Mapping[str, Any], precheck: Mapping[str, Any],
                     case_pack: Mapping[str, Any]) -> Mapping[str, Any]:
    require(result.get("validity") == "VALID" and
            result.get("result_code") == "VALID_FACTORIAL_COMPLETE",
            "valid run disposition changed")
    require(precheck.get("protocol_id") == "hive-luna-sol-raw-c1-factorial-v1.1",
            "valid precheck protocol changed")
    require(precheck.get("source_revision") ==
            "bfe8cb544d6777fe09e436cf08a3450a7db8b5d5",
            "valid source revision changed")
    require(precheck.get("replication_count") == 8 and
            precheck.get("batches_per_condition") == 6 and
            precheck.get("maximum_physical_generation_calls") == 192,
            "valid design dimensions changed")
    require(precheck.get("attempts_per_call") == 1 and
            all(precheck.get(field) is False for field in
                ("retry", "repair", "fallback", "tools", "storage", "resume", "overwrite")),
            "valid no-retry/no-repair contract changed")

    schedule = precheck.get("condition_schedule")
    require(isinstance(schedule, list) and len(schedule) == 8 and
            all(isinstance(row, list) and len(row) == 6 for row in schedule),
            "condition schedule dimensions changed")
    require(precheck.get("condition_schedule_sha256") == sha256_text(canonical_json(schedule)),
            "condition schedule seal mismatch")
    for replication in schedule:
        for order in replication:
            require(isinstance(order, list) and sorted(order) == sorted(CONDITIONS),
                    "condition schedule is not a four-arm permutation")
    positions = {condition: Counter() for condition in CONDITIONS}
    for replication in schedule:
        for order in replication:
            for position, condition in enumerate(order, start=1):
                positions[condition][position] += 1
    require(all(positions[condition] == Counter({1: 12, 2: 12, 3: 12, 4: 12})
                for condition in CONDITIONS), "condition schedule is not position-balanced")

    plan = precheck.get("call_plan")
    require(isinstance(plan, list) and len(plan) == 192, "call plan is not 192 rows")
    require(precheck.get("request_plan_sha256") == sha256_text(canonical_json(plan)),
            "request-plan seal mismatch")
    by_plan: dict[tuple[str, int], Mapping[str, Any]] = {}
    global_sequences: set[int] = set()
    for row in plan:
        require(isinstance(row, dict), "call-plan row is malformed")
        key = (row.get("condition"), row.get("local_sequence"))
        require(key[0] in CONDITIONS and type(key[1]) is int and key not in by_plan,
                "call-plan local identity is malformed or duplicated")
        by_plan[key] = row
        global_sequence = row.get("global_sequence")
        require(type(global_sequence) is int and global_sequence not in global_sequences,
                "call-plan global sequence is malformed or duplicated")
        global_sequences.add(global_sequence)
        replication = row["replication"]
        batch = row["batch_id"]
        position = row["condition_position"]
        require(schedule[replication - 1][batch - 1][position - 1] == row["condition"],
                "call plan differs from frozen condition schedule")
    require(global_sequences == set(range(1, 193)), "call plan global sequence is incomplete")

    cases = case_pack.get("cases")
    require(isinstance(cases, list) and len(cases) == 20, "case pack does not contain 20 cases")
    case_rows = {case.get("case_id"): case for case in cases if isinstance(case, dict)}
    require(len(case_rows) == 20 and all(case.get("correct_slot") in ALLOWED_LABELS[:4]
                                         for case in case_rows.values()),
            "case pack identities or oracle slots are malformed")

    all_response_ids: list[str] = []
    scores: dict[str, list[Mapping[str, Any]]] = {condition: [] for condition in CONDITIONS}
    scores_by_rep: dict[int, dict[str, list[Mapping[str, Any]]]] = {
        replication: {condition: [] for condition in CONDITIONS}
        for replication in range(1, 9)
    }
    usage_metadata: dict[str, list[Mapping[str, Any]]] = {
        condition: [] for condition in CONDITIONS
    }
    prompt_inputs: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    prompt_identity: dict[tuple[int, int, str], str] = {}
    canonical_case_without_representation: dict[str, str] = {}
    canonical_representation: dict[tuple[str, str], str] = {}

    for condition in CONDITIONS:
        directory = VALID_DIR / CONDITION_DIRS[condition]
        call_paths = sorted((directory / "calls").glob("call_*.json"))
        decision_paths = sorted((directory / "decisions").glob("decision_*.json"))
        require(len(call_paths) == 48 and len(decision_paths) == 48,
                f"{condition}: expected 48 calls and decisions")
        call_hashes: dict[int, str] = {}
        prompt_hashes: dict[int, str] = {}
        for local_sequence in range(1, 49):
            stem = f"call_{local_sequence:06d}"
            call_path = directory / "calls" / f"{stem}.json"
            decision_path = directory / "decisions" / f"decision_{local_sequence:06d}.json"
            call = load_json(call_path)
            decision = load_json(decision_path)
            verify_payload_seal(call, f"{condition}/{stem}")
            verify_payload_seal(decision, f"{condition}/decision_{local_sequence:06d}")
            row = by_plan[(condition, local_sequence)]
            label = f"{condition}/{stem}"
            require(call.get("call_id") == stem and call.get("sequence") == local_sequence,
                    f"{label}: local call identity mismatch")
            require(call.get("stage") == f"replication_{row['replication']:03d}" and
                    call.get("condition") == condition and
                    call.get("batch_id") == row["batch_id"] and
                    call.get("case_ids") == row["case_ids"],
                    f"{label}: call-plan identity mismatch")
            require(call.get("status") == "completed" and
                    call.get("admission_error") is None and
                    call.get("transport_error") is None,
                    f"{label}: call was not cleanly completed")

            request = call.get("request")
            require(isinstance(request, dict) and set(request) == {
                "openai_text_format", "openai_text_format_sha256", "prompt",
                "prompt_sha256", "solver_config", "solver_config_sha256"
            }, f"{label}: stored request shape changed")
            prompt = request["prompt"]
            require(isinstance(prompt, str), f"{label}: prompt is not text")
            prompt_hash = sha256_text(prompt)
            require(prompt_hash == request["prompt_sha256"] == row["prompt_sha256"],
                    f"{label}: prompt hash mismatch")
            require(len(prompt.encode("utf-8")) == row["prompt_utf8_bytes"],
                    f"{label}: prompt byte count mismatch")
            config = request["solver_config"]
            require(config == precheck["solver_configs"][condition],
                    f"{label}: solver config changed")
            config_hash = sha256_text(canonical_json(config))
            require(config_hash == request["solver_config_sha256"] ==
                    row["solver_config_sha256"] == precheck["solver_config_sha256"][condition],
                    f"{label}: solver-config hash mismatch")
            text_format = request["openai_text_format"]
            verify_text_format(text_format, len(row["case_ids"]), label)
            format_hash = sha256_text(canonical_json(text_format))
            require(format_hash == request["openai_text_format_sha256"] ==
                    row["text_format_sha256"], f"{label}: output-schema hash mismatch")
            provider_request = request_payload(prompt, config, text_format)
            canonical_request = canonical_json(provider_request)
            require(sha256_text(canonical_request) == row["request_sha256"] and
                    len(canonical_request.encode("utf-8")) ==
                    row["conservative_input_token_upper_bound"],
                    f"{label}: exact provider request differs from call plan")

            metadata = call.get("transport_metadata")
            require(isinstance(metadata, dict), f"{label}: transport metadata is malformed")
            for key, value in config.items():
                require(metadata.get(key) == value, f"{label}: transport config changed at {key}")
            require(metadata.get("requested_model") == MODELS[condition] and
                    metadata.get("returned_model") == MODELS[condition] and
                    metadata.get("returned_service_tier") == "default",
                    f"{label}: returned model or service tier changed")
            require(metadata.get("physical_attempts") == 1 and
                    metadata.get("max_attempts") == 1 and
                    metadata.get("sdk_max_retries") == 0 and
                    metadata.get("provider_fallback") is False and
                    metadata.get("store") is False and
                    metadata.get("tool_permissions") == [] and
                    metadata.get("reasoning_context") == "current_turn" and
                    metadata.get("truncation") == "disabled",
                    f"{label}: one-attempt/no-carry-over contract changed")
            require(metadata.get("adapter_status") == "completed" and
                    metadata.get("response_status") == "completed" and
                    metadata.get("response_error") is None and
                    metadata.get("incomplete_details") is None,
                    f"{label}: response did not end normally")
            for token_key in ("input_tokens", "output_tokens", "reasoning_tokens",
                              "total_tokens", "physical_attempts"):
                require(type(metadata.get(token_key)) is int and metadata[token_key] >= 0,
                        f"{label}: invalid usage field {token_key}")
            require(metadata["total_tokens"] ==
                    metadata["input_tokens"] + metadata["output_tokens"],
                    f"{label}: provider token total is inconsistent")
            require(isinstance(metadata.get("latency_seconds"), (int, float)) and
                    not isinstance(metadata.get("latency_seconds"), bool) and
                    metadata["latency_seconds"] >= 0,
                    f"{label}: latency is invalid")
            response_id = metadata.get("response_id")
            require(isinstance(response_id, str) and response_id,
                    f"{label}: response ID is missing")
            all_response_ids.append(response_id)

            response = call.get("response")
            require(isinstance(response, dict) and set(response) == {"raw_text", "sha256"},
                    f"{label}: response envelope changed")
            raw_text = response["raw_text"]
            require(isinstance(raw_text, str) and response["sha256"] == sha256_text(raw_text),
                    f"{label}: raw response hash mismatch")
            answer = strict_json_loads(raw_text, f"{label} raw response")
            require(isinstance(answer, dict) and set(answer) == {"answers"} and
                    isinstance(answer["answers"], list) and
                    len(answer["answers"]) == len(row["case_ids"]) and
                    all(value in ALLOWED_LABELS for value in answer["answers"]),
                    f"{label}: raw response violates exact output contract")

            require(decision.get("call_id") == stem and
                    decision.get("global_sequence") == row["global_sequence"] and
                    decision.get("replication") == row["replication"] and
                    decision.get("condition_position") == row["condition_position"] and
                    decision.get("batch_id") == row["batch_id"] and
                    decision.get("condition") == condition,
                    f"{label}: decision-plan identity mismatch")
            require(decision.get("status") == "graded" and
                    decision.get("parser_status") == "passed" and
                    decision.get("grader_status") == "ran" and
                    decision.get("grader_agreement") is True and
                    decision.get("physical_attempts") == 1 and
                    decision.get("retry_attempted") is False and
                    decision.get("repair_attempted") is False and
                    decision.get("response_id") == response_id and
                    decision.get("labels") == answer["answers"],
                    f"{label}: decision admission or no-repair contract changed")
            decision_scores = decision.get("scores")
            require(isinstance(decision_scores, list) and
                    len(decision_scores) == len(row["case_ids"]),
                    f"{label}: decision score cardinality mismatch")
            for index, case_id in enumerate(row["case_ids"]):
                require(case_id in case_rows, f"{label}: unknown frozen case {case_id}")
                selected = answer["answers"][index]
                expected = case_rows[case_id]["correct_slot"]
                verify_score(
                    decision_scores[index], case_id=case_id, condition=condition,
                    selected=selected, expected=expected, label=f"{label}/{case_id}",
                )
                scores[condition].append(decision_scores[index])
                scores_by_rep[row["replication"]][condition].append(decision_scores[index])

            prompt_payload = parse_prompt_input(prompt, label)
            prompt_cases = prompt_payload["cases"]
            require([case.get("case_id") for case in prompt_cases] == row["case_ids"],
                    f"{label}: prompt case order differs from plan")
            prompt_inputs[(condition, row["replication"], row["batch_id"])] = prompt_payload
            identity_key = (row["replication"], row["batch_id"], REPRESENTATIONS[condition])
            previous_prompt_hash = prompt_identity.setdefault(identity_key, prompt_hash)
            require(previous_prompt_hash == prompt_hash,
                    f"{label}: models received different prompts for one representation")
            for prompt_case in prompt_cases:
                case_id = prompt_case["case_id"]
                require(case_id in case_rows, f"{label}: prompt contains unknown case")
                without_representation = dict(prompt_case)
                representation = without_representation.pop("representation")
                stable = canonical_json(without_representation)
                previous = canonical_case_without_representation.setdefault(case_id, stable)
                require(previous == stable,
                        f"{label}: question/options changed across conditions")
                rep_key = (REPRESENTATIONS[condition], case_id)
                rep_stable = canonical_json(representation)
                previous_rep = canonical_representation.setdefault(rep_key, rep_stable)
                require(previous_rep == rep_stable,
                        f"{label}: projection changed across models or replications")
                if REPRESENTATIONS[condition] == "C1":
                    require(representation.get("record_columns") == list(C1_COLUMNS),
                            f"{label}: C1 semantic columns changed")

            usage_metadata[condition].append(metadata)
            call_hashes[local_sequence] = sha256_file(call_path)
            prompt_hashes[local_sequence] = prompt_hash
        verify_event_log(directory, call_hashes, prompt_hashes)

    require(len(all_response_ids) == 192 and len(set(all_response_ids)) == 192,
            "valid run response identities are missing or reused")
    for replication in range(1, 9):
        for condition in CONDITIONS:
            selected = scores_by_rep[replication][condition]
            require(len(selected) == 20 and len({score["case_id"] for score in selected}) == 20,
                    "a stochastic replication is not one complete 20-world benchmark")

    state_bytes: dict[str, int] = {}
    for condition in CONDITIONS:
        per_replication: list[int] = []
        for replication in range(1, 9):
            prompt_cases = [case for batch in range(1, 7)
                            for case in prompt_inputs[(condition, replication, batch)]["cases"]]
            require(len(prompt_cases) == 20 and
                    len({case["case_id"] for case in prompt_cases}) == 20,
                    f"{condition}: projected state is not 20 unique worlds")
            per_replication.append(sum(
                len(canonical_json(case["representation"]).encode("utf-8"))
                for case in prompt_cases
            ))
        require(len(set(per_replication)) == 1,
                f"{condition}: representation bytes drift across replications")
        state_bytes[condition] = per_replication[0]
    equivalent(state_bytes, precheck["representation_utf8_bytes_per_20_world_replication"],
               "precheck representation bytes")
    equivalent(state_bytes, result["representation_utf8_bytes_per_20_world_replication"],
               "result representation bytes")

    replication_scores: dict[str, dict[str, int]] = {}
    condition_scores: dict[str, list[int]] = {condition: [] for condition in CONDITIONS}
    for replication in range(1, 9):
        row: dict[str, int] = {}
        for condition in CONDITIONS:
            correct = sum(score["answer_correct"] is True
                          for score in scores_by_rep[replication][condition])
            row[condition] = correct
            condition_scores[condition].append(correct)
        replication_scores[str(replication)] = row
    equivalent(result["replication_scores"], replication_scores, "result replication scores")

    summaries: dict[str, Mapping[str, Any]] = {}
    for condition in CONDITIONS:
        summary = dict(score_summary(scores[condition], condition_scores[condition]))
        sealed_summary = result["conditions"][condition]
        result_field_map = {
            "correct": "exact_correct",
            "total": "total",
            "replication_scores": "exact_correct_by_replication",
            "admissible": "admissible",
            "chronology_errors": "chronology_errors",
            "authority_errors": "authority_errors",
            "chronology_authority_errors": "chronology_authority_errors",
            "illegal_state_promotions": "illegal_state_promotions",
            "insufficient_responses": "insufficient_responses",
            "parser_failures": "parser_failures",
            "grader_failures": "grader_failures",
            "secondary_failures": "secondary_failures",
            "incomplete_responses": "incomplete_responses",
            "transport_failures": "transport_failures",
            "world_error_counts": "world_error_counts",
        }
        for public_name, sealed_name in result_field_map.items():
            equivalent(sealed_summary[sealed_name], summary[public_name],
                       f"result {condition}.{sealed_name}")
        enriched = []
        for score in scores[condition]:
            row = dict(score)
            row["family"] = case_rows[score["case_id"]]["family"]
            row["load"] = case_rows[score["case_id"]]["load"]
            enriched.append(row)
        equivalent(sealed_summary["scores"], enriched, f"result {condition}.scores")
        summaries[condition] = summary

    usage: dict[str, Mapping[str, Any]] = {}
    for condition in CONDITIONS:
        rows = usage_metadata[condition]
        input_tokens = sum(row["input_tokens"] for row in rows)
        output_tokens = sum(row["output_tokens"] for row in rows)
        reasoning_tokens = sum(row["reasoning_tokens"] for row in rows)
        latency = sum(float(row["latency_seconds"]) for row in rows)
        price = PRICING[condition]
        usage[condition] = {
            "call_artifacts": len(rows),
            "physical_generation_calls": sum(row["physical_attempts"] for row in rows),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_seconds": latency,
            "mean_latency_seconds_per_call": latency / len(rows),
            "estimated_generation_cost_usd": (
                input_tokens * price["input"] / 1_000_000
                + output_tokens * price["output"] / 1_000_000
            ),
        }
        equivalent(result["usage"]["by_condition"][condition], usage[condition],
                   f"result usage {condition}")
    usage_total = {
        field: sum(usage[condition][field] for condition in CONDITIONS)
        for field in (
            "call_artifacts", "physical_generation_calls", "input_tokens", "output_tokens",
            "reasoning_tokens", "total_tokens", "latency_seconds",
            "estimated_generation_cost_usd",
        )
    }
    equivalent(result["usage"]["total"], usage_total, "result total usage")

    differences = {
        "LUNA_C1_MINUS_LUNA_RAW": [
            c1 - raw for c1, raw in zip(condition_scores["LUNA_C1"],
                                        condition_scores["LUNA_RAW"])
        ],
        "SOL_C1_MINUS_SOL_RAW": [
            c1 - raw for c1, raw in zip(condition_scores["SOL_C1"],
                                        condition_scores["SOL_RAW"])
        ],
    }
    differences["REPRESENTATION_BY_MODEL_INTERACTION"] = [
        luna - sol for luna, sol in zip(
            differences["LUNA_C1_MINUS_LUNA_RAW"],
            differences["SOL_C1_MINUS_SOL_RAW"],
        )
    ]
    statistics = {name: dict(exact_sign_flip(values)) for name, values in differences.items()}
    adjusted = holm_adjust({name: row["p_value"] for name, row in statistics.items()})
    for name, row in statistics.items():
        row["holm_adjusted_p_value"] = adjusted[name]
        row["decision"] = (
            "SUPPORTED_POSITIVE" if adjusted[name] <= 0.05 and
            row["aggregate_difference_answers"] > 0
            else "SUPPORTED_NEGATIVE" if adjusted[name] <= 0.05 and
            row["aggregate_difference_answers"] < 0
            else "NOT_SUPPORTED"
        )
        sealed = result["primary_confirmatory_comparisons"][name]
        for field in (
            "differences", "aggregate_difference_answers", "observed_absolute_sum",
            "extreme_assignments", "permutations", "p_value",
            "holm_adjusted_p_value", "decision",
        ):
            equivalent(sealed[field], row[field], f"result statistic {name}.{field}")

    return {
        "response_ids": set(all_response_ids),
        "condition_summaries": summaries,
        "replication_scores": replication_scores,
        "usage": usage,
        "usage_total": usage_total,
        "state_bytes": state_bytes,
        "statistics": statistics,
    }


def verify_invalid_run(result: Mapping[str, Any], index: Mapping[str, Any],
                       indexed: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    require(result.get("validity") == "INVALID" and
            result.get("result_code") == "INVALID_APPARATUS",
            "first attempt is not sealed INVALID_APPARATUS")
    require(result.get("failed_global_sequence") == 22 and
            result.get("failed_replication") == 1 and
            result.get("failed_condition") == "SOL_RAW" and
            result.get("failed_batch_id") == 6,
            "first-attempt failure location changed")
    require(result.get("retry_attempted") is False and
            result.get("repair_attempted") is False and
            result.get("partial_artifacts_preserved") is True,
            "first-attempt no-retry preservation contract changed")
    failure = result.get("failure_evidence")
    require(isinstance(failure, dict) and failure.get("failure_class") == "transport_failure",
            "first-attempt failure class changed")
    pointer = failure.get("failed_call_artifact")
    require(isinstance(pointer, dict) and pointer.get("path") == OMITTED_PATH and
            pointer.get("file_sha256") == OMITTED_SHA256 and
            pointer.get("status") == "transport_error",
            "first-attempt failed-call pointer changed")
    require(failure.get("failed_decision_artifact") is None,
            "first-attempt unexpectedly has a failed-call decision")
    require(indexed[OMITTED_PATH]["bytes"] == OMITTED_BYTES and
            indexed[OMITTED_PATH]["sha256"] == OMITTED_SHA256,
            "privacy omission differs from sealed INVALID index")
    require(index.get("file_count") == 52, "INVALID index file count changed")
    require(result.get("usage", {}).get("total", {}).get("physical_generation_calls") == 22,
            "INVALID physical call count changed")

    response_ids: list[str] = []
    call_paths = sorted(INVALID_DIR.glob("*/calls/call_*.json"))
    decision_paths = sorted(INVALID_DIR.glob("*/decisions/decision_*.json"))
    require(len(call_paths) == 21 and len(decision_paths) == 21,
            "INVALID public subset should contain 21 completed calls and decisions")
    for path in call_paths:
        call = load_json(path)
        verify_payload_seal(call, path.relative_to(ROOT).as_posix())
        require(call.get("status") == "completed", "INVALID public call was not completed")
        metadata = call.get("transport_metadata")
        require(isinstance(metadata, dict) and metadata.get("physical_attempts") == 1,
                "INVALID public call violates one-attempt rule")
        response_id = metadata.get("response_id")
        require(isinstance(response_id, str) and response_id,
                "INVALID public call lacks response ID")
        response_ids.append(response_id)
        response = call.get("response")
        require(isinstance(response, dict) and isinstance(response.get("raw_text"), str) and
                response.get("sha256") == sha256_text(response["raw_text"]),
                "INVALID public raw response hash mismatch")
    for path in decision_paths:
        decision = load_json(path)
        verify_payload_seal(decision, path.relative_to(ROOT).as_posix())
        require(decision.get("retry_attempted") is False and
                decision.get("repair_attempted") is False and
                decision.get("status") == "graded",
                "INVALID public decision violates no-repair rule")
    require(len(set(response_ids)) == 21, "INVALID response IDs are reused")
    return {
        "response_ids": set(response_ids),
        "summary": {
            "validity": "INVALID",
            "result_code": "INVALID_APPARATUS",
            "failure_class": "transport_failure",
            "failed_global_sequence": 22,
            "physical_generation_calls": 22,
            "completed_response_ids": 21,
            "completed_outputs_reused_by_valid_restart": False,
            "public_indexed_payload_files": 51,
            "original_indexed_payload_files": 52,
            "privacy_withheld_artifact": {
                "path": OMITTED_PATH,
                "bytes": OMITTED_BYTES,
                "sha256": OMITTED_SHA256,
                "contains_semantic_model_output": False,
            },
        },
    }


def scan_privacy_and_secrets() -> Mapping[str, Any]:
    patterns = {
        "windows_user_path": re.compile(
            rb"[A-Za-z]:\\{1,2}Users\\{1,2}[^\\/\"\s]+", re.IGNORECASE
        ),
        "windows_user_path_slash": re.compile(
            rb"[A-Za-z]:/{1,2}Users/[^/\"\s]+", re.IGNORECASE
        ),
        "posix_home_path": re.compile(rb"/(?:Users|home)/[^/\"\s]+", re.IGNORECASE),
        "openai_style_secret": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
        "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "bearer_credential": re.compile(
            rb"authorization[\"'\s:=]+bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE
        ),
        "email": re.compile(
            rb"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
        ),
    }
    allowed_email_domains = {
        b"example.com", b"example.org", b"example.net", b"example.invalid",
        b"test.invalid",
    }
    allowed_test_secrets = {
        b"sk-test-" + b"1234567890abcdef",
        b"sk-experiment-two-" + b"secret-value",
    }
    scanned = 0
    allowlisted_fixtures = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        scanned += 1
        for name, pattern in patterns.items():
            for match in pattern.finditer(data):
                if (name == "openai_style_secret" and
                        match.group(0) in allowed_test_secrets and
                        path.is_relative_to(FROZEN_SOURCE_DIR / "tests")):
                    allowlisted_fixtures += 1
                    continue
                if name == "email":
                    domain = match.group(0).lower().rsplit(b"@", 1)[-1]
                    if domain in allowed_email_domains:
                        continue
                raise VerificationFailure(
                    f"privacy/secret scan detected {name} in {path.relative_to(ROOT).as_posix()}"
                )
    return {
        "status": "PASS",
        "findings": 0,
        "allowlisted_synthetic_test_fixtures": allowlisted_fixtures,
    }


def build_published_summary(
    valid: Mapping[str, Any], invalid: Mapping[str, Any], result: Mapping[str, Any]
) -> Mapping[str, Any]:
    conditions: dict[str, Any] = {}
    for condition in CONDITIONS:
        row = dict(valid["condition_summaries"][condition])
        row.pop("world_error_counts")
        row.update({
            "state_bytes_per_20_world_replication": valid["state_bytes"][condition],
            "input_tokens": valid["usage"][condition]["input_tokens"],
            "output_tokens": valid["usage"][condition]["output_tokens"],
            "reasoning_tokens": valid["usage"][condition]["reasoning_tokens"],
            "total_tokens": valid["usage"][condition]["total_tokens"],
            "latency_seconds": valid["usage"][condition]["latency_seconds"],
            "estimated_generation_cost_usd": valid["usage"][condition][
                "estimated_generation_cost_usd"
            ],
            "physical_generation_calls": valid["usage"][condition][
                "physical_generation_calls"
            ],
        })
        conditions[condition] = row

    statistics = {
        name: {
            "differences": row["differences"],
            "aggregate_difference_answers": row["aggregate_difference_answers"],
            "p_value": row["p_value"],
            "holm_adjusted_p_value": row["holm_adjusted_p_value"],
            "decision": row["decision"],
        }
        for name, row in valid["statistics"].items()
    }
    raw_bytes = valid["state_bytes"]["LUNA_RAW"]
    c1_bytes = valid["state_bytes"]["LUNA_C1"]
    return {
        "schema_version": 1,
        "bundle_id": BUNDLE_ID,
        "validity": "VALID",
        "result_code": "VALID_FACTORIAL_COMPLETE",
        "canonical_artifacts": {
            "RESULT.json": VALID_RESULT_SHA256,
            "EVIDENCE_INDEX.json": VALID_INDEX_SHA256,
        },
        "design": {
            "fixed_worlds": 20,
            "stochastic_replications": 8,
            "conditions": 4,
            "generation_batches_per_condition_replication": 6,
            "physical_generation_calls": 192,
            "unique_response_ids": 192,
            "retries": 0,
            "repairs": 0,
            "fallbacks": 0,
            "tools": 0,
            "cross_call_reasoning": False,
        },
        "conditions": conditions,
        "usage_total": valid["usage_total"],
        "confirmatory_statistics": statistics,
        "within_model_efficiency": {
            "state_bytes_reduction_percent": 100 * (1 - c1_bytes / raw_bytes),
            "input_tokens_reduction_percent": {
                model: 100 * (1 - valid["usage"][f"{model}_C1"]["input_tokens"] /
                              valid["usage"][f"{model}_RAW"]["input_tokens"])
                for model in ("LUNA", "SOL")
            },
            "generation_cost_reduction_percent": {
                model: 100 * (
                    1 - valid["usage"][f"{model}_C1"]["estimated_generation_cost_usd"] /
                    valid["usage"][f"{model}_RAW"]["estimated_generation_cost_usd"]
                )
                for model in ("LUNA", "SOL")
            },
        },
        "invalid_first_attempt": invalid["summary"],
        "strongest_licensed_claim": (
            "On this sealed synthetic benchmark, the engineered C1 representation "
            "used materially less supplied context and had lower estimated generation "
            "cost under the frozen token-pricing assumptions while preserving the same "
            "aggregate observed correct count as Raw within each tested solver arm."
        ),
        "claim_boundary": result["claim_boundary"],
        "non_claims": [
            "No production-savings claim.",
            "No formal or statistical equivalence claim.",
            "No learned-compression claim.",
            "No general model-substitution claim.",
            "No extension beyond the frozen worlds, representations, models, and settings.",
        ],
    }


def verify_core(*, compare_summary: bool) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    reject_symlinks()
    provenance = load_json(ROOT / "PROVENANCE.json")
    omission = load_json(ROOT / "PRIVACY_OMISSION.json")
    equivalent(provenance, EXPECTED_PROVENANCE, "PROVENANCE.json")
    equivalent(omission, EXPECTED_OMISSION, "PRIVACY_OMISSION.json")

    valid_result, _valid_index, _valid_indexed = verify_sealed_index(
        VALID_DIR,
        expected_result_sha256=VALID_RESULT_SHA256,
        expected_index_sha256=VALID_INDEX_SHA256,
    )
    valid_roots = verify_root_seals(VALID_DIR)
    precheck = valid_roots["PRECHECK.json"]
    verify_frozen_sources(precheck)
    case_pack = load_json(ROOT / "CASE_PACK.json")
    valid = verify_valid_run(valid_result, precheck, case_pack)

    invalid_result, invalid_index, invalid_indexed = verify_sealed_index(
        INVALID_DIR,
        expected_result_sha256=INVALID_RESULT_SHA256,
        expected_index_sha256=INVALID_INDEX_SHA256,
        omitted={OMITTED_PATH: (OMITTED_BYTES, OMITTED_SHA256)},
    )
    verify_root_seals(INVALID_DIR)
    invalid = verify_invalid_run(invalid_result, invalid_index, invalid_indexed)
    require(valid["response_ids"].isdisjoint(invalid["response_ids"]),
            "valid restart reused a response ID from the INVALID first attempt")

    summary = build_published_summary(valid, invalid, valid_result)
    if compare_summary:
        published = load_json(ROOT / "PUBLISHED_SUMMARY.json")
        equivalent(published, summary, "PUBLISHED_SUMMARY.json")
    privacy = scan_privacy_and_secrets()
    output = {
        "verification": "PASS",
        "bundle_id": BUNDLE_ID,
        "offline": True,
        "model_calls": 0,
        "privacy_secret_scan": privacy,
        "published_summary": summary,
    }
    return summary, output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--print-computed-summary", action="store_true",
                       help=argparse.SUPPRESS)
    group.add_argument("--print-computed-output", action="store_true",
                       help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.print_computed_summary:
            summary, _output = verify_core(compare_summary=False)
            print(pretty_json(summary), end="")
            return 0
        if args.print_computed_output:
            _summary, output = verify_core(compare_summary=True)
            print(pretty_json(output), end="")
            return 0
        verify_public_manifest()
        _summary, output = verify_core(compare_summary=True)
        expected_output = pretty_json(output)
        output_path = ROOT / "VERIFIER_OUTPUT.txt"
        require(output_path.is_file(), "VERIFIER_OUTPUT.txt is missing")
        require(output_path.read_bytes() == expected_output.encode("utf-8"),
                "VERIFIER_OUTPUT.txt differs from recomputed verifier output")
        print(expected_output, end="")
        return 0
    except VerificationFailure as exc:
        print(f"VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
