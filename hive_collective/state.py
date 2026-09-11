from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .artifact import CognitiveArtifact


@dataclass
class CollectiveState:
    """Explicit state produced by compilation; it is not presented as truth."""

    task: str
    cycle: int = 0
    claims: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    proposed_actions: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    provenance: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def next_cycle(self) -> "CollectiveState":
        return CollectiveState(task=self.task, cycle=self.cycle + 1)

    def ingest(self, artifact: CognitiveArtifact) -> None:
        self.claims.extend(artifact.claims)
        self.evidence.extend(artifact.evidence)
        self.hypotheses.extend(artifact.hypotheses)
        self.uncertainties.extend(artifact.uncertainties)
        self.conflicts.extend(artifact.conflicts)
        self.proposed_actions.extend(artifact.proposed_actions)
        self.artifact_ids.append(artifact.artifact_id)
        for claim in artifact.claims:
            self.provenance.setdefault(claim, []).append(artifact.artifact_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "cycle": self.cycle,
            "claims": list(self.claims),
            "evidence": list(self.evidence),
            "hypotheses": list(self.hypotheses),
            "uncertainties": list(self.uncertainties),
            "conflicts": list(self.conflicts),
            "proposed_actions": list(self.proposed_actions),
            "artifact_ids": list(self.artifact_ids),
            "provenance": {k: list(v) for k, v in self.provenance.items()},
            "metadata": dict(self.metadata),
        }
