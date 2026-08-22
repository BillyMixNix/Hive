from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol, Sequence

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
from .forge import CapabilityForge, ForgeAttempt


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


@dataclass(frozen=True)
class TargetDraft:
    statement: str
    kind: str = "tool"
    status: str = "open"
    capability: str = ""
    reason: str = ""


class TargetDecomposer(Protocol):
    def decompose(
        self,
        target: BuildTarget,
        available_capabilities: Sequence[str],
    ) -> Sequence[TargetDraft]: ...


class HiveTargetDecomposer:
    """Recursively reduce a blocked target toward executable predecessors."""

    def __init__(self, ask: Callable[..., str] | None = None, *, max_children: int = 5):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask
        self.max_children = max_children

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)

    def decompose(
        self,
        target: BuildTarget,
        available_capabilities: Sequence[str],
    ) -> Sequence[TargetDraft]:
        prompt = (
            "KINGDOM / RECURSIVE CONSTRUCTION\n\n"
            f"Blocked target: {target.statement}\nReason: {target.reason}\n"
            f"Currently available capabilities: {list(available_capabilities)}\n\n"
            "Decompose this blocker into the smallest useful predecessor targets. Prefer targets that can be "
            "executed with available capabilities. If a required predecessor capability is itself missing, make it "
            "a capability target so it can be decomposed again. Do not merely restate the parent. "
            f"Return at most {self.max_children} children as JSON {{'targets': [...]}}. "
            "Each target has statement, kind (tool|capability|experiment), status "
            "(open|blocked|executable), capability, reason. JSON only."
        )
        payload = self._parse(self.ask(prompt, role="planner"))
        drafts: list[TargetDraft] = []
        for item in payload.get("targets", [])[: self.max_children]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "tool")
            if kind not in {"tool", "capability", "experiment"}:
                kind = "tool"
            status = str(item.get("status") or "open")
            if status not in {"open", "blocked", "executable"}:
                status = "open"
            statement = str(item.get("statement") or "").strip()
            if not statement:
                continue
            drafts.append(
                TargetDraft(
                    statement=statement,
                    kind=kind,
                    status=status,
                    capability=str(item.get("capability") or ""),
                    reason=str(item.get("reason") or ""),
                )
            )
        return tuple(drafts)


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

    def expand(
        self,
        target: BuildTarget,
        drafts: Sequence[TargetDraft],
    ) -> tuple[BuildTarget, ...]:
        children: list[BuildTarget] = []
        normalized_parent = target.statement.strip().lower()
        for draft in drafts:
            if draft.statement.strip().lower() == normalized_parent:
                continue
            children.append(
                self.add(
                    draft.statement,
                    kind=draft.kind,
                    parent_id=target.target_id,
                    status=draft.status,
                    capability=draft.capability,
                    reason=draft.reason,
                )
            )
        return tuple(children)

    def recursively_expand(
        self,
        roots: Sequence[BuildTarget],
        decomposer: TargetDecomposer,
        *,
        available_capabilities: Sequence[str],
        max_depth: int = 3,
        max_targets: int = 40,
    ) -> tuple[BuildTarget, ...]:
        # max_depth is relative to each promoted blocker, not absolute graph depth.
        queue: list[tuple[BuildTarget, int]] = [(target, 0) for target in roots]
        created: list[BuildTarget] = []
        while queue and len(self.targets) < max_targets:
            target, relative_depth = queue.pop(0)
            if relative_depth >= max_depth or target.status in {"verified", "rejected", "executable"}:
                continue
            drafts = decomposer.decompose(target, available_capabilities)
            children = self.expand(target, drafts)
            created.extend(children)
            for child in children:
                if child.status in {"open", "blocked"} and len(self.targets) < max_targets:
                    queue.append((child, relative_depth + 1))
        return tuple(created)

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
    forge_attempts: tuple[ForgeAttempt, ...] = ()

    @property
    def missing_capabilities(self) -> tuple[BuildTarget, ...]:
        return tuple(
            target
            for target in self.graph.targets.values()
            if target.kind == "capability" and target.status == "blocked"
        )


class MindConstructor:
    """Kingdom + Arena + recursive blocker promotion and safe capability acquisition."""

    def __init__(
        self,
        engine: KingdomEngine,
        arena: ArenaRegistry,
        planner: ArenaPlanner,
        *,
        target_decomposer: TargetDecomposer | None = None,
        capability_forge: CapabilityForge | None = None,
        construction_depth: int = 3,
        target_budget: int = 40,
    ):
        self.engine = engine
        self.arena = arena
        self.planner = planner
        self.target_decomposer = target_decomposer
        self.capability_forge = capability_forge
        self.construction_depth = construction_depth
        self.target_budget = target_budget

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

        normalized_requests = tuple(request.normalized() for request in requests)
        request_by_id = {request.request_id: request for request in normalized_requests}
        initial_executions = self.arena.execute_many(normalized_requests)
        by_branch: dict[str, list[ArenaExecution]] = {}
        promoted: list[BuildTarget] = []
        promoted_by_request: dict[str, BuildTarget] = {}

        for execution in initial_executions:
            branch_id = execution.observation.branch_id
            by_branch.setdefault(branch_id, []).append(execution)
            parent = branch_targets.get(branch_id, root)
            if execution.missing is not None:
                target = graph.promote_missing(execution, parent_id=parent.target_id)
                if target is not None:
                    promoted.append(target)
                    promoted_by_request[execution.observation.request_id] = target
            elif execution.observation.status == "verified":
                graph.add(
                    execution.observation.claim,
                    kind="experiment",
                    parent_id=parent.target_id,
                    status="verified",
                    reason=execution.observation.source,
                )

        forge_attempts: list[ForgeAttempt] = []
        retry_executions: list[ArenaExecution] = []
        if self.capability_forge is not None:
            for execution in initial_executions:
                if execution.missing is None:
                    continue
                request_id = execution.observation.request_id
                target = promoted_by_request.get(request_id)
                request = request_by_id.get(request_id)
                if target is None or request is None:
                    continue
                attempt = self.capability_forge.attempt(target, request)
                forge_attempts.append(attempt)
                if attempt.status != "accepted" or not attempt.registered:
                    continue

                retry = self.arena.execute(request)
                retry_executions.append(retry)
                by_branch.setdefault(retry.observation.branch_id, []).append(retry)
                if retry.observation.status == "verified":
                    graph.set_status(target.target_id, "verified")
                    parent = branch_targets.get(retry.observation.branch_id, root)
                    graph.add(
                        retry.observation.claim,
                        kind="experiment",
                        parent_id=parent.target_id,
                        status="verified",
                        reason=retry.observation.source,
                    )

        unresolved = [
            graph.targets[target.target_id]
            for target in promoted
            if graph.targets[target.target_id].status == "blocked"
        ]
        if unresolved and self.target_decomposer is not None:
            graph.recursively_expand(
                unresolved,
                self.target_decomposer,
                available_capabilities=self.arena.tool_names,
                max_depth=self.construction_depth,
                max_targets=self.target_budget,
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
        all_executions = tuple(initial_executions) + tuple(retry_executions)
        return ConstructionRun(
            base_run=base_run,
            verified_results=verified_tuple,
            arena_executions=all_executions,
            graph=graph,
            structure=structure,
            packet=packet,
            probes=probes,
            forge_attempts=tuple(forge_attempts),
        )
