"""Source-preserving adapter contract for Hive Compressor.

Human language is evidence. This module keeps it verbatim and separate from the
machine-state records that are eligible for compression.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from .compressor import C1_FIELDS, CompressionError


FORBIDDEN_RECORD_TEXT_FIELDS = {
    "raw_text",
    "source_text",
    "human_text",
    "message_text",
    "verbatim",
    "original_text",
}


@dataclass(frozen=True)
class SourceEvidence:
    ref: str
    text: str
    source_type: str = "human"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, str]:
        return {
            "ref": self.ref,
            "source_type": self.source_type,
            "text": self.text,
            "sha256": self.sha256,
        }


def preserve_source(ref: str, text: str, source_type: str = "human") -> SourceEvidence:
    if not isinstance(ref, str) or not ref.strip():
        raise CompressionError("source ref must be a non-empty string")
    if not isinstance(text, str):
        raise CompressionError("source text must be a string")
    if not isinstance(source_type, str) or not source_type.strip():
        raise CompressionError("source_type must be a non-empty string")
    return SourceEvidence(ref=ref.strip(), text=text, source_type=source_type.strip())


def _validate_machine_record(record: Any, index: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise CompressionError(f"derived record {index} must be an object")

    forbidden = FORBIDDEN_RECORD_TEXT_FIELDS.intersection(record)
    if forbidden:
        raise CompressionError(
            "derived machine state must not embed preserved human text fields: "
            + ", ".join(sorted(forbidden))
        )

    missing = [field for field in C1_FIELDS if field not in record]
    if missing:
        raise CompressionError(
            f"derived record {index} is missing required semantic fields: {', '.join(missing)}"
        )

    unknown = set(record) - set(C1_FIELDS)
    if unknown:
        raise CompressionError(
            f"derived record {index} contains non-C1 state fields: "
            + ", ".join(sorted(unknown))
        )

    return dict(record)


def build_adapter_packet(
    sources: Iterable[SourceEvidence],
    linked_records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build a source-preserving packet before compression.

    `linked_records` entries have this shape:

        {"record": <canonical C1 record>, "source_refs": ["msg-1", ...]}

    Source text remains outside `compression_records`. Only canonical machine
    records flow into the compressor.
    """
    source_list = list(sources)
    source_index: dict[str, SourceEvidence] = {}
    for source in source_list:
        if not isinstance(source, SourceEvidence):
            raise CompressionError("sources must contain SourceEvidence objects")
        if source.ref in source_index:
            raise CompressionError(f"duplicate source ref: {source.ref}")
        source_index[source.ref] = source

    compression_records: list[dict[str, Any]] = []
    lineage: dict[str, list[str]] = {}

    for index, item in enumerate(linked_records):
        if not isinstance(item, dict):
            raise CompressionError(f"linked record {index} must be an object")

        record = _validate_machine_record(item.get("record"), index)
        source_refs = item.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            raise CompressionError(f"derived record {index} must have at least one source_ref")
        if not all(isinstance(ref, str) and ref for ref in source_refs):
            raise CompressionError(f"derived record {index} has invalid source_refs")

        missing_sources = [ref for ref in source_refs if ref not in source_index]
        if missing_sources:
            raise CompressionError(
                f"derived record {index} references unknown source(s): "
                + ", ".join(missing_sources)
            )

        record_ref = str(record["ref"])
        if record_ref in lineage:
            raise CompressionError(f"duplicate derived record ref: {record_ref}")

        compression_records.append(record)
        lineage[record_ref] = list(source_refs)

    return {
        "schema": "hive.source-preserving-adapter.v1",
        "compression_records": compression_records,
        "lineage": lineage,
        "source_evidence": [source.as_dict() for source in source_list],
    }


def recover_source(packet: dict[str, Any], source_ref: str) -> str:
    """Return the exact preserved source text for a reference."""
    for source in packet.get("source_evidence", []):
        if source.get("ref") == source_ref:
            text = source.get("text")
            if not isinstance(text, str):
                raise CompressionError(f"source {source_ref} has invalid text")
            actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual_hash != source.get("sha256"):
                raise CompressionError(f"source {source_ref} failed integrity check")
            return text
    raise CompressionError(f"unknown source ref: {source_ref}")
