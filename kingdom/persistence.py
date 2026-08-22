from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .construction import ConstructionRun
from .core import HashChainLedger


@dataclass(frozen=True)
class ConstructionRecord:
    run_id: str
    path: str
    sha256: str


class ConstructionRecorder:
    """Persist the post-Kingdom construction state and anchor its hash in the ledger."""

    def __init__(
        self,
        root: str | Path = ".hive/kingdom/construction_runs",
        *,
        ledger: HashChainLedger,
    ):
        self.root = Path(root)
        self.ledger = ledger

    @staticmethod
    def _payload(run: ConstructionRun) -> dict[str, Any]:
        graph = run.graph
        return {
            "schema_version": 1,
            "base_run_id": run.base_run.run_id,
            "seed": asdict(run.base_run.seed),
            "branches": [asdict(item) for item in run.base_run.branches],
            "verified_results": [asdict(item) for item in run.verified_results],
            "arena_executions": [asdict(item) for item in run.arena_executions],
            "construction_graph": {
                "targets": {key: asdict(value) for key, value in graph.targets.items()},
                "children": {key: list(value) for key, value in graph.children.items()},
                "resolution_modes": dict(graph.resolution_modes),
            },
            "structure": asdict(run.structure),
            "packet": asdict(run.packet),
            "probes": [asdict(item) for item in run.probes],
            "forge_attempts": [asdict(item) for item in run.forge_attempts],
        }

    @staticmethod
    def _encode(payload: dict[str, Any]) -> bytes:
        return (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")

    def persist(self, run: ConstructionRun) -> ConstructionRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = self._payload(run)
        encoded = self._encode(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        destination = self.root / f"{run.base_run.run_id}-construction.json"

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(self.root),
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

        record = ConstructionRecord(
            run_id=run.base_run.run_id,
            path=str(destination),
            sha256=digest,
        )
        self.ledger.append(
            "construction_run",
            {
                "run_id": record.run_id,
                "construction_file": record.path,
                "sha256": record.sha256,
                "arena_execution_count": len(run.arena_executions),
                "target_count": len(run.graph.targets),
                "forge_attempt_count": len(run.forge_attempts),
                "frontier_count": len(run.graph.frontier()),
            },
        )
        return record

    @staticmethod
    def verify(record: ConstructionRecord) -> bool:
        path = Path(record.path)
        if not path.is_file():
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest == record.sha256
