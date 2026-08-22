from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from .core import (
    BranchResult,
    BranchSpec,
    CognitivePacket,
    ComprehensionAssessment,
    ComprehensionProbe,
    KingdomConfig,
    KingdomProvider,
    Seed,
    StructureMap,
)


@dataclass(frozen=True)
class WorldSpec:
    """A deliberately incompatible reasoning world.

    Worlds are interventions on assumptions/objectives, not role labels. Two
    workers can have different roles and still reason inside the same world;
    this type exists to force genuinely different trajectories.
    """

    name: str
    premise_shift: str
    objective: str
    falsifier: str

    @property
    def world_id(self) -> str:
        body = f"{self.name}|{self.premise_shift}|{self.objective}|{self.falsifier}".lower()
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]

    def to_branch(self, seed: Seed, index: int) -> BranchSpec:
        return BranchSpec(
            branch_id=f"world-{index:02d}-{self.world_id[:6]}",
            lens=f"world:{self.name}",
            question=(
                f"Inside the '{self.name}' world, investigate the seed as if the world premise "
                f"were binding. Determine what this world uniquely reveals, what would make it fail, "
                f"and what executable evidence would distinguish it from competing worlds. Seed: {seed.text}"
            ),
            assumption_shift=(
                f"Premise: {self.premise_shift} Objective: {self.objective} "
                f"Falsifier: {self.falsifier}"
            ),
        )


def default_worlds(seed: Seed) -> tuple[WorldSpec, ...]:
    """Return a fixed minimum-diversity basis for arbitrary seeds."""

    return (
        WorldSpec(
            name="premise_true",
            premise_shift=f"The central intuition in '{seed.text}' is substantially correct.",
            objective="Find the strongest realizable form of the idea.",
            falsifier="Identify an observation that would force abandonment of the central intuition.",
        ),
        WorldSpec(
            name="premise_false",
            premise_shift=f"The central intuition in '{seed.text}' is wrong or misleading.",
            objective="Explain the apparent usefulness without relying on the central intuition.",
            falsifier="Find evidence that cannot be explained without restoring the original intuition.",
        ),
        WorldSpec(
            name="minimum_viable",
            premise_shift="Only capabilities available with current tools and modest resources may be used.",
            objective="Reach the nearest executable experiment or prototype.",
            falsifier="Show that a required dependency cannot be reduced to an available operation.",
        ),
        WorldSpec(
            name="capability_max",
            premise_shift="Cost and elegance are secondary; maximize demonstrated capability using available tools.",
            objective="Discover the upper reachable bound before optimizing it.",
            falsifier="Show that added complexity produces no measurable capability gain.",
        ),
        WorldSpec(
            name="adversarial",
            premise_shift="Assume the proposed system will be attacked by correlated errors, bad evidence, and seductive explanations.",
            objective="Construct the strongest failure case and the gate required to catch it.",
            falsifier="Demonstrate a gate that reliably detects the constructed failure mode.",
        ),
        WorldSpec(
            name="outside_frame",
            premise_shift="Assume the problem has been framed at the wrong level of abstraction.",
            objective="Find a reformulation that changes what must be built or measured.",
            falsifier="Show that the reframing is behaviorally equivalent to the original framing.",
        ),
    )


class WorldBranchingProvider:
    """Provider wrapper that guarantees incompatible world branches exist.

    The wrapped provider still contributes its own model-generated branches.
    Required worlds are inserted first so a branch budget cannot silently erase
    premise-level diversity.
    """

    def __init__(self, provider: KingdomProvider, *, world_count: int = 6):
        if world_count < 0:
            raise ValueError("world_count must be >= 0")
        self.provider = provider
        self.world_count = world_count

    def decompose(self, seed: Seed, config: KingdomConfig) -> Sequence[BranchSpec]:
        worlds = default_worlds(seed)[: min(self.world_count, config.max_branches)]
        required = [world.to_branch(seed, index + 1) for index, world in enumerate(worlds)]
        remaining = max(0, config.max_branches - len(required))
        generated = list(self.provider.decompose(seed, config))[:remaining] if remaining else []
        return tuple(required + generated)

    def explore(self, seed: Seed, branch: BranchSpec) -> BranchResult:
        return self.provider.explore(seed, branch)

    def integrate(
        self,
        seed: Seed,
        branches: Sequence[BranchSpec],
        results: Sequence[BranchResult],
    ) -> StructureMap:
        return self.provider.integrate(seed, branches, results)

    def encode(
        self,
        seed: Seed,
        structure: StructureMap,
        config: KingdomConfig,
    ) -> CognitivePacket:
        return self.provider.encode(seed, structure, config)

    def make_probes(
        self,
        seed: Seed,
        structure: StructureMap,
        packet: CognitivePacket,
    ) -> Sequence[ComprehensionProbe]:
        return self.provider.make_probes(seed, structure, packet)

    def assess(
        self,
        seed: Seed,
        structure: StructureMap,
        probes: Sequence[ComprehensionProbe],
        answers: dict[str, str],
    ) -> ComprehensionAssessment:
        return self.provider.assess(seed, structure, probes, answers)
