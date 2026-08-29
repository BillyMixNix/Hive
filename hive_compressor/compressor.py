"""Deterministic authority-aware state projection for the Hive Compressor MVP.

This module intentionally starts with the representation that has actually been
benchmarked: structured state/event records. It does not pretend to be a generic
free-text summarizer.
"""

from __future__ import annotations

import json
import math
from typing import Any, Iterable


C1_FIELDS = (
    "ref",
    "effective_t",
    "kind",
    "authority",
    "status",
    "requires",
    "effects",
)

KNOWN_DROPPABLE_FIELDS = {"record_t"}


class CompressionError(ValueError):
    """Raised when input cannot be compressed without violating the contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _estimated_tokens(text: str) -> int:
    """Provider-neutral rough token estimate, explicitly not a billing count."""
    return max(0, math.ceil(len(text) / 4))


def _validate_record(record: Any, index: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise CompressionError(f"record {index} must be an object")

    missing = [field for field in C1_FIELDS if field not in record]
    if missing:
        raise CompressionError(
            f"record {index} is missing required semantic fields: {', '.join(missing)}"
        )

    unknown = set(record) - set(C1_FIELDS) - KNOWN_DROPPABLE_FIELDS
    if unknown:
        raise CompressionError(
            "record "
            f"{index} contains unknown fields that C1 has not been approved to drop: "
            + ", ".join(sorted(unknown))
        )

    if not isinstance(record.get("requires"), list):
        raise CompressionError(f"record {index}.requires must be a list")
    if not isinstance(record.get("effects"), (list, dict)):
        raise CompressionError(f"record {index}.effects must be a list or object")

    return record


def compress_records(records: Iterable[dict[str, Any]], mode: str = "c1") -> dict[str, Any]:
    """Compress canonical Hive state records.

    Modes:
      * raw: canonicalize only; useful as a baseline.
      * c1: retain authority/time/status/dependency/effect semantics and omit record_t.

    The function fails closed when it sees a field that the C1 contract does not
    explicitly know how to preserve or omit.
    """
    if mode not in {"raw", "c1"}:
        raise CompressionError("mode must be 'raw' or 'c1'")

    if not isinstance(records, list):
        records = list(records)

    validated = [_validate_record(record, idx) for idx, record in enumerate(records)]

    raw_payload = validated
    if mode == "raw":
        output = [dict(record) for record in validated]
        omitted_fields: list[str] = []
    else:
        output = [
            {field: record[field] for field in C1_FIELDS}
            for record in validated
        ]
        omitted_fields = ["record_t"] if any("record_t" in r for r in validated) else []

    before_text = _canonical_json(raw_payload)
    after_text = _canonical_json(output)
    before_bytes = len(before_text.encode("utf-8"))
    after_bytes = len(after_text.encode("utf-8"))
    bytes_saved = max(0, before_bytes - after_bytes)
    reduction_percent = (bytes_saved / before_bytes * 100.0) if before_bytes else 0.0

    return {
        "mode": mode,
        "schema": "hive.semantic-ledger.v1",
        "records": output,
        "omitted_fields": omitted_fields,
        "stats": {
            "records": len(output),
            "input_bytes": before_bytes,
            "output_bytes": after_bytes,
            "bytes_saved": bytes_saved,
            "reduction_percent": round(reduction_percent, 2),
            "estimated_input_tokens": _estimated_tokens(before_text),
            "estimated_output_tokens": _estimated_tokens(after_text),
            "token_count_note": "rough provider-neutral estimate; not billing tokens",
        },
    }
