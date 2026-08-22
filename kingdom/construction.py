from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

from .arena import ArenaExecution, ArenaPlanner, ArenaRegistry, ToolRequest
from .core import (
    BranchResult,
    CognitivePacket,
    ComprehensionProbe,
    KingdomEngine,
    KingdomRun,
    Seed,
    StructureMap,
)


@dataclass(frozen=True)
class BuildTarget:
    target_id: str
    statement: str
    kind: str
    status: str = "open"
    parent_id: str | None = None
    depth: int = 0
    capability: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"goal", "branch", "capability", "experiment", "tool"}:
            raise ValueError(f"unsupported target kind: {self.kind}")
        if self.status not in {"open", "blocked", "executable", "verified", "rejected"}:
            raise ValueError(f"unsupported target status: {self.status}")


@dataclass
class ConstructionGraph:
    """Dependency graph that turns blockers into new decomposable targets."""

    targets: dict[str, BuildTarget] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)

    @staticmethod
    def _stable_id(kind: str, statement: str, parent_id: str | None) -> str:
        body = f"{kind}|{parent_id or ''}|{statement.strip().lower()}"
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]

    def add(
        self,
        statement: str,
        *,
        kind: str,
        parent_id: str | None = None,
        status: str = "open",
        capability: str = "",
        reason: str = "",
    ) -> BuildTarget:
        statement = statement.strip()
        if not statement:
            raise ValueError("target statement cannot be empty")
        if parent_id is not None and parent_id not in self.targets:
            raise KeyError(f"unknown parent target {parent_id}")
        target_id = self._stable_id(kind, statement, parent_id)
        existing = self.targets.get(target_id)
        if existing is not None:
            return existing
        depth = 0 if parent_id is None else self.targets[parent_id].depth + 1
        target = BuildTarget(
            target_id=target_id,
            statement=statement,
            kind=kind,
            status=status,
            parent_id=parent_id,
            depth=depth,
            capability=capability,
            reason=reason,
        )
        self.targets[target_id] = target
        if parent_id is not None:
            self.children.setdefault(parent_id, []).append(target_id)
        return target

    def set_status(self, target_id: str, status: str) -> BuildTarget:
        target = self.targets[target_id]
        updated = replace(target, status=status)
        self.targets[target_id] = updated
        return updated

    def promote_missing(
        self,
        execution: ArenaExecution,
        *,
        parent_id: str,
    ) -> BuildTarget | None:
        missing = execution.missing
        if missing is None:
            return None
        statement = (
            f"Build or acquire capability '{missing.name}' able to perform operation "
            f"'{missing.operation}' for: {missing.purpose or 'the blocked branch'}"
        )
        return self.add(
            statement,
            kind="capability",
            parent_id=parent_id,
            status="blocked",
            capability=missing.name,
            reason=missing.purpose,
        )

    def frontier(self) -> tuple[BuildTarget, ...]:
        """Return unresolved leaf targets: the next things that must become executable."""
        values = []
        for target in self.targets.values():
            if target.status in {"verified", "rejected"}:
                continue
            if any(
                self.targets[child].status not in {"verified", "rejected"}
                for child in self.children.get(target.target_id, ())
            ):
                continue
            values.append(target)
        return tuple(sorted(values, key=lambda item: (item.depth, item.target_id)))

    def path_to(self, target_id: str) -> tuple[BuildTarget, ...]:
        path: list[BuildTarget] = []
        current = self.targets[target_id]
        while True:
            path.append(current)
            if current.parent_id is None:
                break
            current = self.targets[current.parent_id]
        return tuple(reversed(path))


@dataclass(frozen=True)
class ConstructionRun:
    base_run: KingdomRun
    verified_results: tuple[BranchResult, ...]
    arena_executions: tuple[ArenaExecution, ...]
    graph: ConstructionGraph
    structure: StructureMap
    packet: CognitivePacket
    probes: tuple[ComprehensionProbe, ...]

    @property
    def missing_capabilities(self) -> tuple[BuildTarget, ...]:
        return tuple(
            target
            for target in self.graph.targets.values()
            if target.kind == "capability" and target.status == "blocked"
        )


class MindConstructor:
    """Kingdom + Arena + recursive blocker promotion.

    This is intentionally one loop above KingdomEngine. Kingdom explores the
    conceptual territory. Arena asks reality. Missing Arena capabilities are
    promoted into new construction targets instead of being terminal errors.
    """

    def __init__(
        self,
        engine: KingdomEngine,
        arena: ArenaRegistry,
        planner: ArenaPlanner,
    ):
        self.engine = engine
        self.arena = arena
        self.planner = planner

    def run(self, seed: Seed) -> ConstructionRun:
        base_run = self.engine.run(seed)
        branches = {branch.branch_id: branch for branch in base_run.branches}
        graph = ConstructionGraph()
        root = graph.add(seed.text, kind="goal", status="open")
        branch_targets: dict[str, BuildTarget] = {}

        requests: list[ToolRequest] = []
        for result in base_run.results:
            branch = branches[result.branch_id]
            branch_target = graph.add(
                branch.question,
                kind="branch",
                parent_id=root.target_id,
                status="open",
                reason=branch.assumption_shift,
            )
            branch_targets[result.branch_id] = branch_target
            requests.extend(
                self.planner.plan(
                    seed,
                    branch,
                    result,
                    self.arena.tool_names,
                )
            )

        executions = self.arena.execute_many(tuple(requests))
        by_branch: dict[str, list[ArenaExecution]] = {}
        for execution in executions:
            branch_id = execution.observation.branch_id
            by_branch.setdefault(branch_id, []).append(execution)
            parent = branch_targets.get(branch_id, root)
            if execution.missing is not None:
                graph.promote_missing(execution, parent_id=parent.target_id)
            elif execution.observation.status == "verified":
                graph.add(
                    execution.observation.claim,
                    kind="experiment",
                    parent_id=parent.target_id,
                    status="verified",
                    reason=execution.observation.source,
                )

        verified_results: list[BranchResult] = []
        for result in base_run.results:
            extra = tuple(
                execution.observation.as_evidence()
                for execution in by_branch.get(result.branch_id, ())
            )
            verified_results.append(
                BranchResult(
                    branch_id=result.branch_id,
                    findings=result.findings,
                    evidence=result.evidence + extra,
                    assumptions=result.assumptions,
                    uncertainties=result.uncertainties,
                    next_branches=result.next_branches,
                )
            )

        verified_tuple = tuple(sorted(verified_results, key=lambda item: item.branch_id))
        structure = self.engine.provider.integrate(seed, base_run.branches, verified_tuple)
        packet = self.engine.provider.encode(seed, structure, self.engine.config)
        probes = tuple(self.engine.provider.make_probes(seed, structure, packet))
        return ConstructionRun(
            base_run=base_run,
            verified_results=verified_tuple,
            arena_executions=executions,
            graph=graph,
            structure=structure,
            packet=packet,
            probes=probes,
        )
