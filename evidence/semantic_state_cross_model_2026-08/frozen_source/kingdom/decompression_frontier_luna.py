"""Capability-gated GPT-5.6 Luna compression frontier for Hive.

This is a separate experiment from sealed Decompression Test v1/v2/v2.1.
It reuses the frozen 20 worlds and deterministic oracle, but asks a narrower
question: after Luna demonstrates perfect Raw capability, how much of the
compact ledger can be removed before exact task performance first changes?
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hive_llm import FrozenSolverConfig, ask_hive
from kingdom import decompression_test as v1
from kingdom import decompression_test_v2 as v2


PROTOCOL_ID = "hive-luna-compression-frontier-v1"
PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = 1
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 2_048
TIMEOUT_SECONDS = 900
EXPECTED_OPENAI_SDK = "3.3.1"
FROZEN_CASE_PACK_SHA256 = (
    "73e4684c1889a1e0d0a5f084d1e8b29f0241ce332baa4f6c6c5c92b5688ce2ed"
)
FROZEN_EXPANDED_PACK_SHA256 = (
    "da81bae7eb4df4f19f045400a1a03e72cb3595f1531288e6f139d01080ca8dc9"
)
RAW_CALLS = 6
FRONTIER_CALLS = 18
MAX_GENERATION_CALLS = RAW_CALLS + FRONTIER_CALLS
RAW_REQUIRED_CORRECT = 20
RAW_INPUT_TOKEN_UPPER_BOUND = 400_000
FRONTIER_INPUT_TOKEN_UPPER_BOUND = 500_000
AUTHORIZED_COST_CEILING_USD = 0.30
INPUT_USD_PER_MILLION = 0.20
OUTPUT_USD_PER_MILLION = 1.20
RUN_DIR = Path(".hive/benchmarks/decompression_test/luna-frontier-v1-001")

LEVELS = ("C0", "C1", "C2")
FULL_COLUMNS = (
    "ref",
    "effective_t",
    "record_t",
    "kind",
    "authority",
    "status",
    "requires",
    "effects",
)
LEVEL_COLUMNS = {
    "C0": FULL_COLUMNS,
    "C1": tuple(name for name in FULL_COLUMNS if name != "record_t"),
    "C2": tuple(
        name
        for name in FULL_COLUMNS
        if name not in {"record_t", "kind", "authority", "status"}
    ),
}
# The old slot names are used only to inherit the frozen Latin-square order.
SLOT_TO_LEVEL = {"raw": "C0", "retrieval": "C1", "compressed": "C2"}
SOURCE_FILES = (
    "hive_llm.py",
    "kingdom/decompression_test.py",
    "kingdom/decompression_test_v2.py",
    "kingdom/decompression_frontier_luna.py",
    "benchmarks/decompression_test/CASE_PACK.json",
    "benchmarks/decompression_test/PROTOCOL_LUNA_FRONTIER_V1.md",
    "tests/test_hive_llm_openai.py",
    "tests/test_decompression_frontier_luna.py",
)


class ApparatusFailure(RuntimeError):
    """A transport, schema, parser, or evidence failure; never a task miss."""


@dataclass(frozen=True)
class PlannedCall:
    sequence: int
    stage: str
    batch_id: int
    condition: str
    case_ids: tuple[str, ...]
    prompt: str
    text_format: Mapping[str, Any]


@dataclass(frozen=True)
class CallRecord:
    sequence: int
    call_id: str
    stage: str
    batch_id: int
    condition: str
    artifact_path: str
    artifact_file_sha256: str
    status: str
    metadata: Mapping[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _sealed(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result["payload_sha256"] = _sha256_text(_canonical_json(result))
    return result


def _verify_seal(payload: Mapping[str, Any]) -> None:
    claimed = payload.get("payload_sha256")
    body = {key: value for key, value in payload.items() if key != "payload_sha256"}
    if not isinstance(claimed, str) or claimed != _sha256_text(_canonical_json(body)):
        raise ApparatusFailure("sealed JSON payload hash mismatch")


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return {"python_type": type(value).__qualname__, "repr": repr(value)}


def _safe_error(error: BaseException | None) -> Mapping[str, Any] | None:
    if error is None:
        return None
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    secret = os.environ.get("OPENAI_API_KEY", "")
    if secret:
        rendered = rendered.replace(secret, "[REDACTED_OPENAI_KEY]")
    rendered = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
        r"\1[REDACTED_OPENAI_KEY]",
        rendered,
    )
    rendered = re.sub(
        r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED_OPENAI_KEY]", rendered
    )
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error).replace(secret, "[REDACTED_OPENAI_KEY]") if secret else str(error),
        "traceback": rendered,
        "traceback_sha256": _sha256_text(rendered),
    }


def solver_config() -> FrozenSolverConfig:
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


def openai_text_format(expected_count: int) -> dict[str, Any]:
    answers = v2.output_schema(expected_count)
    return {
        "type": "json_schema",
        "name": f"hive_labels_{expected_count}",
        "schema": {
            "type": "object",
            "properties": {"answers": answers},
            "required": ["answers"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def parse_structured_labels(raw: str, expected_count: int) -> tuple[str, ...]:
    """Accept only the one-field object enforced by the OpenAI schema."""
    if not isinstance(raw, str):
        raise v2.ConstrainedInterfaceFailure("response must be text")
    try:
        payload = json.loads(raw, object_pairs_hook=v1._reject_duplicate_pairs)
    except (json.JSONDecodeError, v1.ModelOutputRejected) as exc:
        raise v2.ConstrainedInterfaceFailure(f"strict JSON parsing failed: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"answers"}:
        raise v2.ConstrainedInterfaceFailure("response must contain only answers")
    answers = payload["answers"]
    if not isinstance(answers, list) or len(answers) != expected_count:
        raise v2.ConstrainedInterfaceFailure("answers length differs from batch")
    if any(not isinstance(label, str) or label not in v2.LABELS for label in answers):
        raise v2.ConstrainedInterfaceFailure("answer is not one allowed label")
    return tuple(answers)


def transform_compact_packet(
    packet: Mapping[str, Any], level: str
) -> dict[str, Any]:
    """Apply one query-blind named-column projection to a compact packet."""
    if level not in LEVELS:
        raise ValueError(f"unknown frontier level {level!r}")
    if packet.get("format") != "compact_typed_ledger_v1":
        raise ValueError("frontier input is not the frozen compact codec")
    source_columns = tuple(packet.get("record_columns", ()))
    if source_columns != FULL_COLUMNS:
        raise ValueError("frozen compact columns changed")
    retained = LEVEL_COLUMNS[level]
    indexes = tuple(source_columns.index(name) for name in retained)
    records = packet.get("records")
    if not isinstance(records, list):
        raise ValueError("compact records must be a list")
    projected = {
        "format": "compact_named_columns_frontier_v1",
        "record_columns": list(retained),
        "records": [[copy.deepcopy(record[index]) for index in indexes] for record in records],
    }
    validate_frontier_packet(projected, expected_level=level)
    return projected


def validate_frontier_packet(
    packet: Mapping[str, Any], *, expected_level: str | None = None
) -> None:
    if set(packet) != {"format", "record_columns", "records"}:
        raise ValueError("frontier packet has missing or unknown fields")
    if packet["format"] != "compact_named_columns_frontier_v1":
        raise ValueError("frontier packet format mismatch")
    columns = tuple(packet["record_columns"])
    matches = [level for level, expected in LEVEL_COLUMNS.items() if columns == expected]
    if len(matches) != 1 or (expected_level is not None and matches[0] != expected_level):
        raise ValueError("frontier record columns do not identify the expected level")
    records = packet["records"]
    if not isinstance(records, list) or not records:
        raise ValueError("frontier records must be a nonempty list")
    seen_refs: set[str] = set()
    for record in records:
        if not isinstance(record, list) or len(record) != len(columns):
            raise ValueError("frontier record width differs from record_columns")
        row = dict(zip(columns, record))
        ref = row.get("ref")
        if not isinstance(ref, str) or not ref or ref in seen_refs:
            raise ValueError("frontier references must be unique nonempty strings")
        seen_refs.add(ref)
        if not isinstance(row.get("effective_t"), int):
            raise ValueError("frontier effective time must be an integer")
        if "record_t" in row and not isinstance(row["record_t"], int):
            raise ValueError("frontier record time must be an integer")
        if "kind" in row and row["kind"] not in set(v1._KIND_CODES.values()):
            raise ValueError("frontier kind code is invalid")
        if "authority" in row and row["authority"] not in set(v1._AUTHORITY_CODES.values()):
            raise ValueError("frontier authority code is invalid")
        if "status" in row and row["status"] not in set(v1._STATUS_CODES.values()):
            raise ValueError("frontier status code is invalid")
        for name in ("requires", "effects"):
            atoms = row.get(name)
            if not isinstance(atoms, list) or any(
                not isinstance(atom, list) or len(atom) != 3 for atom in atoms
            ):
                raise ValueError(f"frontier {name} atoms are invalid")


SOLVER_PROMPT_PREFIX = """HIVE LUNA COMPRESSION FRONTIER v1 — FROZEN SOLVER

