from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean
from typing import Mapping, Sequence

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

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall((text or "").lower()))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


@dataclass(frozen=True)
class BranchSimilarity:
    left_id: str
    right_id: str
    question_similarity: float
    assumption_similarity: float
    combined_similarity: float


@dataclass(frozen=True)
class DiversityReport:
    branch_count: int
    unique_lenses: int
    unique_assumption_shifts: int
    mean_pairwise_similarity: float
    effective_branch_count: int
    efficiency: float
    correlated_pairs: tuple[BranchSimilarity, ...]


def branch_similarity(left: BranchSpec, right: BranchSpec) -> BranchSimilarity:
    question = _jaccard(_tokens(left.question), _tokens(right.question))
    assumptions = _jaccard(_tokens(left.assumption_shift), _tokens(right.assumption_shift))
    combined = 0.55 * question + 0.45 * assumptions
    return BranchSimilarity(
        left.branch_id,
        right.branch_id,
        question,
        assumptions,
        combined,
    )


def _forced_world(branch: BranchSpec) -> bool:
    return branch.lens.lower().startswith("world:")


def branches_are_correlated(
    left: BranchSpec,
    right: BranchSpec,
    *,
    question_threshold: float = 0.78,
    assumption_threshold: float = 0.78,
) -> bool:
    # Forced worlds are deliberate interventions and remain distinct even when
    # their wording shares a template.
    if _forced_world(left) or _forced_world(right):
        return False
    similarity = branch_similarity(left, right)
    return (
        similarity.question_similarity >= question_threshold
        and similarity.assumption_similarity >= assumption_threshold
    )


def filter_novel_branches(
    branches: Sequence[BranchSpec],
    *,
    question_threshold: float = 0.78,
    assumption_threshold: float = 0.78,
) -> tuple[BranchSpec, ...]:
    accepted: list[BranchSpec] = []
    for branch in branches:
        if _forced_world(branch):
            accepted.append(branch)
            continue
        if any(
            branches_are_correlated(
                branch,
                previous,
                question_threshold=question_threshold,
                assumption_threshold=assumption_threshold,
            )
            for previous in accepted
        ):
            continue
        accepted.append(branch)
    return tuple(accepted)


def diversity_report(branches: Sequence[BranchSpec]) -> DiversityReport:
    values = tuple(branches)
    if not values:
        return DiversityReport(0, 0, 0, 0.0, 0, 0.0, ())

    similarities: list[BranchSimilarity] = []
    correlated: list[BranchSimilarity] = []
    representatives: list[BranchSpec] = []
    for index, branch in enumerate(values):
        for other in values[index + 1 :]:
            similarity = branch_similarity(branch, other)
            similarities.append(similarity)
            if branches_are_correlated(branch, other):
                correlated.append(similarity)
        if _forced_world(branch) or not any(branches_are_correlated(branch, rep) for rep in representatives):
            representatives.append(branch)

    effective = len(representatives)
    return DiversityReport(
        branch_count=len(values),
        unique_lenses=len({item.lens.strip().lower() for item in values}),
        unique_assumption_shifts=len(
            {item.assumption_shift.strip().lower() for item in values if item.assumption_shift.strip()}
        ),
        mean_pairwise_similarity=mean(item.combined_similarity for item in similarities) if similarities else 0.0,
        effective_branch_count=effective,
        efficiency=effective / len(values),
        correlated_pairs=tuple(
            sorted(correlated, key=lambda item: item.combined_similarity, reverse=True)
        ),
    )


class NoveltyFilteringProvider:
    """Provider wrapper that removes near-duplicate generated branches.

    This is a lexical proxy, not a semantic-diversity oracle. Explicit forced
    world branches are never removed by this layer.
    """

    def __init__(
        self,
        inner: KingdomProvider,
        *,
        question_threshold: float = 0.78,
        assumption_threshold: float = 0.78,
    ):
        self.inner = inner
        self.question_threshold = question_threshold
        self.assumption_threshold = assumption_threshold

    def _filter(self, branches: Sequence[BranchSpec]) -> tuple[BranchSpec, ...]:
        return filter_novel_branches(
            branches,
            question_threshold=self.question_threshold,
            assumption_threshold=self.assumption_threshold,
        )

    def decompose(self, seed: Seed, config: KingdomConfig) -> Sequence[BranchSpec]:
        return self._filter(self.inner.decompose(seed, config))

    def explore(self, seed: Seed, branch: BranchSpec) -> BranchResult:
        result = self.inner.explore(seed, branch)
        return BranchResult(
            branch_id=result.branch_id,
            findings=result.findings,
            evidence=result.evidence,
            assumptions=result.assumptions,
            uncertainties=result.uncertainties,
            next_branches=self._filter(result.next_branches),
        )

    def integrate(
        self,
        seed: Seed,
        branches: Sequence[BranchSpec],
        results: Sequence[BranchResult],
    ) -> StructureMap:
        return self.inner.integrate(seed, branches, results)

    def encode(
        self,
        seed: Seed,
        structure: StructureMap,
        config: KingdomConfig,
    ) -> CognitivePacket:
        return self.inner.encode(seed, structure, config)

    def make_probes(
        self,
        seed: Seed,
        structure: StructureMap,
        packet: CognitivePacket,
    ) -> Sequence[ComprehensionProbe]:
        return self.inner.make_probes(seed, structure, packet)

    def assess(
        self,
        seed: Seed,
        structure: StructureMap,
        probes: Sequence[ComprehensionProbe],
        answers: Mapping[str, str],
    ) -> ComprehensionAssessment:
        return self.inner.assess(seed, structure, probes, answers)
