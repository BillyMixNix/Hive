from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .artifact import CognitiveArtifact


class CognitiveNode(ABC):
    """Bounded cognitive operation. Nodes produce artifacts, never collective truth."""

    node_id: str
    operation: str

    def __init__(self, node_id: str, operation: str) -> None:
        self.node_id = node_id
        self.operation = operation

    @abstractmethod
    def run(self, task: str, state: dict[str, Any] | None = None) -> CognitiveArtifact:
        raise NotImplementedError


class FunctionNode(CognitiveNode):
    """Adapter for deterministic functions, useful for controlled experiments."""

    def __init__(self, node_id: str, operation: str, function) -> None:
        super().__init__(node_id, operation)
        self.function = function

    def run(self, task: str, state: dict[str, Any] | None = None) -> CognitiveArtifact:
        result = self.function(task, state or {})
        if isinstance(result, CognitiveArtifact):
            return result
        if not isinstance(result, dict):
            raise TypeError("node function must return CognitiveArtifact or dict")
        return CognitiveArtifact(node_id=self.node_id, operation=self.operation, **result)
