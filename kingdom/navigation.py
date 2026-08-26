from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .core import BranchResult, KingdomRun, StructureMap


@dataclass(frozen=True)
class NavNode:
    ref: str
    kind: str
    label: str
    detail: str
    branch_refs: tuple[str, ...] = ()
    child_refs: tuple[str, ...] = ()


@dataclass
class CognitiveNavigator:
    """Inspectable view over a compressed Kingdom result.

    The packet can stay small while every load-bearing structural claim retains
    a stable ref that can be expanded back into branch-level provenance.
    """

    nodes: dict[str, NavNode] = field(default_factory=dict)

    @staticmethod
    def _ref(kind: str, label: str) -> str:
        digest = hashlib.sha256(f"{kind}|{label}".encode("utf-8")).hexdigest()[:10]
        return f"{kind}:{digest}"

    @classmethod
    def from_parts(
        cls,
        structure: StructureMap,
        results: Sequence[BranchResult],
    ) -> "CognitiveNavigator":
        navigator = cls()
        result_map = {result.branch_id: result for result in results}

        for result in results:
            details: list[str] = []
            if result.findings:
                details.append("Findings:\n" + "\n".join(f"- {item}" for item in result.findings))
            if result.evidence:
                details.append(
                    "Evidence:\n"
                    + "\n".join(
                        f"- [{item.stance} {item.confidence:.2f}] {item.claim} ({item.source or 'no source'})"
                        for item in result.evidence
                    )
                )
            if result.uncertainties:
                details.append("Uncertainties:\n" + "\n".join(f"- {item}" for item in result.uncertainties))
            navigator.nodes[result.branch_id] = NavNode(
                ref=result.branch_id,
                kind="branch",
                label=result.branch_id,
                detail="\n\n".join(details),
            )

        categories: tuple[tuple[str, Sequence[str]], ...] = (
            ("invariant", structure.invariants),
            ("disagreement", structure.disagreements),
            ("hinge", structure.hinge_assumptions),
            ("causal", structure.causal_links),
            ("anomaly", structure.anomalies),
            ("unknown", structure.unknowns),
        )
        for kind, statements in categories:
            for statement in statements:
                refs = tuple(
                    ref for ref in structure.provenance.get(statement, ()) if ref in result_map
                )
                ref = cls._ref(kind, statement)
                navigator.nodes[ref] = NavNode(
                    ref=ref,
                    kind=kind,
                    label=statement,
                    detail=statement,
                    branch_refs=refs,
                    child_refs=refs,
                )
        return navigator

    @classmethod
    def from_run(cls, run: KingdomRun) -> "CognitiveNavigator":
        return cls.from_parts(run.structure, run.results)

    def inspect(self, ref: str) -> NavNode:
        if ref not in self.nodes:
            raise KeyError(f"unknown cognitive ref {ref!r}")
        return self.nodes[ref]

    def expand(self, ref: str) -> tuple[NavNode, ...]:
        node = self.inspect(ref)
        return tuple(self.nodes[child] for child in node.child_refs if child in self.nodes)

    def search(self, text: str) -> tuple[NavNode, ...]:
        needle = text.strip().lower()
        if not needle:
            return ()
        return tuple(
            node
            for node in self.nodes.values()
            if needle in node.label.lower() or needle in node.detail.lower()
        )
