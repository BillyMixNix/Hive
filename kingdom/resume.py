from __future__ import annotations

import copy
from typing import Sequence

from .arena import ArenaExecution, ArenaRegistry
from .construction import BuildTarget, ConstructionRun, TargetDecomposer
from .core import BranchResult, KingdomEngine
from .forge import CapabilityForge, ForgeAttempt
from .target_execution import TargetExecutionPlanner


class ConstructionResumer:
    """Continue a persisted ConstructionRun without replaying the base search."""

    def __init__(
        self,
        engine: KingdomEngine,
        arena: ArenaRegistry,
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
        self.target_decomposer = target_decomposer
        self.target_planner = target_planner
        self.capability_forge = capability_forge
        self.construction_depth = construction_depth
        self.target_budget = target_budget
        self.construction_rounds = max(0, construction_rounds)

    def _invalidate_absent_capabilities(self, graph) -> tuple[BuildTarget, ...]:
        invalidated: list[BuildTarget] = []
        available = set(self.arena.tool_names)
        for target in list(graph.targets.values()):
            if (
                target.kind == "capability"
                and target.status == "verified"
                and target.capability
                and target.capability not in available
            ):
                invalidated.append(graph.set_status(target.target_id, "blocked"))
                parent_id = target.parent_id
                while parent_id is not None:
                    parent = graph.targets[parent_id]
                    if parent_id in graph.resolution_modes and parent.status == "verified":
                        graph.set_status(parent_id, "blocked")
                    parent_id = parent.parent_id
        return tuple(invalidated)

    def advance(self, prior: ConstructionRun) -> ConstructionRun:
        seed = prior.base_run.seed
        graph = copy.deepcopy(prior.graph)
        self._invalidate_absent_capabilities(graph)
        graph.resolve_dependencies()

        unresolved = [
            target
            for target in graph.targets.values()
            if target.kind == "capability" and target.status == "blocked"
        ]
        if unresolved and self.target_decomposer is not None:
            graph.recursively_expand(
                unresolved,
                self.target_decomposer,
                available_capabilities=self.arena.tool_names,
                max_depth=self.construction_depth,
                max_targets=self.target_budget,
            )

        new_executions: list[ArenaExecution] = []
        new_forge_attempts: list[ForgeAttempt] = []
        by_branch: dict[str, list[ArenaExecution]] = {}
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
                    requests = tuple(
                        request.normalized()
                        for request in self.target_planner.plan(
                            seed,
                            target,
                            self.arena.tool_names,
                        )
                    )
                    if not requests:
                        continue
                    final_statuses: list[str] = []

                    for request in requests:
                        execution = self.arena.execute(request)
                        new_executions.append(execution)
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
                                    new_forge_attempts.append(attempt)
                                    if attempt.status == "accepted" and attempt.registered:
                                        retry = self.arena.execute(request)
                                        new_executions.append(retry)
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
        verified_results = _append_evidence(prior.verified_results, by_branch)
        structure = self.engine.provider.integrate(
            seed,
            prior.base_run.branches,
            verified_results,
        )
        packet = self.engine.provider.encode(seed, structure, self.engine.config)
        probes = tuple(self.engine.provider.make_probes(seed, structure, packet))
        return ConstructionRun(
            base_run=prior.base_run,
            verified_results=verified_results,
            arena_executions=prior.arena_executions + tuple(new_executions),
            graph=graph,
            structure=structure,
            packet=packet,
            probes=probes,
            forge_attempts=prior.forge_attempts + tuple(new_forge_attempts),
        )


def _append_evidence(
    results: Sequence[BranchResult],
    by_branch: dict[str, list[ArenaExecution]],
) -> tuple[BranchResult, ...]:
    updated: list[BranchResult] = []
    for result in results:
        extra = tuple(
            execution.observation.as_evidence()
            for execution in by_branch.get(result.branch_id, ())
        )
        updated.append(
            BranchResult(
                branch_id=result.branch_id,
                findings=result.findings,
                evidence=result.evidence + extra,
                assumptions=result.assumptions,
                uncertainties=result.uncertainties,
                next_branches=result.next_branches,
            )
        )
    return tuple(updated)
