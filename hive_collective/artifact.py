from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid


@dataclass(frozen=True)
class CognitiveArtifact:
    """A bounded, provenance-carrying result of one cognitive operation."""

    node_id: str
    operation: str
    observations: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    proposed_actions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    confidence: float | None = None
    provenance: list[str] = field(default_factory=list)
    artifact_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id must be non-empty")
        if not self.operation.strip():
            raise ValueError("operation must be non-empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
