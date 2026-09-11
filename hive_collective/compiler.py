from __future__ import annotations

from collections import defaultdict

from .artifact import CognitiveArtifact
from .state import CollectiveState


class CollectiveCompiler:
    """Compile artifacts into state while preserving disagreement and provenance."""

    def compile(
        self,
        task: str,
        artifacts: list[CognitiveArtifact],
        prior: CollectiveState | None = None,
    ) -> CollectiveState:
        state = CollectiveState(task=task, cycle=(prior.cycle + 1 if prior else 0))
        if prior:
            state.claims = list(prior.claims)
            state.evidence = list(prior.evidence)
            state.hypotheses = list(prior.hypotheses)
            state.uncertainties = list(prior.uncertainties)
            state.conflicts = list(prior.conflicts)
            state.proposed_actions = list(prior.proposed_actions)
            state.artifact_ids = list(prior.artifact_ids)
            state.provenance = {k: list(v) for k, v in prior.provenance.items()}
            state.metadata = dict(prior.metadata)

        for artifact in artifacts:
            state.ingest(artifact)

        state.claims = self._dedupe(state.claims)
        state.evidence = self._dedupe(state.evidence)
        state.hypotheses = self._dedupe(state.hypotheses)
        state.uncertainties = self._dedupe(state.uncertainties)
        state.conflicts = self._dedupe(state.conflicts)
        state.proposed_actions = self._dedupe(state.proposed_actions)
        state.metadata["artifact_count"] = len(state.artifact_ids)
        state.metadata["node_count"] = len({a.node_id for a in artifacts})
        return state

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            key = " ".join(item.split()).casefold()
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
