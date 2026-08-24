"""Multiobjective evaluation, evidence, repair, versioning, and safety records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from hive_reference.model import canonical_json, sha256_text
from hive_reference.representation import (
    CostBreakdown,
    EvaluationSummary,
    OriginKind,
    OriginManifest,
    RepresentationEvaluator,
    RepresentationVersion,
    TaskExpectation,
    ValidationStatus,
)


class ResearchInvariantError(ValueError):
    """Evidence, fitness, or migration policy was violated."""


class EvidenceLevel(str, Enum):
    PROVEN = "PROVEN"
    SUPPORTED = "SUPPORTED"
    PLAUSIBLE = "PLAUSIBLE"
    SPECULATIVE = "SPECULATIVE"
    FALSIFIED = "FALSIFIED"


@dataclass(frozen=True)
class FitnessVector:
    protocol_id: str
    solver_id: str
    task_set_hash: str
    representation_id: str
    sample_size: int
    hard_gates_passed: bool
    reconstruction_accuracy: float
    task_accuracy: float
    causal_accuracy: float
    temporal_accuracy: float
    authority_accuracy: float
    provenance_retention: float
    transfer_accuracy: float | None
    robustness: float | None
    cost: CostBreakdown
    uncertainty_json: str = "{}"

    def __post_init__(self) -> None:
        if not self.protocol_id or not self.solver_id or not self.task_set_hash:
            raise ResearchInvariantError("fitness vectors require protocol, solver, and task set")
        if self.sample_size <= 0:
            raise ResearchInvariantError("fitness sample size must be positive")
        values = (
            self.reconstruction_accuracy,
            self.task_accuracy,
            self.causal_accuracy,
            self.temporal_accuracy,
            self.authority_accuracy,
            self.provenance_retention,
            self.transfer_accuracy,
            self.robustness,
        )
        if any(value is not None and not 0.0 <= value <= 1.0 for value in values):
            raise ResearchInvariantError("fitness quality values must be in [0, 1]")
        try:
            uncertainty = json.loads(self.uncertainty_json)
        except json.JSONDecodeError as exc:
            raise ResearchInvariantError("uncertainty must be JSON") from exc
        if canonical_json(uncertainty) != self.uncertainty_json:
            raise ResearchInvariantError("uncertainty must use canonical JSON")

    def comparable_to(self, other: "FitnessVector") -> bool:
        return (
            self.protocol_id == other.protocol_id
            and self.solver_id == other.solver_id
            and self.task_set_hash == other.task_set_hash
            and self.transfer_accuracy is not None
            and other.transfer_accuracy is not None
            and self.robustness is not None
            and other.robustness is not None
        )

    def dominates(self, other: "FitnessVector") -> bool:
        """Strict Pareto dominance under identical comparison conditions."""

        if not self.hard_gates_passed or not self.comparable_to(other):
            return False
        maximize_self = (
            self.reconstruction_accuracy,
            self.task_accuracy,
            self.causal_accuracy,
            self.temporal_accuracy,
            self.authority_accuracy,
            self.provenance_retention,
            float(self.transfer_accuracy),
            float(self.robustness),
        )
        maximize_other = (
            other.reconstruction_accuracy,
            other.task_accuracy,
            other.causal_accuracy,
            other.temporal_accuracy,
            other.authority_accuracy,
            other.provenance_retention,
            float(other.transfer_accuracy),
            float(other.robustness),
        )
        minimize_fields = (
            "packet_bytes",
            "schema_bytes",
            "ontology_bytes",
            "code_config_bytes",
            "lookup_bytes",
            "preprocessing_steps",
            "preprocessing_model_calls",
            "solver_model_calls",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "human_authored_domain_bytes",
        )
        minimize_self = tuple(getattr(self.cost, name) for name in minimize_fields)
        minimize_other = tuple(getattr(other.cost, name) for name in minimize_fields)
        no_worse = all(left >= right for left, right in zip(maximize_self, maximize_other)) and all(
            left <= right for left, right in zip(minimize_self, minimize_other)
        )
        strictly_better = any(left > right for left, right in zip(maximize_self, maximize_other)) or any(
            left < right for left, right in zip(minimize_self, minimize_other)
        )
        return no_worse and strictly_better


def pareto_frontier(vectors: Sequence[FitnessVector]) -> tuple[FitnessVector, ...]:
    eligible = tuple(vector for vector in vectors if vector.hard_gates_passed)
    return tuple(
        vector
        for vector in eligible
        if not any(other is not vector and other.dominates(vector) for other in eligible)
    )


@dataclass(frozen=True)
class ExperimentEvidence:
    experiment_id: str
    protocol_hash: str
    validity: str
    result: str
    artifact_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.validity not in {"VALID", "INVALID", "EXPLORATORY"}:
            raise ResearchInvariantError("unknown experiment validity")


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    statement: str
    scope: str
    evidence_level: EvidenceLevel
    supporting_experiments: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    dependencies: tuple[str, ...]
    falsification_condition: str
    current_status: str


class EvidenceRegistry:
    """Validated in-memory view of the tracked claim registry."""

    def __init__(self, claims: Sequence[ClaimRecord]) -> None:
        self._claims = {claim.claim_id: claim for claim in claims}
        if len(self._claims) != len(claims):
            raise ResearchInvariantError("claim IDs must be unique")
        for claim in claims:
            missing = set(claim.dependencies) - set(self._claims)
            if missing:
                raise ResearchInvariantError(f"claim {claim.claim_id} has missing dependencies")

    @classmethod
    def load(cls, path: str | Path) -> "EvidenceRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        claims = []
        for item in payload["claims"]:
            claims.append(
                ClaimRecord(
                    claim_id=str(item["claim_id"]),
                    statement=str(item["statement"]),
                    scope=str(item["scope"]),
                    evidence_level=EvidenceLevel(str(item["evidence_level"])),
                    supporting_experiments=tuple(str(value) for value in item["supporting_experiments"]),
                    contradicting_evidence=tuple(str(value) for value in item["contradicting_evidence"]),
                    dependencies=tuple(str(value) for value in item["dependencies"]),
                    falsification_condition=str(item["falsification_condition"]),
                    current_status=str(item["current_status"]),
                )
            )
        return cls(claims)

    def get(self, claim_id: str) -> ClaimRecord:
        return self._claims[claim_id]

    @property
    def claims(self) -> tuple[ClaimRecord, ...]:
        return tuple(self._claims[key] for key in sorted(self._claims))

    @staticmethod
    def validate_upgrade(evidence: ExperimentEvidence, target_level: EvidenceLevel) -> None:
        if evidence.validity == "INVALID":
            raise ResearchInvariantError("invalid experiments cannot upgrade claims")
        if target_level is EvidenceLevel.PROVEN and evidence.validity != "VALID":
            raise ResearchInvariantError("exploratory evidence cannot establish PROVEN")


@dataclass(frozen=True)
class RepresentationProfile:
    representation_id: str
    solver_id: str
    task_family: str
    source_split: str
    allowed_evidence_manifest_hash: str
    failure_counts: tuple[tuple[str, int], ...]
    implicated_component_ids: tuple[str, ...]
    evidence_run_ids: tuple[str, ...]

    @property
    def profile_hash(self) -> str:
        return sha256_text(canonical_json(asdict(self)))


@dataclass(frozen=True)
class RepairProposal:
    proposal_id: str
    parent_representation_id: str
    candidate_representation_id: str
    implicated_component_ids: tuple[str, ...]
    retrieved_source_event_ids: tuple[str, ...]
    localizer_id: str
    diagnosis_confidence: float
    oracle_assisted: bool


@dataclass(frozen=True)
class MigrationDecision:
    decision_id: str
    parent_representation_id: str
    candidate_representation_id: str
    parent_representation_hash: str
    candidate_representation_hash: str
    protocol_hash: str
    evaluator_hash: str
    parent_outcome_hash: str
    candidate_outcome_hash: str
    status: str
    reason: str
    rollback_verified: bool


@dataclass(frozen=True)
class ActivationEvent:
    activation_id: str
    previous_active_id: str | None
    new_active_id: str
    decision_id: str
    action: str


class RepresentationRegistry:
    """Immutable versions with append-only active-pointer changes."""

    def __init__(self) -> None:
        self._versions: dict[str, RepresentationVersion] = {}
        self._activations: list[ActivationEvent] = []
        self._active_id: str | None = None

    @property
    def active_id(self) -> str | None:
        return self._active_id

    @property
    def active(self) -> RepresentationVersion | None:
        return None if self._active_id is None else self._versions[self._active_id]

    @property
    def activations(self) -> tuple[ActivationEvent, ...]:
        return tuple(self._activations)

    def register(self, representation: RepresentationVersion) -> None:
        if representation.representation_id in self._versions:
            raise ResearchInvariantError("representation versions are immutable and IDs cannot be reused")
        if representation.parent_id is not None and representation.parent_id not in self._versions:
            raise ResearchInvariantError("representation parent must be registered")
        self._versions[representation.representation_id] = representation

    def activate(self, representation_id: str, decision: MigrationDecision) -> ActivationEvent:
        if representation_id not in self._versions:
            raise ResearchInvariantError("cannot activate an unregistered representation")
        if self._active_id is None:
            raise ResearchInvariantError("activation requires a bootstrapped active representation")
        if decision.status != "promote" or decision.candidate_representation_id != representation_id:
            raise ResearchInvariantError("activation requires a matching promotion decision")
        if not decision.rollback_verified:
            raise ResearchInvariantError("activation requires verified deterministic rollback")
        if decision.parent_representation_id != self._active_id:
            raise ResearchInvariantError("promotion decision parent must be the current active version")
        parent = self._versions[self._active_id]
        candidate = self._versions[representation_id]
        if candidate.parent_id != self._active_id:
            raise ResearchInvariantError("candidate must descend directly from the current active version")
        if decision.parent_representation_hash != parent.content_hash:
            raise ResearchInvariantError(
                "promotion decision parent content does not match the active representation"
            )
        if decision.candidate_representation_hash != candidate.content_hash:
            raise ResearchInvariantError(
                "promotion decision candidate content does not match the registered representation"
            )
        event = ActivationEvent(
            activation_id="activation_" + sha256_text(
                canonical_json([self._active_id, representation_id, decision.decision_id])
            )[:16],
            previous_active_id=self._active_id,
            new_active_id=representation_id,
            decision_id=decision.decision_id,
            action="activate",
        )
        self._active_id = representation_id
        self._activations.append(event)
        return event

    def bootstrap(self, representation_id: str) -> ActivationEvent:
        if self._active_id is not None or representation_id not in self._versions:
            raise ResearchInvariantError("bootstrap is allowed exactly once for a registered version")
        event = ActivationEvent(
            activation_id="activation_" + sha256_text(representation_id)[:16],
            previous_active_id=None,
            new_active_id=representation_id,
            decision_id="bootstrap",
            action="activate",
        )
        self._active_id = representation_id
        self._activations.append(event)
        return event

    def rollback(self, target_id: str, *, reason: str) -> ActivationEvent:
        if target_id not in self._versions or self._active_id is None:
            raise ResearchInvariantError("rollback target and active version are required")
        previously_active_ids = {event.new_active_id for event in self._activations}
        if target_id not in previously_active_ids:
            raise ResearchInvariantError("rollback target must have been active previously")
        if target_id == self._active_id:
            raise ResearchInvariantError("rollback target must differ from the current active version")
        event = ActivationEvent(
            activation_id="rollback_" + sha256_text(
                canonical_json([self._active_id, target_id, reason, len(self._activations)])
            )[:16],
            previous_active_id=self._active_id,
            new_active_id=target_id,
            decision_id=reason,
            action="rollback",
        )
        self._active_id = target_id
        self._activations.append(event)
        return event

    def get(self, representation_id: str) -> RepresentationVersion:
        return self._versions[representation_id]


def _evaluation_hash(summary: EvaluationSummary) -> str:
    return sha256_text(canonical_json(asdict(summary)))


class RepresentationRepairGate:
    """Protected no-regression gate; non-domination alone is insufficient."""

    gate_id = "hive-representation-repair-gate-v1"

    def __init__(self, evaluator: RepresentationEvaluator) -> None:
        self.evaluator = evaluator

    def evaluate(
        self,
        parent: RepresentationVersion,
        candidate: RepresentationVersion,
        *,
        protected_tasks: Sequence[TaskExpectation],
        new_tasks: Sequence[TaskExpectation],
        protocol_hash: str,
    ) -> MigrationDecision:
        parent_old = self.evaluator.evaluate(parent, protected_tasks)
        candidate_old = self.evaluator.evaluate(candidate, protected_tasks)
        parent_new = self.evaluator.evaluate(parent, new_tasks)
        candidate_new = self.evaluator.evaluate(candidate, new_tasks)
        parent_old_replay = self.evaluator.evaluate(parent, protected_tasks)
        parent_new_replay = self.evaluator.evaluate(parent, new_tasks)
        rollback_verified = (
            _evaluation_hash(parent_old) == _evaluation_hash(parent_old_replay)
            and _evaluation_hash(parent_new) == _evaluation_hash(parent_new_replay)
        )
        parent_payload = {"old": asdict(parent_old), "new": asdict(parent_new)}
        candidate_payload = {"old": asdict(candidate_old), "new": asdict(candidate_new)}
        if not rollback_verified:
            status, reason = "reject", "parent_replay_nondeterministic"
        elif not candidate_old.all_passed:
            status, reason = "reject", "protected_task_regression"
        elif candidate_new.passed <= parent_new.passed:
            status, reason = "reject", "no_positive_new_task_improvement"
        elif candidate.validation_status is ValidationStatus.REJECTED:
            status, reason = "reject", "candidate_validation_rejected"
        else:
            status, reason = "promote", "protected_noninferiority_and_new_task_improvement"
        payload = [
            parent.representation_id,
            candidate.representation_id,
            parent.content_hash,
            candidate.content_hash,
            protocol_hash,
            status,
            reason,
        ]
        return MigrationDecision(
            decision_id="migration_" + sha256_text(canonical_json(payload))[:16],
            parent_representation_id=parent.representation_id,
            candidate_representation_id=candidate.representation_id,
            parent_representation_hash=parent.content_hash,
            candidate_representation_hash=candidate.content_hash,
            protocol_hash=protocol_hash,
            evaluator_hash=sha256_text(self.evaluator.solver.solver_id),
            parent_outcome_hash=sha256_text(canonical_json(parent_payload)),
            candidate_outcome_hash=sha256_text(canonical_json(candidate_payload)),
            status=status,
            reason=reason,
            rollback_verified=rollback_verified,
        )


class DeterministicMissingDependencyProposer:
    """Oracle-assisted plumbing demonstration, explicitly not a learner."""

    proposer_id = "deterministic-missing-dependency-proposer-v1"

    def propose(
        self,
        parent: RepresentationVersion,
        source: RepresentationVersion,
        *,
        missing_component_id: str,
        candidate_id: str,
    ) -> tuple[RepresentationVersion, RepairProposal]:
        source_component = next(
            (item for item in source.components if item.component_id == missing_component_id),
            None,
        )
        if source_component is None:
            raise ResearchInvariantError("missing component is absent from the source representation")
        if any(item.component_id == missing_component_id for item in parent.components):
            raise ResearchInvariantError("parent already contains the requested component")
        components = tuple(sorted((*parent.components, source_component), key=lambda item: item.component_id))
        packet_bytes = len(canonical_json([asdict(item) for item in components]).encode("utf-8"))
        candidate = replace(
            parent,
            representation_id=candidate_id,
            version=parent.version + 1,
            parent_id=parent.representation_id,
            components=components,
            origin=OriginManifest(
                OriginKind.DETERMINISTIC_HEURISTIC,
                discovery_automatic=True,
                training_ids=("observed_failure_cluster",),
                human_semantic_dependencies=parent.origin.human_semantic_dependencies,
                oracle_assisted=True,
            ),
            validation_status=ValidationStatus.DETERMINISTICALLY_VALIDATED,
            cost=replace(parent.cost, packet_bytes=packet_bytes),
        )
        proposal = RepairProposal(
            proposal_id="repair_" + sha256_text(
                canonical_json([parent.representation_id, candidate_id, missing_component_id])
            )[:16],
            parent_representation_id=parent.representation_id,
            candidate_representation_id=candidate_id,
            implicated_component_ids=(missing_component_id,),
            retrieved_source_event_ids=source_component.source_event_ids,
            localizer_id="oracle_induced_demo_failure",
            diagnosis_confidence=1.0,
            oracle_assisted=True,
        )
        return candidate, proposal


@dataclass(frozen=True)
class ImprovementCycle:
    cycle_id: str
    protocol_hash: str
    evaluator_hash: str
    proposer_before_hash: str
    proposer_after_hash: str
    train_manifest_hash: str
    selection_manifest_hash: str
    metaheldout_manifest_hash: str
    control_arm: str
    total_cost_before: CostBreakdown
    total_cost_after: CostBreakdown
    benchmark_changed: bool
    evaluator_changed: bool
    heldout_leakage_detected: bool
    compute_matched: bool
    human_input_matched: bool
    rollback_verified: bool

    @property
    def admissible_recursive_evidence(self) -> bool:
        return (
            not self.benchmark_changed
            and not self.evaluator_changed
            and not self.heldout_leakage_detected
            and self.compute_matched
            and self.human_input_matched
            and self.rollback_verified
            and self.control_arm in {"frozen", "shuffled_meta", "no_meta"}
        )
