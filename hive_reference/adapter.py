"""Thin, read-only adapter to the frozen decompression benchmark.

The adapter intentionally reuses the benchmark's own loader, decoder, replay,
and statistics rather than copying its case pack or creating another inference
path.  It establishes deterministic harness connectivity only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from kingdom.decompression_test import (
    _representation_stats as _legacy_representation_stats,
    load_case_pack,
    validate_case_pack,
)


DEFAULT_CASE_PACK = Path("benchmarks/decompression_test/CASE_PACK.json")


@dataclass(frozen=True)
class FrozenCodecAdapterReport:
    case_pack_sha256: str
    case_count: int
    case_ids: tuple[str, ...]
    all_source_hashes_recomputed: bool
    all_compressed_replay_matches: bool
    compressed_required_ref_recall: float
    raw_total_bytes: int
    retrieval_total_bytes: int
    compressed_total_bytes: int
    compressed_to_raw_byte_ratio: float
    inference_calls: int = 0

    def to_mapping(self) -> dict[str, Any]:
        return {
            "all_compressed_replay_matches": self.all_compressed_replay_matches,
            "all_source_hashes_recomputed": self.all_source_hashes_recomputed,
            "case_count": self.case_count,
            "case_ids": list(self.case_ids),
            "case_pack_sha256": self.case_pack_sha256,
            "compressed_required_ref_recall": self.compressed_required_ref_recall,
            "compressed_to_raw_byte_ratio": self.compressed_to_raw_byte_ratio,
            "compressed_total_bytes": self.compressed_total_bytes,
            "inference_calls": self.inference_calls,
            "raw_total_bytes": self.raw_total_bytes,
            "retrieval_total_bytes": self.retrieval_total_bytes,
        }


class FrozenDecompressionAdapter:
    def inspect(self, case_pack_path: str | Path = DEFAULT_CASE_PACK) -> FrozenCodecAdapterReport:
        path = Path(case_pack_path)
        raw_bytes = path.read_bytes()
        payload, cases = load_case_pack(path)
        validate_case_pack(payload, cases)
        stats = tuple(_legacy_representation_stats(case) for case in cases)
        totals = {
            condition: sum(int(item["representation_utf8_bytes"][condition]) for item in stats)
            for condition in ("raw", "retrieval", "compressed")
        }
        return FrozenCodecAdapterReport(
            case_pack_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            case_count=len(cases),
            case_ids=tuple(case.case_id for case in cases),
            all_source_hashes_recomputed=all(bool(item["raw_source_hashes_recomputed"]) for item in stats),
            all_compressed_replay_matches=all(bool(item["compressed_task_replay_match"]) for item in stats),
            compressed_required_ref_recall=min(
                float(item["compressed_required_ref_recall"]) for item in stats
            ),
            raw_total_bytes=totals["raw"],
            retrieval_total_bytes=totals["retrieval"],
            compressed_total_bytes=totals["compressed"],
            compressed_to_raw_byte_ratio=round(
                totals["compressed"] / max(totals["raw"], 1), 9
            ),
        )


@dataclass(frozen=True)
class CapabilityGate:
    solver_id: str
    raw_correct: int
    raw_total: int
    required_accuracy: float
    passed: bool
    representation_interpretation_allowed: bool


def capability_gate_from_result(
    result: Mapping[str, Any],
    *,
    solver_id: str,
    required_accuracy: float = 0.8,
) -> CapabilityGate:
    if not 0.0 <= required_accuracy <= 1.0:
        raise ValueError("required accuracy must be in [0, 1]")
    raw = result["condition_summaries"]["raw"]
    correct = int(raw["exact_correct"])
    total = int(raw["total"])
    valid = result.get("validity") == "VALID"
    passed = valid and total > 0 and correct / total >= required_accuracy
    return CapabilityGate(
        solver_id=solver_id,
        raw_correct=correct,
        raw_total=total,
        required_accuracy=required_accuracy,
        passed=passed,
        representation_interpretation_allowed=passed,
    )


def load_result(path: str | Path) -> Mapping[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
