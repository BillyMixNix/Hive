"""Executable, deterministic Hive whole-system research reference model."""

from hive_reference.adapter import FrozenDecompressionAdapter
from hive_reference.demo import build_demo_ledger, build_demo_tasks, run_demo
from hive_reference.model import EventLedger
from hive_reference.representation import (
    ReferenceCompressor,
    RepresentationRootCommitment,
    SelectiveDecompressor,
)

__all__ = [
    "EventLedger",
    "FrozenDecompressionAdapter",
    "ReferenceCompressor",
    "RepresentationRootCommitment",
    "SelectiveDecompressor",
    "build_demo_ledger",
    "build_demo_tasks",
    "run_demo",
]
