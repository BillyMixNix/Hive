from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Seed:
    text: str
    context: str = ""
    goal: str = "increase operator understanding"


@dataclass(frozen=True)
class BranchSpec:
    branch_id: str
    lens: str
    question: str
    assumption_shift: str = ""
    parent_id: str | None = None
    depth: int = 0

    def fingerprint(self) -> str:
        payload = "|".join(
            part.strip().lower()
            for part in (self.lens, self.question, self.assumption_shift)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Evidence:
    claim: str
    stance: str
    confidence: float
    source: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.stance not in {"support", "contradict", "observe", "uncertain"}:
            raise ValueError(f"unsupported evidence stance: {self.stance}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class BranchResult:
    branch_id: str
    findings: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    assumptions: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    next_branches: tuple[BranchSpec, ...] = ()


@dataclass(frozen=True)
class StructureMap:
    invariants: tuple[str, ...] = ()
    disagreements: tuple[str, ...] = ()
    hinge_assumptions: tuple[str, ...] = ()
    causal_links: tuple[str, ...] = ()
    anomalies: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    provenance: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class CognitivePacket:
    title: str
    orientation: str
    load_bearing_insights: tuple[str, ...]
    uncertainty: tuple[str, ...]
    next_moves: tuple[str, ...]
    inspectable_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ComprehensionProbe:
    probe_id: str
    question: str
    target: str


@dataclass(frozen=True)
class ComprehensionAssessment:
    score: float
    understood: tuple[str, ...]
    missed: tuple[str, ...]
    reexpand: tuple[str, ...]
    feedback: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")


@dataclass(frozen=True)
class KingdomConfig:
    max_branches: int = 24
    max_depth: int = 1
    workers: int = 4
    codec_items: int = 10

    def __post_init__(self) -> None:
        if self.max_branches < 1:
            raise ValueError("max_branches must be >= 1")
        if self.max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if self.workers < 1:
            raise ValueError("workers must be >= 1")
        if self.codec_items < 1:
            raise ValueError("codec_items must be >= 1")


@dataclass(frozen=True)
class KingdomRun:
    run_id: str
    seed: Seed
    branches: tuple[BranchSpec, ...]
    results: tuple[BranchResult, ...]
    structure: StructureMap
    packet: CognitivePacket
    probes: tuple[ComprehensionProbe, ...]
    started_at: float
    finished_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KingdomProvider(Protocol):
    def decompose(self, seed: Seed, config: KingdomConfig) -> Sequence[BranchSpec]: ...

    def explore(self, seed: Seed, branch: BranchSpec) -> BranchResult: ...

    def integrate(
        self,
        seed: Seed,
        branches: Sequence[BranchSpec],
        results: Sequence[BranchResult],
    ) -> StructureMap: ...

    def encode(
        self,
        seed: Seed,
        structure: StructureMap,
        config: KingdomConfig,
    ) -> CognitivePacket: ...

    def make_probes(
        self,
        seed: Seed,
        structure: StructureMap,
        packet: CognitivePacket,
    ) -> Sequence[ComprehensionProbe]: ...

    def assess(
        self,
        seed: Seed,
        structure: StructureMap,
        probes: Sequence[ComprehensionProbe],
        answers: Mapping[str, str],
    ) -> ComprehensionAssessment: ...


class HashChainLedger:
    """Small append-only JSONL ledger with tamper-evident record chaining."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = ""
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = line
        if not last:
            return "0" * 64
        return str(json.loads(last)["record_hash"])

    def append(self, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            previous = self._last_hash()
            body = {
                "kind": kind,
                "payload": dict(payload),
                "previous_hash": previous,
                "timestamp": time.time(),
            }
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
            record = dict(body)
            record["record_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            return record

    def verify(self) -> bool:
        previous = "0" * 64
        if not self.path.exists():
            return True
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("previous_hash") != previous:
                    return False
                body = {key: value for key, value in record.items() if key != "record_hash"}
                canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
                expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                if record.get("record_hash") != expected:
                    return False
                previous = expected
        return True


class KingdomEngine:
    def __init__(
        self,
        provider: KingdomProvider,
        *,
        config: KingdomConfig | None = None,
        run_dir: str | Path = ".hive/kingdom/runs",
        ledger_path: str | Path = ".hive/kingdom/ledger.jsonl",
    ):
        self.provider = provider
        self.config = config or KingdomConfig()
        self.run_dir = Path(run_dir)
        self.ledger = HashChainLedger(ledger_path)

    @staticmethod
    def _normalize_branch(branch: BranchSpec, *, depth: int, parent_id: str | None) -> BranchSpec:
        branch_id = branch.branch_id.strip() or uuid.uuid4().hex[:12]
        return BranchSpec(
            branch_id=branch_id,
            lens=branch.lens.strip() or "general",
            question=branch.question.strip(),
            assumption_shift=branch.assumption_shift.strip(),
            parent_id=parent_id if parent_id is not None else branch.parent_id,
            depth=depth,
        )

    def _accept_branches(
        self,
        candidates: Sequence[BranchSpec],
        accepted: list[BranchSpec],
        seen: set[str],
        *,
        depth: int,
        parent_id: str | None,
    ) -> list[BranchSpec]:
        wave: list[BranchSpec] = []
        ids = {item.branch_id for item in accepted}
        for raw in candidates:
            if len(accepted) >= self.config.max_branches:
                break
            branch = self._normalize_branch(raw, depth=depth, parent_id=parent_id)
            if not branch.question:
                continue
            fingerprint = branch.fingerprint()
            if fingerprint in seen:
                continue
            if branch.branch_id in ids:
                branch = BranchSpec(
                    branch_id=f"{branch.branch_id}-{uuid.uuid4().hex[:6]}",
                    lens=branch.lens,
                    question=branch.question,
                    assumption_shift=branch.assumption_shift,
                    parent_id=branch.parent_id,
                    depth=branch.depth,
                )
            seen.add(fingerprint)
            ids.add(branch.branch_id)
            accepted.append(branch)
            wave.append(branch)
        return wave

    def _explore_wave(self, seed: Seed, wave: Sequence[BranchSpec]) -> list[BranchResult]:
        if not wave:
            return []
        results: list[BranchResult] = []
        with ThreadPoolExecutor(max_workers=min(self.config.workers, len(wave))) as pool:
            future_map = {pool.submit(self.provider.explore, seed, branch): branch for branch in wave}
            for future in as_completed(future_map):
                branch = future_map[future]
                result = future.result()
                if result.branch_id != branch.branch_id:
                    result = BranchResult(
                        branch_id=branch.branch_id,
                        findings=result.findings,
                        evidence=result.evidence,
                        assumptions=result.assumptions,
                        uncertainties=result.uncertainties,
                        next_branches=result.next_branches,
                    )
                results.append(result)
        return sorted(results, key=lambda item: item.branch_id)

    def run(self, seed: Seed) -> KingdomRun:
        if not seed.text.strip():
            raise ValueError("seed text cannot be empty")

        started_at = time.time()
        run_id = f"kingdom-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        accepted: list[BranchSpec] = []
        seen: set[str] = set()
        all_results: list[BranchResult] = []

        initial = self.provider.decompose(seed, self.config)
        wave = self._accept_branches(initial, accepted, seen, depth=0, parent_id=None)

        depth = 0
        while wave and depth <= self.config.max_depth:
            wave_results = self._explore_wave(seed, wave)
            all_results.extend(wave_results)
            if depth >= self.config.max_depth:
                break

            next_wave: list[BranchSpec] = []
            for result in wave_results:
                children = self._accept_branches(
                    result.next_branches,
                    accepted,
                    seen,
                    depth=depth + 1,
                    parent_id=result.branch_id,
                )
                next_wave.extend(children)
            wave = next_wave
            depth += 1

        ordered_branches = tuple(sorted(accepted, key=lambda item: (item.depth, item.branch_id)))
        ordered_results = tuple(sorted(all_results, key=lambda item: item.branch_id))
        structure = self.provider.integrate(seed, ordered_branches, ordered_results)
        packet = self.provider.encode(seed, structure, self.config)
        probes = tuple(self.provider.make_probes(seed, structure, packet))
        finished_at = time.time()
        run = KingdomRun(
            run_id=run_id,
            seed=seed,
            branches=ordered_branches,
            results=ordered_results,
            structure=structure,
            packet=packet,
            probes=probes,
            started_at=started_at,
            finished_at=finished_at,
        )
        self._persist(run)
        return run

    def assess(self, run: KingdomRun, answers: Mapping[str, str]) -> ComprehensionAssessment:
        assessment = self.provider.assess(
            run.seed,
            run.structure,
            run.probes,
            answers,
        )
        self.ledger.append(
            "comprehension_assessment",
            {
                "run_id": run.run_id,
                "score": assessment.score,
                "missed": list(assessment.missed),
                "reexpand": list(assessment.reexpand),
            },
        )
        return assessment

    def _persist(self, run: KingdomRun) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / f"{run.run_id}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        self.ledger.append(
            "kingdom_run",
            {
                "run_id": run.run_id,
                "seed": run.seed.text,
                "branch_count": len(run.branches),
                "result_count": len(run.results),
                "run_file": str(path),
            },
        )
