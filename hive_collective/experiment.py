from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .artifact import CognitiveArtifact
from .compiler import CollectiveCompiler
from .node import CognitiveNode
from .state import CollectiveState


@dataclass
class CollectiveRun:
    task: str
    artifacts: list[CognitiveArtifact]
    state: CollectiveState


class CollectiveRunner:
    """Small harness for comparing bounded-node composition strategies."""

    def __init__(self, compiler: CollectiveCompiler | None = None) -> None:
        self.compiler = compiler or CollectiveCompiler()

    def run_once(self, task: str, nodes: Iterable[CognitiveNode]) -> CollectiveRun:
        node_list = list(nodes)
        artifacts = [node.run(task, {}) for node in node_list]
        state = self.compiler.compile(task, artifacts)
        return CollectiveRun(task=task, artifacts=artifacts, state=state)

    def run_iterative(
        self,
        task: str,
        nodes: Iterable[CognitiveNode],
        cycles: int = 2,
    ) -> list[CollectiveRun]:
        if cycles < 1:
            raise ValueError("cycles must be >= 1")
        node_list = list(nodes)
        prior: CollectiveState | None = None
        runs: list[CollectiveRun] = []
        for _ in range(cycles):
            state_input = prior.as_dict() if prior else {}
            artifacts = [node.run(task, state_input) for node in node_list]
            state = self.compiler.compile(task, artifacts, prior=prior)
            run = CollectiveRun(task=task, artifacts=artifacts, state=state)
            runs.append(run)
            prior = state
        return runs
