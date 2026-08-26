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
from .target_execution import TargetExecutionPlanner


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
    origin_branch_id: str = ""

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


@dataclass(frozen=True)
class TargetDecomposition:
    """A complete child set plus how those children resolve their parent.

    mode='all': every child is required.
    mode='any': any one verified child is sufficient.
    """

    mode: str
    targets: tuple[TargetDraft, ...]

    def __post_init__(self) -> None:
        if self.mode not in {"all", "any"}:
            raise ValueError("decomposition mode must be 'all' or 'any'")


class TargetDecomposer(Protocol):
    def decompose(
        self,
        target: BuildTarget,
        available_capabilities: Sequence[str],
    ) -> TargetDecomposition | Sequence[TargetDraft]: ...


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
    ) -> TargetDecomposition:
        prompt = (
            "KINGDOM / RECURSIVE CONSTRUCTION\n\n"
            f"Blocked target: {target.statement}\nReason: {target.reason}\n"
            f"Currently available capabilities: {list(available_capabilities)}\n\n"
            "Decompose this blocker into the smallest COMPLETE set of useful predecessor targets. Prefer targets "
            "that can be executed with available capabilities. If a required predecessor capability is itself "
            "missing, make it a capability target so it can be decomposed again. Do not merely restate the parent. "
            "State whether ALL returned children are jointly required to resolve the parent, or whether ANY one child "
            "is a sufficient alternative. Only call the decomposition complete if the stated mode and children really "
            "define a resolution condition for the parent. "
            f"Return at most {self.max_children} children as JSON with keys 'resolution_mode' ('all'|'any') and "
            "'targets'. Each target has statement, kind (tool|capability|experiment), status "
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
        mode = str(payload.get("resolution_mode") or "all").lower()
        if mode not in {"all", "any"}:
            mode = "all"
        return TargetDecomposition(mode=mode, targets=tuple(drafts))


@dataclass
class ConstructionGraph:
    """Dependency graph that turns blockers into new decomposable targets."""

    targets: dict[str, BuildTarget] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    resolution_modes: dict[str, str] = field(default_factory=dict)

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
        origin_branch_id: str = "",
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
        if parent_id is not None and not origin_branch_id:
            origin_branch_id = self.targets[parent_id].origin_branch_id
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
            origin_branch_id=origin_branch_id,
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

    def set_resolution_mode(self, target_id: str, mode: str) -> None:
        if target_id not in self.targets:
            raise KeyError(f"unknown target {target_id}")
        if mode not in {"all", "any"}:
            raise ValueError("resolution mode must be 'all' or 'any'")
        self.resolution_modes[target_id] = mode

    def resolve_dependencies(self) -> tuple[BuildTarget, ...]:
        """Propagate verified/rejected status only where a complete rule exists."""

        changed: list[BuildTarget] = []
        progress = True
        while progress:
            progress = False
            ordered = sorted(self.resolution_modes, key=lambda item: self.targets[item].depth, reverse=True)
            for target_id in ordered:
                target = self.targets[target_id]
                if target.status in {"verified", "rejected"}:
                    continue
                child_ids = self.children.get(target_id, ())
                if not child_ids:
                    continue
                statuses = [self.targets[child_id].status for child_id in child_ids]
                mode = self.resolution_modes[target_id]
                next_status: str | None = None
                if mode == "all":
                    if all(status == "verified" for status in statuses):
                        next_status = "verified"
                    elif any(status == "rejected" for status in statuses):
                        next_status = "rejected"
                else:  # any
                    if any(status == "verified" for status in statuses):
                        next_status = "verified"
                    elif all(status == "rejected" for status in statuses):
                        next_status = "rejected"
                if next_status is not None and next_status != target.status:
                    updated = self.set_status(target_id, next_status)
                    changed.append(updated)
                    progress = True
        return tuple(changed)

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
        *,
        resolution_mode: str | None = None,
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
        if children and resolution_mode is not None:
            self.set_resolution_mode(target.target_id, resolution_mode)
        return tuple(children)

    @staticmethod
    def _normalize_decomposition(
        value: TargetDecomposition | Sequence[TargetDraft],
    ) -> tuple[Sequence[TargetDraft], str | None]:
        if isinstance(value, TargetDecomposition):
            return value.targets, value.mode
        return value, None

    def recursively_expand(
        self,
        roots: Sequence[BuildTarget],
        decomposer: TargetDecomposer,
        *,
        available_capabilities: Sequence[str],
        max_depth: int = 3,
        max_targets: int = 40,
    ) -> tuple[BuildTarget, ...]:
        queue: list[tuple[BuildTarget, int]] = [(target, 0) for target in roots]
        created: list[BuildTarget] = []
        while queue and len(self.targets) < max_targets:
            target, relative_depth = queue.pop(0)
            if relative_depth >= max_depth or target.status in {"verified", "rejected", "executable"}:
                continue
            decomposition = decomposer.decompose(target, available_capabilities)
            drafts, mode = self._normalize_decomposition(decomposition)
            children = self.expand(target, drafts, resolution_mode=mode)
            created.extend(children)
            for child in children:
                if child.status in {"open", "blocked"} and len(self.targets) < max_targets:
                    queue.append((child, relative_depth + 1))
        self.resolve_dependencies()
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
    """Kingdom + Arena + recursive construction + gated capability acquisition."""

    def __init__(
        self,
        engine: KingdomEngine,
        arena: ArenaRegistry,
        planner: ArenaPlanner,
        *,
        target_decomposer: TargetDecomposer | None = None,
        target_planner: TargetExecutionPlanner | None = None,
        capability_forge: CapabilityForge | None = None,
        construction_depth: int = 3,
        target_budget: int = 40,
        construction_rounds: int = 3,
    ):
        self.engine = engine
        self.arena = arena
        self.planner = planner
        self.target_decomposer = target_decomposer
        self.target_planner = target_planner
        self.capability_forge = capability_forge
        self.construction_depth = construction_depth
        self.target_budget = target_budget
        self.construction_rounds = max(0, construction_rounds)

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
                origin_branch_id=result.branch_id,
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

        frontier_executions: list[ArenaExecution] = []
        attempted_frontier: set[str] = set()
        if self.target_planner is not None:
            for _ in range(self.construction_rounds):
                executable = [
                    target
                    for target in graph.frontier()
                    if target.status == "executable"
                    and target.kind not in {"goal", "branch"}
                    and target.target_id not in attempted_frontier
                ]
                if not executable:
                    break
                round_progress = False
                new_blockers: list[BuildTarget] = []

                for target in executable:
                    attempted_frontier.add(target.target_id)
                    planned = tuple(
                        request.normalized()
                        for request in self.target_planner.plan(
                            seed,
                            target,
                            self.arena.tool_names,
                        )
                    )
                    if not planned:
                        continue
                    final_statuses: list[str] = []

                    for request in planned:
                        execution = self.arena.execute(request)
                        frontier_executions.append(execution)
                        by_branch.setdefault(execution.observation.branch_id, []).append(execution)
                        final_execution = execution

                        if execution.missing is not None:
                            missing_target = graph.promote_missing(
                                execution,
                                parent_id=target.target_id,
                            )
                            if missing_target is not None:
                                new_blockers.append(missing_target)
                                if self.capability_forge is not None:
                                    attempt = self.capability_forge.attempt(missing_target, request)
                                    forge_attempts.append(attempt)
                                    if attempt.status == "accepted" and attempt.registered:
                                        retry = self.arena.execute(request)
                                        frontier_executions.append(retry)
                                        by_branch.setdefault(
                                            retry.observation.branch_id, []
                                        ).append(retry)
                                        final_execution = retry
                                        if retry.observation.status == "verified":
                                            graph.set_status(missing_target.target_id, "verified")

                        if final_execution.observation.status == "verified":
                            graph.add(
                                final_execution.observation.claim,
                                kind="experiment",
                                parent_id=target.target_id,
                                status="verified",
                                reason=final_execution.observation.source,
                            )
                        final_statuses.append(final_execution.observation.status)

                    if final_statuses and all(status == "verified" for status in final_statuses):
                        graph.set_status(target.target_id, "verified")
                        round_progress = True

                unresolved_new = [
                    graph.targets[target.target_id]
                    for target in new_blockers
                    if graph.targets[target.target_id].status == "blocked"
                ]
                if unresolved_new and self.target_decomposer is not None:
                    created = graph.recursively_expand(
                        unresolved_new,
                        self.target_decomposer,
                        available_capabilities=self.arena.tool_names,
                        max_depth=self.construction_depth,
                        max_targets=self.target_budget,
                    )
                    round_progress = round_progress or bool(created)
                resolved = graph.resolve_dependencies()
                round_progress = round_progress or bool(resolved)
                if not round_progress and not unresolved_new:
                    break

        graph.resolve_dependencies()

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
        all_executions = (
            tuple(initial_executions)
            + tuple(retry_executions)
            + tuple(frontier_executions)
        )
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