Solve each independent synthetic world using only its supplied representation.
Effective time determines chronology; record time is only arrival order.
Only canonical, completed actual/observation/message events with satisfied
preconditions can change current truth or knowledge. Plans, rumors, claims,
attempts, future events, and unsatisfied effects must not be promoted.

A full verbose packet uses named event fields. A compact packet contains
record_columns plus positional records: read every position only by its named
column. Possible compact columns are ref, effective_t, record_t, kind,
authority, status, requires, and effects. Missing columns were not supplied;
do not reconstruct them as facts. Compact codes, when present: kind A=actual,
P=plan, R=rumor, C=claim, O=observation, M=message; authority K=canonical,
N=noncanonical; status C=completed, P=planned, A=attempted, R=reported.
requires=[key,operator,value] and effects=[operator,key,value]. The relative
array order is preserved but does not replace effective chronology.

Return one answer value per supplied case, in the same order. The constrained
response contains one field named answers, whose array contains only A, B, C,
D, or INSUFFICIENT. Use INSUFFICIENT only when the supplied representation
cannot support one option. Return no case IDs, answer text, reasoning, or prose.
"""


def _case_payload(case: v1.BenchmarkCase, condition: str) -> dict[str, Any]:
    if condition == "raw_capability":
        item = v1._case_prompt_payload(case, "raw")
    elif condition in LEVELS:
        item = v1._case_prompt_payload(case, "compressed")
        item["representation"] = transform_compact_packet(
            item["representation"], condition
        )
    else:
        raise ValueError(f"unknown condition {condition!r}")
    return item


def build_solver_prompt(
    cases: Sequence[v1.BenchmarkCase], condition: str
) -> str:
    payload = {
        "representation_family": (
            "full_verbose_history"
            if condition == "raw_capability"
            else "compact_named_column_records"
        ),
        "cases": [_case_payload(case, condition) for case in cases],
    }
    return SOLVER_PROMPT_PREFIX + "\nINPUT:\n" + _pretty_json(payload)


def _input_payload(prompt: str) -> Mapping[str, Any]:
    marker = "\nINPUT:\n"
    if prompt.count(marker) != 1:
        raise ValueError("frontier prompt boundary mismatch")
    value = json.loads(prompt.split(marker, 1)[1])
    if not isinstance(value, dict):
        raise ValueError("frontier prompt input must be an object")
    return value


def build_call_plan(
    payload: Mapping[str, Any], cases: Sequence[v1.BenchmarkCase]
) -> tuple[PlannedCall, ...]:
    by_case = {case.case_id: case for case in cases}
    calls: list[PlannedCall] = []
    sequence = 1
    for batch in payload["batches"]:
        batch_cases = tuple(by_case[str(case_id)] for case_id in batch["case_ids"])
        calls.append(
            PlannedCall(
                sequence=sequence,
                stage="raw_gate",
                batch_id=int(batch["batch_id"]),
                condition="raw_capability",
                case_ids=tuple(case.case_id for case in batch_cases),
                prompt=build_solver_prompt(batch_cases, "raw_capability"),
                text_format=openai_text_format(len(batch_cases)),
            )
        )
        sequence += 1
    for batch in payload["batches"]:
        batch_cases = tuple(by_case[str(case_id)] for case_id in batch["case_ids"])
        for slot in batch["condition_order"]:
            level = SLOT_TO_LEVEL[str(slot)]
            calls.append(
                PlannedCall(
                    sequence=sequence,
                    stage="frontier",
                    batch_id=int(batch["batch_id"]),
                    condition=level,
                    case_ids=tuple(case.case_id for case in batch_cases),
                    prompt=build_solver_prompt(batch_cases, level),
                    text_format=openai_text_format(len(batch_cases)),
                )
            )
            sequence += 1
    if len(calls) != MAX_GENERATION_CALLS:
        raise RuntimeError("frontier call plan does not contain exactly 24 calls")
    return tuple(calls)


def _git_revision_and_sources(repo_root: Path) -> tuple[str, dict[str, str]]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hashes: dict[str, str] = {}
    for relative in SOURCE_FILES:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repo_root,
            capture_output=True,
        )
        if tracked.returncode != 0:
            raise RuntimeError(f"frontier source is not committed: {relative}")
        head = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        working_object = subprocess.run(
            ["git", "hash-object", "--path", relative, "--", relative],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        head_object = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if working_object != head_object:
            raise RuntimeError(f"frontier source differs from HEAD: {relative}")
        hashes[relative] = _sha256_bytes(head)
    return revision, dict(sorted(hashes.items()))


def _expanded_pack_hash(cases: Sequence[v1.BenchmarkCase]) -> str:
    expanded = v1._expanded_pack_payload(cases)
    return _sha256_text(_canonical_json(expanded))


def deterministic_preflight(
    repo_root: Path, *, require_committed: bool = True
) -> tuple[Mapping[str, Any], tuple[v1.BenchmarkCase, ...], tuple[PlannedCall, ...], Mapping[str, Any]]:
    case_path = repo_root / "benchmarks/decompression_test/CASE_PACK.json"
    if _sha256_bytes(case_path.read_bytes()) != FROZEN_CASE_PACK_SHA256:
        raise RuntimeError("frozen CASE_PACK.json changed")
    payload, cases = v1.load_case_pack(case_path)
    v1.validate_case_pack(payload, cases)
    expanded_hash = _expanded_pack_hash(cases)
    if expanded_hash != FROZEN_EXPANDED_PACK_SHA256:
        raise RuntimeError("expanded frozen worlds changed")
    calls = build_call_plan(payload, cases)
    config = solver_config()
    request_rows = []
    raw_upper = 0
    frontier_upper = 0
    for call in calls:
        request = {
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
        byte_upper = len(_canonical_json(request).encode("utf-8"))
        if call.stage == "raw_gate":
            raw_upper += byte_upper
        else:
            frontier_upper += byte_upper
        request_rows.append(
            {
                "sequence": call.sequence,
                "stage": call.stage,
                "batch_id": call.batch_id,
                "condition": call.condition,
                "case_ids": list(call.case_ids),
                "prompt_sha256": _sha256_text(call.prompt),
                "prompt_utf8_bytes": len(call.prompt.encode("utf-8")),
                "text_format_sha256": _sha256_text(_canonical_json(call.text_format)),
                "request_sha256": _sha256_text(_canonical_json(request)),
                "conservative_input_token_upper_bound": byte_upper,
            }
        )
    if raw_upper > RAW_INPUT_TOKEN_UPPER_BOUND:
        raise RuntimeError("Raw request-byte token upper bound exceeds frozen ceiling")
    if frontier_upper > FRONTIER_INPUT_TOKEN_UPPER_BOUND:
        raise RuntimeError("frontier request-byte token upper bound exceeds frozen ceiling")
    output_upper = MAX_GENERATION_CALLS * MAX_OUTPUT_TOKENS
    cost_upper = (
        (raw_upper + frontier_upper) * INPUT_USD_PER_MILLION / 1_000_000
        + output_upper * OUTPUT_USD_PER_MILLION / 1_000_000
    )
    if cost_upper > AUTHORIZED_COST_CEILING_USD:
        raise RuntimeError("conservative generation cost exceeds frozen authorization")
    positions = {
        level: sorted(
            index
            for batch in payload["batches"]
            for index, slot in enumerate(batch["condition_order"])
            if SLOT_TO_LEVEL[str(slot)] == level
        )
        for level in LEVELS
    }
    if any(sorted(value) != [0, 0, 1, 1, 2, 2] for value in positions.values()):
        raise RuntimeError("frontier level order is not fully counterbalanced")
    representation = {}
    for case in cases:
        raw = v1.raw_packet(case)
        representation[case.case_id] = {
            "raw": len(_canonical_json(raw).encode("utf-8")),
            **{
                level: len(
                    _canonical_json(
                        transform_compact_packet(v1.compressed_packet(case), level)
                    ).encode("utf-8")
                )
                for level in LEVELS
            },
        }
    if require_committed:
        revision, source_hashes = _git_revision_and_sources(repo_root)
    else:
        revision, source_hashes = "TEST_UNCOMMITTED", {}
    preflight = _sealed(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "source_revision": revision,
            "source_file_sha256": source_hashes,
            "case_pack_sha256": FROZEN_CASE_PACK_SHA256,
            "expanded_pack_sha256": expanded_hash,
            "solver_prompt_template_sha256": _sha256_text(SOLVER_PROMPT_PREFIX),
            "solver_config": config.to_mapping(),
            "solver_config_sha256": config.configuration_hash,
            "raw_gate": {
                "required_exact_correct": RAW_REQUIRED_CORRECT,
                "required_illegal_promotions": 0,
                "calls": RAW_CALLS,
                "cases": 20,
            },
            "levels": {level: list(LEVEL_COLUMNS[level]) for level in LEVELS},
            "slot_to_level": SLOT_TO_LEVEL,
            "frontier_position_counts": positions,
            "call_plan": request_rows,
            "representation_utf8_bytes_by_case": representation,
            "cost": {
                "pricing_usd_per_million": {
                    "input": INPUT_USD_PER_MILLION,
                    "output_including_reasoning": OUTPUT_USD_PER_MILLION,
                },
                "raw_input_token_upper_bound_from_request_utf8_bytes": raw_upper,
                "frontier_input_token_upper_bound_from_request_utf8_bytes": frontier_upper,
                "output_token_upper_bound": output_upper,
                "conservative_generation_cost_upper_bound_usd": cost_upper,
                "authorized_cost_ceiling_usd": AUTHORIZED_COST_CEILING_USD,
                "note": "UTF-8 request bytes are a conservative tokenizer-independent upper bound; actual API usage is authoritative.",
            },
        }
    )
    return payload, cases, calls, preflight


def _validate_metadata(
    metadata: Mapping[str, Any],
    *,
    config: FrozenSolverConfig,
    expected_text_format: Mapping[str, Any],
    expected_returned_model: str | None,
) -> tuple[str, str]:
    required = {
        "provider": "openai",
        "api": "responses",
        "provider_fallback": False,
        "sdk_max_retries": 0,
        "physical_attempts": 1,
        "adapter_status": "completed",
        "response_status": "completed",
        "requested_model": config.model,
        "configuration_hash": config.configuration_hash,
        "sdk_version": EXPECTED_OPENAI_SDK,
        "returned_service_tier": config.service_tier,
    }
    for name, value in required.items():
        if metadata.get(name) != value:
            raise ApparatusFailure(f"OpenAI metadata mismatch for {name}")
    if metadata.get("incomplete_details") is not None:
        raise ApparatusFailure("completed response retained incomplete details")
    if metadata.get("response_error") is not None:
        raise ApparatusFailure("completed response retained an error object")
    expected_format_hash = _sha256_text(_canonical_json(expected_text_format))
    if metadata.get("openai_text_format_sha256") != expected_format_hash:
        raise ApparatusFailure("structured-output format hash mismatch")
    returned_model = metadata.get("returned_model")
    response_id = metadata.get("response_id")
    if not isinstance(returned_model, str) or not returned_model:
        raise ApparatusFailure("returned model identity is missing")
    if expected_returned_model is not None and returned_model != expected_returned_model:
        raise ApparatusFailure("returned model identity drifted within the run")
    if not isinstance(response_id, str) or not response_id:
        raise ApparatusFailure("response ID is missing")
    counters = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    if any(
        isinstance(metadata.get(name), bool)
        or not isinstance(metadata.get(name), int)
        or metadata[name] < 0
        for name in counters
    ):
        raise ApparatusFailure("OpenAI token accounting is missing or invalid")
    if metadata["cached_input_tokens"] != 0 or metadata["cache_write_input_tokens"] != 0:
        raise ApparatusFailure("explicit no-breakpoint cache policy was violated")
    if metadata["reasoning_tokens"] > metadata["output_tokens"]:
        raise ApparatusFailure("reasoning tokens exceed output tokens")
    if metadata["total_tokens"] != metadata["input_tokens"] + metadata["output_tokens"]:
        raise ApparatusFailure("total token accounting is incoherent")
    return returned_model, response_id


class OpenAIAuditStore:
    """Small append-only store for native Responses API evidence."""

    def __init__(
        self,
        root: Path,
        *,
        ask_fn: Callable[..., str],
        config: FrozenSolverConfig,
    ) -> None:
        self.root = root
        self.calls_dir = root / "calls"
        self.decisions_dir = root / "decisions"
        self.events_path = root / "events.jsonl"
        self.ask_fn = ask_fn
        self.config = config
        self.records: list[CallRecord] = []
        self.returned_model: str | None = None
        root.mkdir(parents=True, exist_ok=False)
        self.calls_dir.mkdir()
        self.decisions_dir.mkdir()
        _write_exclusive(self.events_path, "")

    def _append_event(self, payload: Mapping[str, Any]) -> None:
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(payload) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def ask(self, planned: PlannedCall) -> str:
        if planned.sequence != len(self.records) + 1:
            raise ApparatusFailure("call sequence is not contiguous")
        call_id = f"call_{planned.sequence:06d}"
        started = _utc_now()
        self._append_event(
            {
                "event": "call_started",
                "at_utc": started,
                "call_id": call_id,
                "sequence": planned.sequence,
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "prompt_sha256": _sha256_text(planned.prompt),
            }
        )
        metadata: dict[str, Any] = {}
        response: str | None = None
        error: BaseException | None = None
        admission_error: BaseException | None = None
        try:
            response = self.ask_fn(
                planned.prompt,
                role="default",
                solver_config=self.config,
                metadata=metadata,
                openai_text_format=planned.text_format,
            )
        except BaseException as exc:  # preserve every failed physical request
            error = exc
        if error is None:
            try:
                returned_model, _ = _validate_metadata(
                    metadata,
                    config=self.config,
                    expected_text_format=planned.text_format,
                    expected_returned_model=self.returned_model,
                )
                if self.returned_model is None:
                    self.returned_model = returned_model
            except BaseException as exc:
                admission_error = exc
        status = (
            "completed"
            if error is None and admission_error is None
            else "transport_error" if error is not None else "metadata_rejected"
        )
        artifact = _sealed(
            {
                "schema_version": SCHEMA_VERSION,
                "call_id": call_id,
                "sequence": planned.sequence,
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "case_ids": list(planned.case_ids),
                "started_at_utc": started,
                "finished_at_utc": _utc_now(),
                "status": status,
                "request": {
                    "prompt": planned.prompt,
                    "prompt_sha256": _sha256_text(planned.prompt),
                    "openai_text_format": planned.text_format,
                    "openai_text_format_sha256": _sha256_text(
                        _canonical_json(planned.text_format)
                    ),
                    "solver_config": self.config.to_mapping(),
                    "solver_config_sha256": self.config.configuration_hash,
                },
                "response": {
                    "raw_text": response,
                    "sha256": _sha256_text(response) if response is not None else None,
                },
                "transport_metadata": _json_safe(metadata),
                "transport_error": _safe_error(error),
                "admission_error": _safe_error(admission_error),
            }
        )
        path = self.calls_dir / f"{call_id}.json"
        _write_exclusive(path, _pretty_json(artifact))
        file_hash = _sha256_bytes(path.read_bytes())
        record = CallRecord(
            sequence=planned.sequence,
            call_id=call_id,
            stage=planned.stage,
            batch_id=planned.batch_id,
            condition=planned.condition,
            artifact_path=path.relative_to(self.root).as_posix(),
            artifact_file_sha256=file_hash,
            status=status,
            metadata=copy.deepcopy(metadata),
        )
        self.records.append(record)
        self._append_event(
            {
                "event": "call_finished",
                "at_utc": _utc_now(),
                "call_id": call_id,
                "sequence": planned.sequence,
                "status": status,
                "artifact_path": record.artifact_path,
                "artifact_file_sha256": file_hash,
            }
        )
        if error is not None:
            raise ApparatusFailure(f"{call_id} transport failed: {error}") from None
        if admission_error is not None:
            raise ApparatusFailure(f"{call_id} metadata rejected: {admission_error}") from None
        assert response is not None
        return response

    def write_decision(self, record: CallRecord, payload: Mapping[str, Any]) -> None:
        path = self.decisions_dir / f"decision_{record.sequence:06d}.json"
        _write_exclusive(path, _pretty_json(_sealed(payload)))


def _score_summary(
    scores: Sequence[v2.LabelScore],
    by_case: Mapping[str, v1.BenchmarkCase],
) -> dict[str, Any]:
    rows = []
    for score in scores:
        row = asdict(score)
        case = by_case[score.case_id]
        row["family"] = case.family
        row["load"] = case.load
        rows.append(row)
    return {
        "total": len(scores),
        "admissible": sum(score.admissible for score in scores),
        "exact_correct": sum(score.answer_correct is True for score in scores),
        "insufficient_responses": sum(
            score.selected_label == "INSUFFICIENT" for score in scores
        ),
        "chronology_authority_errors": sum(
            score.chronology_authority_error is True for score in scores
        ),
        "illegal_state_promotions": sum(
            score.illegal_state_promotions or 0 for score in scores
        ),
        "grader_failures": sum(score.grader_status != "ran" for score in scores),
        "secondary_failures": sum(
            score.secondary_status != "ran" for score in scores
        ),
        "scores": rows,
    }


def classify_frontier(correct: Mapping[str, int]) -> str:
    values = [int(correct[level]) for level in LEVELS]
    if values[0] < 20:
        return "VALID_COMPRESSED_BASELINE_FAIL"
    first_failure = next((index for index, value in enumerate(values) if value < 20), None)
    if first_failure is None:
        return "VALID_RIGHT_CENSORED_ALL_PASS"
    if any(value == 20 for value in values[first_failure + 1 :]):
        return "VALID_NONMONOTONIC_DESCRIPTIVE"
    return f"VALID_FRONTIER_BOUNDARY_{LEVELS[first_failure - 1]}"


class LunaFrontierRunner:
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
        self.scores: dict[str, list[v2.LabelScore]] = {
            "raw_capability": [],
            **{level: [] for level in LEVELS},
        }

    def _run_call(
        self,
        audit: OpenAIAuditStore,
        planned: PlannedCall,
        by_case: Mapping[str, v1.BenchmarkCase],
    ) -> None:
        response = audit.ask(planned)
        record = audit.records[-1]
        cases = [by_case[case_id] for case_id in planned.case_ids]
        try:
            labels = parse_structured_labels(response, len(cases))
        except v2.ConstrainedInterfaceFailure as exc:
            rejected = [v2.rejected_score(case, planned.condition) for case in cases]
            audit.write_decision(
                record,
                {
                    "schema_version": SCHEMA_VERSION,
                    "call_id": record.call_id,
                    "status": "parser_rejected",
                    "stage": planned.stage,
                    "batch_id": planned.batch_id,
                    "condition": planned.condition,
                    "response_sha256": _sha256_text(response),
                    "parser_status": "failed",
                    "grader_status": "not_run",
                    "grader_agreement": None,
                    "error": str(exc),
                    "scores": [asdict(score) for score in rejected],
                },
            )
            self.scores[planned.condition].extend(rejected)
            raise ApparatusFailure(f"{record.call_id} strict parser rejected output") from None
        scores = [
            v2.grade_label(case, label, condition=planned.condition)
            for case, label in zip(cases, labels)
        ]
        self.scores[planned.condition].extend(scores)
        secondary_failed = any(score.secondary_status != "ran" for score in scores)
        audit.write_decision(
            record,
            {
                "schema_version": SCHEMA_VERSION,
                "call_id": record.call_id,
                "status": "secondary_failed" if secondary_failed else "graded",
                "stage": planned.stage,
                "batch_id": planned.batch_id,
                "condition": planned.condition,
                "response_sha256": _sha256_text(response),
                "parser_status": "passed",
                "grader_status": "ran",
                "grader_agreement": True,
                "labels": list(labels),
                "scores": [asdict(score) for score in scores],
            },
        )
        if secondary_failed:
            raise ApparatusFailure(
                f"{record.call_id} deterministic secondary evaluation failed"
            )

    @staticmethod
    def _usage(records: Sequence[CallRecord]) -> dict[str, Any]:
        def measured_int(record: CallRecord, name: str) -> int:
            value = record.metadata.get(name)
            return value if type(value) is int and value >= 0 else 0

        def measured_float(record: CallRecord, name: str) -> float:
            value = record.metadata.get(name)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

        by_condition: dict[str, dict[str, Any]] = {}
        for condition in ("raw_capability", *LEVELS):
            selected = [record for record in records if record.condition == condition]
            by_condition[condition] = {
                "call_artifacts": len(selected),
                "physical_generation_calls": sum(
                    measured_int(record, "physical_attempts") for record in selected
                ),
                "input_tokens": sum(measured_int(record, "input_tokens") for record in selected),
                "output_tokens": sum(measured_int(record, "output_tokens") for record in selected),
                "reasoning_tokens": sum(measured_int(record, "reasoning_tokens") for record in selected),
                "latency_seconds": sum(measured_float(record, "latency_seconds") for record in selected),
            }
        total_input = sum(value["input_tokens"] for value in by_condition.values())
        total_output = sum(value["output_tokens"] for value in by_condition.values())
        return {
            "by_condition": by_condition,
            "total": {
                "call_artifacts": len(records),
                "physical_generation_calls": sum(
                    measured_int(record, "physical_attempts") for record in records
                ),
                "input_tokens": total_input,
                "output_tokens": total_output,
                "reasoning_tokens": sum(value["reasoning_tokens"] for value in by_condition.values()),
                "latency_seconds": sum(value["latency_seconds"] for value in by_condition.values()),
                "estimated_generation_cost_usd": (
                    total_input * INPUT_USD_PER_MILLION / 1_000_000
                    + total_output * OUTPUT_USD_PER_MILLION / 1_000_000
                ),
            },
        }

    def _finish(
        self,
        audit: OpenAIAuditStore,
        *,
        preflight: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        _write_exclusive(self.output_dir / "RESULT.json", _pretty_json(_sealed(result)))
        _write_exclusive(
            self.output_dir / "RUN_STATUS.json",
            _pretty_json(
                _sealed(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "finished_at_utc": _utc_now(),
                        "validity": result["validity"],
                        "result_code": result["result_code"],
                        "call_artifacts": len(audit.records),
                        "physical_generation_calls": result["usage"]["total"][
                            "physical_generation_calls"
                        ],
                    }
                )
            ),
        )
        rows = []
        for path in sorted(
            item
            for item in self.output_dir.rglob("*")
            if item.is_file() and item.name != "EVIDENCE_INDEX.json"
        ):
            rows.append(
                {
                    "path": path.relative_to(self.output_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_bytes(path.read_bytes()),
                }
            )
        index = _sealed(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "source_revision": preflight["source_revision"],
                "file_count": len(rows),
                "total_bytes": sum(row["bytes"] for row in rows),
                "files": rows,
            }
        )
        _write_exclusive(
            self.output_dir / "EVIDENCE_INDEX.json", _pretty_json(index)
        )
        return result

    def run(self) -> Mapping[str, Any]:
        payload, cases, calls, preflight = deterministic_preflight(
            self.repo_root, require_committed=self.require_committed
        )
        by_case = {case.case_id: case for case in cases}
        audit = OpenAIAuditStore(
            self.output_dir, ask_fn=self.ask_fn, config=self.config
        )
        _write_exclusive(
            self.output_dir / "PRECHECK.json", _pretty_json(preflight)
        )
        manifest = _sealed(
            {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "protocol_version": PROTOCOL_VERSION,
                "created_at_utc": _utc_now(),
                "source_revision": preflight["source_revision"],
                "precheck_sha256": preflight["payload_sha256"],
                "solver_config": self.config.to_mapping(),
                "solver_config_sha256": self.config.configuration_hash,
                "expected_openai_sdk": EXPECTED_OPENAI_SDK,
                "generation_call_budget": {
                    "raw_gate": RAW_CALLS,
                    "frontier_if_gate_passes": FRONTIER_CALLS,
                    "maximum": MAX_GENERATION_CALLS,
                    "attempts_per_call": 1,
                },
                "no_retry": True,
                "no_repair": True,
                "no_prompt_tuning_after_outputs": True,
                "raw_is_capability_gate_not_contemporaneous_baseline": True,
                "retrieval_deferred": True,
            }
        )
        _write_exclusive(
            self.output_dir / "MANIFEST.json", _pretty_json(manifest)
        )
        try:
            for planned in calls[:RAW_CALLS]:
                self._run_call(audit, planned, by_case)
        except ApparatusFailure as exc:
            result = {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "validity": "INVALID",
                "result_code": "INVALID_APPARATUS",
                "apparatus_failure": str(exc),
                "raw": _score_summary(self.scores["raw_capability"], by_case),
                "frontier": "NOT_RUN",
                "usage": self._usage(audit.records),
                "returned_model": audit.returned_model,
                "evidence_interpretation": "No representation claim is licensed.",
            }
            return self._finish(audit, preflight=preflight, result=result)
        raw_summary = _score_summary(self.scores["raw_capability"], by_case)
        raw_pass = (
            raw_summary["exact_correct"] == RAW_REQUIRED_CORRECT
            and raw_summary["illegal_state_promotions"] == 0
        )
        if not raw_pass:
            result = {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "validity": "VALID",
                "result_code": "VALID_RAW_CAPABILITY_FAIL",
                "raw": raw_summary,
                "frontier": "NOT_RUN",
                "usage": self._usage(audit.records),
                "returned_model": audit.returned_model,
                "evidence_interpretation": (
                    "This Luna run did not clear the underlying-task capability gate; "
                    "representation quality is not interpreted."
                ),
            }
            return self._finish(audit, preflight=preflight, result=result)
        try:
            for planned in calls[RAW_CALLS:]:
                self._run_call(audit, planned, by_case)
        except ApparatusFailure as exc:
            result = {
                "schema_version": SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "validity": "INVALID",
                "result_code": "INVALID_APPARATUS",
                "apparatus_failure": str(exc),
                "raw": raw_summary,
                "frontier": {
                    level: _score_summary(self.scores[level], by_case)
                    for level in LEVELS
                },
                "usage": self._usage(audit.records),
                "returned_model": audit.returned_model,
                "evidence_interpretation": "No frontier claim is licensed.",
            }
            return self._finish(audit, preflight=preflight, result=result)
        frontier = {
            level: _score_summary(self.scores[level], by_case) for level in LEVELS
        }
        correct = {level: frontier[level]["exact_correct"] for level in LEVELS}
        result_code = classify_frontier(correct)
        representation_totals = {
            condition: sum(
                row[condition]
                for row in preflight["representation_utf8_bytes_by_case"].values()
            )
            for condition in ("raw", *LEVELS)
        }
        result = {
            "schema_version": SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "validity": "VALID",
            "result_code": result_code,
            "raw": raw_summary,
            "frontier": frontier,
            "representation_utf8_bytes": representation_totals,
            "representation_ratios_to_raw": {
                level: representation_totals[level] / representation_totals["raw"]
                for level in LEVELS
            },
            "usage": self._usage(audit.records),
            "returned_model": audit.returned_model,
            "scoped_evidence": {
                "full_compact_usable": (
                    "SUPPORTED" if correct["C0"] == 20 else "NOT_SUPPORTED"
                ),
                "record_time_removal_zero_distortion": (
                    "SUPPORTED"
                    if correct["C0"] == 20 and correct["C1"] == 20
                    else "NOT_SUPPORTED"
                ),
                "applicability_bundle_removal_zero_distortion": (
                    "SUPPORTED"
                    if all(correct[level] == 20 for level in LEVELS)
                    else "NOT_SUPPORTED"
                ),
                "broad_hive_claim": "NOT_PROVEN",
            },
            "interpretation_rule": (
                "Confirmatory interpretation follows C0→C1→C2 and stops at the "
                "first sub-20/20 level; later recovery is descriptive only."
            ),
        }
        return self._finish(audit, preflight=preflight, result=result)


def verify_run(run_dir: Path) -> Mapping[str, Any]:
    index_path = run_dir / "EVIDENCE_INDEX.json"
    if not index_path.is_file():
        raise ApparatusFailure("EVIDENCE_INDEX.json is missing")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    _verify_seal(index)
    expected_paths = {row["path"] for row in index["files"]}
    actual_paths = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path.name != "EVIDENCE_INDEX.json"
    }
    if actual_paths != expected_paths:
        raise ApparatusFailure("evidence file set differs from the sealed index")
    for row in index["files"]:
        path = run_dir / row["path"]
        if path.stat().st_size != row["bytes"] or _sha256_bytes(path.read_bytes()) != row["sha256"]:
            raise ApparatusFailure(f"evidence changed: {row['path']}")
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            _verify_seal(payload)
    calls = sorted((run_dir / "calls").glob("call_*.json"))
    decisions = sorted((run_dir / "decisions").glob("decision_*.json"))
    if len(decisions) > len(calls) or len(calls) - len(decisions) > 1:
        raise ApparatusFailure("call and decision counts are inconsistent")
    if len(decisions) < len(calls):
        final_call = json.loads(calls[-1].read_text(encoding="utf-8"))
        if final_call.get("status") == "completed":
            raise ApparatusFailure("a completed call is missing its decision")
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    if len(events) != 2 * len(calls):
        raise ApparatusFailure("audit journal does not contain two events per call")
    physical_attempts = 0
    for path in calls:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        attempts = artifact.get("transport_metadata", {}).get("physical_attempts")
        if type(attempts) is int and attempts >= 0:
            physical_attempts += attempts
    return {
        "verified": True,
        "file_count": index["file_count"],
        "total_bytes": index["total_bytes"],
        "call_artifacts": len(calls),
        "physical_generation_calls": physical_attempts,
        "source_revision": index["source_revision"],
    }


def _check_live_prerequisites() -> None:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY is not present; no inference was started")
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError(
            "openai==3.3.1 is not installed; no inference was started"
        ) from exc
    if getattr(openai, "__version__", None) != EXPECTED_OPENAI_SDK:
        raise RuntimeError(
            f"openai SDK must be exactly {EXPECTED_OPENAI_SDK}; no inference was started"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acknowledge-frozen-luna-frontier-v1",
        action="store_true",
        help="required acknowledgement that this is the one frozen run",
    )
    parser.add_argument("--output-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        print(_pretty_json(verify_run(args.verify)), end="")
        return 0
    if not args.acknowledge_frozen_luna_frontier_v1:
        parser.error("--acknowledge-frozen-luna-frontier-v1 is required")
    _check_live_prerequisites()
    repo_root = Path(__file__).resolve().parents[1]
    result = LunaFrontierRunner(
        repo_root=repo_root,
        output_dir=(repo_root / args.output_dir).resolve(),
    ).run()
    print(_pretty_json(result), end="")
    return 0 if result["validity"] == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
