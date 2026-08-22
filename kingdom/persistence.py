from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .arena import ArenaExecution, ArenaObservation, MissingCapability
from .construction import BuildTarget, ConstructionGraph, ConstructionRun
from .core import (
    BranchResult,
    BranchSpec,
    CognitivePacket,
    ComprehensionProbe,
    Evidence,
    HashChainLedger,
    KingdomRun,
    Seed,
    StructureMap,
)
from .forge import CandidateValidation, ForgeAttempt


@dataclass(frozen=True)
class ConstructionRecord:
    run_id: str
    path: str
    sha256: str


class ConstructionRecorder:
    """Persist and restore tamper-evident construction checkpoints."""

    SCHEMA_VERSION = 2

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
            "schema_version": ConstructionRecorder.SCHEMA_VERSION,
            "base_run": asdict(run.base_run),
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
        destination = self.root / (
            f"{run.base_run.run_id}-{digest[:12]}-construction.json"
        )

        if not destination.exists():
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

    def latest_record(self, run_id: str) -> ConstructionRecord | None:
        if not self.ledger.verify():
            raise ValueError("construction ledger failed verification")
        if not self.ledger.path.exists():
            return None
        latest: ConstructionRecord | None = None
        with self.ledger.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("kind") != "construction_run":
                    continue
                payload = event.get("payload") or {}
                if payload.get("run_id") != run_id:
                    continue
                latest = ConstructionRecord(
                    run_id=run_id,
                    path=str(payload.get("construction_file") or ""),
                    sha256=str(payload.get("sha256") or ""),
                )
        return latest

    def load_verified(self, run_id: str) -> ConstructionRun:
        record = self.latest_record(run_id)
        if record is None:
            raise FileNotFoundError(f"no construction checkpoint for run {run_id}")
        if not self.verify(record):
            raise ValueError("construction checkpoint hash does not match ledger")
        return self.load(record.path)

    @classmethod
    def load(cls, path: str | Path) -> ConstructionRun:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported construction checkpoint schema")

        base_payload = payload["base_run"]
        base_run = KingdomRun(
            run_id=str(base_payload["run_id"]),
            seed=Seed(**base_payload["seed"]),
            branches=tuple(_branch_spec(item) for item in base_payload.get("branches", [])),
            results=tuple(_branch_result(item) for item in base_payload.get("results", [])),
            structure=_structure(base_payload.get("structure") or {}),
            packet=_packet(base_payload.get("packet") or {}),
            probes=tuple(_probe(item) for item in base_payload.get("probes", [])),
            started_at=float(base_payload.get("started_at", 0.0)),
            finished_at=float(base_payload.get("finished_at", 0.0)),
        )

        graph_payload = payload.get("construction_graph") or {}
        graph = ConstructionGraph(
            targets={
                key: BuildTarget(**value)
                for key, value in (graph_payload.get("targets") or {}).items()
            },
            children={
                key: list(value)
                for key, value in (graph_payload.get("children") or {}).items()
            },
            resolution_modes=dict(graph_payload.get("resolution_modes") or {}),
        )

        return ConstructionRun(
            base_run=base_run,
            verified_results=tuple(
                _branch_result(item) for item in payload.get("verified_results", [])
            ),
            arena_executions=tuple(
                _arena_execution(item) for item in payload.get("arena_executions", [])
            ),
            graph=graph,
            structure=_structure(payload.get("structure") or {}),
            packet=_packet(payload.get("packet") or {}),
            probes=tuple(_probe(item) for item in payload.get("probes", [])),
            forge_attempts=tuple(
                _forge_attempt(item) for item in payload.get("forge_attempts", [])
            ),
        )


def _branch_spec(item: dict[str, Any]) -> BranchSpec:
    return BranchSpec(**item)


def _evidence(item: dict[str, Any]) -> Evidence:
    return Evidence(**item)


def _branch_result(item: dict[str, Any]) -> BranchResult:
    return BranchResult(
        branch_id=str(item.get("branch_id") or ""),
        findings=tuple(item.get("findings") or ()),
        evidence=tuple(_evidence(value) for value in item.get("evidence", [])),
        assumptions=tuple(item.get("assumptions") or ()),
        uncertainties=tuple(item.get("uncertainties") or ()),
        next_branches=tuple(_branch_spec(value) for value in item.get("next_branches", [])),
    )


def _structure(item: dict[str, Any]) -> StructureMap:
    return StructureMap(
        invariants=tuple(item.get("invariants") or ()),
        disagreements=tuple(item.get("disagreements") or ()),
        hinge_assumptions=tuple(item.get("hinge_assumptions") or ()),
        causal_links=tuple(item.get("causal_links") or ()),
        anomalies=tuple(item.get("anomalies") or ()),
        unknowns=tuple(item.get("unknowns") or ()),
        provenance={
            key: tuple(value)
            for key, value in (item.get("provenance") or {}).items()
        },
    )


def _packet(item: dict[str, Any]) -> CognitivePacket:
    return CognitivePacket(
        title=str(item.get("title") or ""),
        orientation=str(item.get("orientation") or ""),
        load_bearing_insights=tuple(item.get("load_bearing_insights") or ()),
        uncertainty=tuple(item.get("uncertainty") or ()),
        next_moves=tuple(item.get("next_moves") or ()),
        inspectable_refs={
            key: tuple(value)
            for key, value in (item.get("inspectable_refs") or {}).items()
        },
    )


def _probe(item: dict[str, Any]) -> ComprehensionProbe:
    return ComprehensionProbe(**item)


def _arena_execution(item: dict[str, Any]) -> ArenaExecution:
    observation_payload = dict(item.get("observation") or {})
    observation_payload["artifacts"] = tuple(observation_payload.get("artifacts") or ())
    missing_payload = item.get("missing")
    return ArenaExecution(
        observation=ArenaObservation(**observation_payload),
        missing=MissingCapability(**missing_payload) if missing_payload else None,
    )


def _forge_attempt(item: dict[str, Any]) -> ForgeAttempt:
    validation_payload = item.get("validation")
    validation = CandidateValidation(**validation_payload) if validation_payload else None
    return ForgeAttempt(
        target_id=str(item.get("target_id") or ""),
        capability=str(item.get("capability") or ""),
        operation=str(item.get("operation") or ""),
        status=str(item.get("status") or "unavailable"),
        candidate_fingerprint=str(item.get("candidate_fingerprint") or ""),
        detail=str(item.get("detail") or ""),
        registered=bool(item.get("registered")),
        validation=validation,
    )
