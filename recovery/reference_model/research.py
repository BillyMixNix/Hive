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
    RepresentationInvariantError,
    RepresentationVersion,
    SolveStatus,
    SolverOutcome,
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


def _is_normalized_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


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
        required_text = {
            "experiment_id": self.experiment_id,
            "protocol_hash": self.protocol_hash,
            "result": self.result,
        }
        missing = tuple(
            name
            for name, value in required_text.items()
            if not isinstance(value, str) or not value.strip()
        )
        if missing:
            raise ResearchInvariantError(
                "experiment evidence requires nonempty " + ", ".join(missing)
            )
        if not _is_normalized_sha256(self.protocol_hash):
            raise ResearchInvariantError(
                "experiment protocol hash must be normalized lowercase SHA-256 hex"
            )
        if self.validity not in {"VALID", "INVALID", "EXPLORATORY"}:
            raise ResearchInvariantError("unknown experiment validity")
        if not self.artifact_hashes:
            raise ResearchInvariantError("experiment evidence requires at least one artifact hash")
        if any(
            not _is_normalized_sha256(value)
            for value in self.artifact_hashes
        ):
            raise ResearchInvariantError(
                "artifact hashes must be normalized lowercase SHA-256 hex"
            )


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
    """Validated read-only view; upgrade checks are syntactic, not authoritative."""

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
    def validate_syntactic_eligibility(
        evidence: ExperimentEvidence,
        target_level: EvidenceLevel,
    ) -> None:
        """Fail closed when an upgrade would require trusted artifact verification."""

        if evidence.validity == "INVALID":
            raise ResearchInvariantError("invalid experiments cannot upgrade claims")
        if target_level in {EvidenceLevel.PROVEN, EvidenceLevel.SUPPORTED}:
            raise ResearchInvariantError(
                f"{target_level.value} requires a trusted artifact verifier; "
                "this registry performs syntactic eligibility checks only"
            )

    @staticmethod
    def validate_upgrade(evidence: ExperimentEvidence, target_level: EvidenceLevel) -> None:
        """Backward-compatible fail-closed alias for syntactic eligibility."""

        EvidenceRegistry.validate_syntactic_eligibility(evidence, target_level)


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
    gate_id: str = ""
    protected_task_manifest_hash: str = ""
    new_task_manifest_hash: str = ""
    cost_ceiling_hash: str = ""

    @staticmethod
    def _content_mapping(
        *,
        parent_representation_id: str,
        candidate_representation_id: str,
        parent_representation_hash: str,
        candidate_representation_hash: str,
        protocol_hash: str,
        evaluator_hash: str,
        parent_outcome_hash: str,
        candidate_outcome_hash: str,
        status: str,
        reason: str,
        rollback_verified: bool,
        gate_id: str,
        protected_task_manifest_hash: str,
        new_task_manifest_hash: str,
        cost_ceiling_hash: str,
    ) -> dict[str, Any]:
        return {
            "candidate_outcome_hash": candidate_outcome_hash,
            "candidate_representation_hash": candidate_representation_hash,
            "candidate_representation_id": candidate_representation_id,
            "cost_ceiling_hash": cost_ceiling_hash,
            "evaluator_hash": evaluator_hash,
            "gate_id": gate_id,
            "new_task_manifest_hash": new_task_manifest_hash,
            "parent_outcome_hash": parent_outcome_hash,
            "parent_representation_hash": parent_representation_hash,
            "parent_representation_id": parent_representation_id,
            "protected_task_manifest_hash": protected_task_manifest_hash,
            "protocol_hash": protocol_hash,
            "reason": reason,
            "rollback_verified": rollback_verified,
            "status": status,
        }

    @classmethod
    def from_content(cls, **content: Any) -> "MigrationDecision":
        """Build a deterministically identified record; this grants no activation authority."""

        content_mapping = cls._content_mapping(**content)
        return cls(
            decision_id="migration_" + sha256_text(canonical_json(content_mapping)),
            **content,
        )

    def __post_init__(self) -> None:
        required = (
            self.decision_id,
            self.parent_representation_id,
            self.candidate_representation_id,
            self.parent_representation_hash,
            self.candidate_representation_hash,
            self.protocol_hash,
            self.evaluator_hash,
            self.parent_outcome_hash,
            self.candidate_outcome_hash,
            self.reason,
            self.gate_id,
            self.protected_task_manifest_hash,
            self.new_task_manifest_hash,
            self.cost_ceiling_hash,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ResearchInvariantError("migration decisions require complete nonempty evidence")
        if self.status not in {"promote", "reject"}:
            raise ResearchInvariantError("migration decision status must be promote or reject")
        hashes = (
            self.parent_representation_hash,
            self.candidate_representation_hash,
            self.protocol_hash,
            self.evaluator_hash,
            self.parent_outcome_hash,
            self.candidate_outcome_hash,
            self.protected_task_manifest_hash,
            self.new_task_manifest_hash,
            self.cost_ceiling_hash,
        )
        if any(not _is_normalized_sha256(value) for value in hashes):
            raise ResearchInvariantError(
                "migration decision hashes must be normalized lowercase SHA-256 hex"
            )
        if self.decision_id != "migration_" + self.content_hash:
            raise ResearchInvariantError("migration decision ID does not match full content hash")

    @property
    def content_hash(self) -> str:
        """Hash every decision field except the ID derived from this content."""

        return sha256_text(
            canonical_json(
                self._content_mapping(
                    parent_representation_id=self.parent_representation_id,
                    candidate_representation_id=self.candidate_representation_id,
                    parent_representation_hash=self.parent_representation_hash,
                    candidate_representation_hash=self.candidate_representation_hash,
                    protocol_hash=self.protocol_hash,
                    evaluator_hash=self.evaluator_hash,
                    parent_outcome_hash=self.parent_outcome_hash,
                    candidate_outcome_hash=self.candidate_outcome_hash,
                    status=self.status,
                    reason=self.reason,
                    rollback_verified=self.rollback_verified,
                    gate_id=self.gate_id,
                    protected_task_manifest_hash=self.protected_task_manifest_hash,
                    new_task_manifest_hash=self.new_task_manifest_hash,
                    cost_ceiling_hash=self.cost_ceiling_hash,
                )
            )
        )


@dataclass(frozen=True)
class ActivationEvent:
    activation_id: str
    previous_active_id: str | None
    new_active_id: str
    decision_id: str
    decision_content_hash: str
    activation_sequence: int
    action: str


_MIGRATION_GATE_ID = "hive-representation-repair-gate-v2"
_PROMOTABLE_VALIDATION_STATUSES = frozenset(
    {
        ValidationStatus.DETERMINISTICALLY_VALIDATED,
        ValidationStatus.EMPIRICALLY_VALIDATED,
        ValidationStatus.TRANSFER_VALIDATED,
    }
)
_COMPATIBILITY_FIELDS = (
    "family_id",
    "schema_id",
    "codec_id",
    "source_ledger_hash",
    "source_component_manifest_hash",
)
MATCHED_RESOURCE_COST_FIELDS = tuple(CostBreakdown.__dataclass_fields__)


def task_manifest_hash(tasks: Sequence[TaskExpectation]) -> str:
    """Hash the exact ordered task/expectation sequence used by a frozen gate."""

    return sha256_text(canonical_json(tuple(tasks)))


def _cost_ceiling_hash(cost: CostBreakdown) -> str:
    if type(cost) is not CostBreakdown:
        raise ResearchInvariantError("cost ceiling must be an exact CostBreakdown")
    try:
        cost.validate_integrity()
    except RepresentationInvariantError as exc:
        raise ResearchInvariantError("cost ceiling is invalid") from exc
    return sha256_text(canonical_json(asdict(cost)))


def _require_representation_cost_integrity(
    representation: RepresentationVersion,
) -> None:
    try:
        representation.validate_cost_integrity()
    except RepresentationInvariantError as exc:
        raise ResearchInvariantError(
            "representation cost accounting is invalid"
        ) from exc


def _candidate_compatibility_error(
    parent: RepresentationVersion,
    candidate: RepresentationVersion,
) -> str | None:
    if candidate.parent_id != parent.representation_id:
        return "candidate_parent_mismatch"
    if candidate.version != parent.version + 1:
        return "candidate_version_mismatch"
    for field_name in _COMPATIBILITY_FIELDS:
        if getattr(candidate, field_name) != getattr(parent, field_name):
            return f"candidate_{field_name}_mismatch"
    return None


def _require_registry_eligible(representation: RepresentationVersion) -> None:
    if representation.validation_status not in _PROMOTABLE_VALIDATION_STATUSES:
        raise ResearchInvariantError(
            "representation registry requires deterministic, empirical, or transfer validation"
        )


class RepresentationRegistry:
    """Immutable versions with append-only active-pointer changes."""

    def __init__(
        self,
        *,
        gate: "RepresentationRepairGate",
        protected_tasks: Sequence[TaskExpectation],
        new_tasks: Sequence[TaskExpectation],
        protocol_hash: str,
    ) -> None:
        if type(gate) is not RepresentationRepairGate:
            raise ResearchInvariantError("registry requires the concrete protected repair gate")
        if type(gate.evaluator) is not RepresentationEvaluator:
            raise ResearchInvariantError("registry requires an exact trusted RepresentationEvaluator")
        if not _is_normalized_sha256(protocol_hash):
            raise ResearchInvariantError(
                "registry protocol hash must be normalized lowercase SHA-256 hex"
            )
        protected = tuple(protected_tasks)
        new = tuple(new_tasks)
        if not protected or not new:
            raise ResearchInvariantError("registry requires nonempty protected and new task suites")
        if any(type(task) is not TaskExpectation for task in (*protected, *new)):
            raise ResearchInvariantError("registry task suites require exact TaskExpectation records")
        query_ids = tuple(task.query.query_id for task in (*protected, *new))
        if len(query_ids) != len(set(query_ids)):
            raise ResearchInvariantError("protected and new task query IDs must be unique")
        protected_manifest_hash = task_manifest_hash(protected)
        new_manifest_hash = task_manifest_hash(new)
        if protected_manifest_hash == new_manifest_hash:
            raise ResearchInvariantError("protected and new task manifests must differ")

        self._versions: dict[str, RepresentationVersion] = {}
        self._version_hashes: dict[str, str] = {}
        self._activations: list[ActivationEvent] = []
        self._active_id: str | None = None
        self._gate = gate
        self._evaluator = gate.evaluator
        self._decompressor = gate.evaluator.decompressor
        self._solver = gate.evaluator.solver
        self._evaluator_hash = gate.evaluator_hash
        self._candidate_cost_ceiling = gate.candidate_cost_ceiling
        self._candidate_cost_ceiling_hash = (
            None
            if gate.candidate_cost_ceiling is None
            else _cost_ceiling_hash(gate.candidate_cost_ceiling)
        )
        self._protected_tasks = protected
        self._new_tasks = new
        self._protocol_hash = protocol_hash
        self._protected_task_manifest_hash = protected_manifest_hash
        self._new_task_manifest_hash = new_manifest_hash

    @property
    def active_id(self) -> str | None:
        return self._active_id

    @property
    def active(self) -> RepresentationVersion | None:
        if self._active_id is None:
            return None
        return self._require_committed_version(self._active_id)

    @property
    def activations(self) -> tuple[ActivationEvent, ...]:
        return tuple(self._activations)

    @property
    def protected_task_manifest_hash(self) -> str:
        return self._protected_task_manifest_hash

    @property
    def new_task_manifest_hash(self) -> str:
        return self._new_task_manifest_hash

    @property
    def protocol_hash(self) -> str:
        return self._protocol_hash

    def register(self, representation: RepresentationVersion) -> None:
        if type(representation) is not RepresentationVersion:
            raise ResearchInvariantError("registry requires exact RepresentationVersion records")
        if type(representation.cost) is not CostBreakdown:
            raise ResearchInvariantError("representation requires an exact CostBreakdown")
        _require_representation_cost_integrity(representation)
        if representation.representation_id in self._versions:
            raise ResearchInvariantError("representation versions are immutable and IDs cannot be reused")
        _require_registry_eligible(representation)
        if representation.parent_id is not None and representation.parent_id not in self._versions:
            raise ResearchInvariantError("representation parent must be registered")
        if representation.parent_id is not None:
            parent = self._require_committed_version(representation.parent_id)
            compatibility_error = _candidate_compatibility_error(parent, representation)
            if compatibility_error is not None:
                raise ResearchInvariantError(
                    "representation candidate is incompatible with its parent: "
                    + compatibility_error
                )
        representation_hash = representation.content_hash
        if not _is_normalized_sha256(representation_hash):
            raise ResearchInvariantError("representation content hash must be normalized SHA-256")
        self._versions[representation.representation_id] = representation
        self._version_hashes[representation.representation_id] = representation_hash

    def _require_committed_version(
        self,
        representation_id: str,
    ) -> RepresentationVersion:
        representation = self._versions[representation_id]
        expected_hash = self._version_hashes.get(representation_id)
        try:
            _require_representation_cost_integrity(representation)
            actual_hash = representation.content_hash
        except ResearchInvariantError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ResearchInvariantError(
                "registered representation content cannot be revalidated"
            ) from exc
        if expected_hash is None or actual_hash != expected_hash:
            raise ResearchInvariantError(
                "registered representation content changed after registration"
            )
        return representation

    def activate(self, representation_id: str, decision: MigrationDecision) -> ActivationEvent:
        """Reject direct activation; evaluation and mutation are one registry operation."""

        del representation_id, decision
        raise ResearchInvariantError(
            "direct activation is forbidden; use evaluate_and_activate with a repair gate"
        )

    def evaluate_and_activate(
        self,
        representation_id: str,
    ) -> tuple[MigrationDecision, ActivationEvent | None]:
        """Evaluate exact registered versions and apply only the synchronous gate result."""

        if representation_id not in self._versions:
            raise ResearchInvariantError("cannot activate an unregistered representation")
        if self._active_id is None:
            raise ResearchInvariantError("activation requires a bootstrapped active representation")
        parent = self._require_committed_version(self._active_id)
        candidate = self._require_committed_version(representation_id)
        gate = self._gate
        if (
            type(gate) is not RepresentationRepairGate
            or type(gate.evaluator) is not RepresentationEvaluator
            or gate.evaluator is not self._evaluator
            or gate.evaluator.decompressor is not self._decompressor
            or gate.evaluator.solver is not self._solver
            or gate.evaluator_hash != self._evaluator_hash
            or gate.candidate_cost_ceiling != self._candidate_cost_ceiling
            or (
                None
                if gate.candidate_cost_ceiling is None
                else _cost_ceiling_hash(gate.candidate_cost_ceiling)
            )
            != self._candidate_cost_ceiling_hash
        ):
            raise ResearchInvariantError("frozen repair-gate or evaluator configuration changed")
        if task_manifest_hash(self._protected_tasks) != self._protected_task_manifest_hash:
            raise ResearchInvariantError("frozen protected task manifest changed")
        if task_manifest_hash(self._new_tasks) != self._new_task_manifest_hash:
            raise ResearchInvariantError("frozen new task manifest changed")
        decision = RepresentationRepairGate.evaluate(
            gate,
            parent,
            candidate,
            protected_tasks=self._protected_tasks,
            new_tasks=self._new_tasks,
            protocol_hash=self._protocol_hash,
        )
        parent = self._require_committed_version(self._active_id)
        candidate = self._require_committed_version(representation_id)
        if decision.status == "reject":
            return decision, None
        if not gate.gate_id or decision.gate_id != gate.gate_id:
            raise ResearchInvariantError("activation requires the synchronous repair-gate decision")
        if decision.protocol_hash != self._protocol_hash:
            raise ResearchInvariantError("migration decision protocol does not match frozen registry")
        if decision.evaluator_hash != gate.evaluator_hash:
            raise ResearchInvariantError("migration decision evaluator does not match frozen registry")
        if decision.protected_task_manifest_hash != self._protected_task_manifest_hash:
            raise ResearchInvariantError("migration decision protected manifest mismatch")
        if decision.new_task_manifest_hash != self._new_task_manifest_hash:
            raise ResearchInvariantError("migration decision new-task manifest mismatch")
        expected_ceiling = gate.cost_ceiling_for(parent)
        if decision.cost_ceiling_hash != _cost_ceiling_hash(expected_ceiling):
            raise ResearchInvariantError("migration decision cost ceiling mismatch")
        if decision.status != "promote" or decision.candidate_representation_id != representation_id:
            raise ResearchInvariantError("activation requires a matching promotion decision")
        if not decision.rollback_verified:
            raise ResearchInvariantError("activation requires verified deterministic rollback")
        if decision.parent_representation_id != self._active_id:
            raise ResearchInvariantError("promotion decision parent must be the current active version")
        parent = self._require_committed_version(self._active_id)
        candidate = self._require_committed_version(representation_id)
        _require_registry_eligible(candidate)
        compatibility_error = _candidate_compatibility_error(parent, candidate)
        if compatibility_error is not None:
            raise ResearchInvariantError(
                "candidate must be compatible with the current active version: "
                + compatibility_error
            )
        if decision.parent_representation_hash != parent.content_hash:
            raise ResearchInvariantError(
                "promotion decision parent content does not match the active representation"
            )
        if decision.candidate_representation_hash != candidate.content_hash:
            raise ResearchInvariantError(
                "promotion decision candidate content does not match the registered representation"
            )
        event = ActivationEvent(
            activation_id="activation_"
            + sha256_text(
                canonical_json(
                    {
                        "activation_sequence": len(self._activations),
                        "decision_content_hash": decision.content_hash,
                        "new_active_id": representation_id,
                        "previous_active_id": self._active_id,
                    }
                )
            ),
            previous_active_id=self._active_id,
            new_active_id=representation_id,
            decision_id=decision.decision_id,
            decision_content_hash=decision.content_hash,
            activation_sequence=len(self._activations),
            action="activate",
        )
        self._active_id = representation_id
        self._activations.append(event)
        return decision, event

    def bootstrap(self, representation_id: str) -> ActivationEvent:
        if self._active_id is not None or representation_id not in self._versions:
            raise ResearchInvariantError("bootstrap is allowed exactly once for a registered version")
        representation = self._require_committed_version(representation_id)
        sequence = len(self._activations)
        decision_content_hash = sha256_text(
            canonical_json(
                {
                    "action": "bootstrap",
                    "representation_hash": representation.content_hash,
                }
            )
        )
        event = ActivationEvent(
            activation_id="activation_"
            + sha256_text(
                canonical_json(
                    {
                        "activation_sequence": sequence,
                        "decision_content_hash": decision_content_hash,
                        "new_active_id": representation_id,
                        "previous_active_id": None,
                    }
                )
            ),
            previous_active_id=None,
            new_active_id=representation_id,
            decision_id="bootstrap",
            decision_content_hash=decision_content_hash,
            activation_sequence=sequence,
            action="activate",
        )
        self._active_id = representation_id
        self._activations.append(event)
        return event

    def rollback(self, target_id: str, *, reason: str) -> ActivationEvent:
        if target_id not in self._versions or self._active_id is None:
            raise ResearchInvariantError("rollback target and active version are required")
        if not isinstance(reason, str) or not reason.strip():
            raise ResearchInvariantError("rollback requires a nonempty reason")
        self._require_committed_version(self._active_id)
        self._require_committed_version(target_id)
        previously_active_ids = {event.new_active_id for event in self._activations}
        if target_id not in previously_active_ids:
            raise ResearchInvariantError("rollback target must have been active previously")
        if target_id == self._active_id:
            raise ResearchInvariantError("rollback target must differ from the current active version")
        sequence = len(self._activations)
        decision_content_hash = sha256_text(
            canonical_json(
                {
                    "action": "rollback",
                    "from": self._active_id,
                    "reason": reason,
                    "to": target_id,
                }
            )
        )
        event = ActivationEvent(
            activation_id="rollback_"
            + sha256_text(
                canonical_json(
                    {
                        "activation_sequence": sequence,
                        "decision_content_hash": decision_content_hash,
                        "new_active_id": target_id,
                        "previous_active_id": self._active_id,
                    }
                )
            ),
            previous_active_id=self._active_id,
            new_active_id=target_id,
            decision_id=reason,
            decision_content_hash=decision_content_hash,
            activation_sequence=sequence,
            action="rollback",
        )
        self._active_id = target_id
        self._activations.append(event)
        return event

    def get(self, representation_id: str) -> RepresentationVersion:
        return self._require_committed_version(representation_id)


def _evaluation_hash(summary: EvaluationSummary) -> str:
    return sha256_text(canonical_json(asdict(summary)))


def _evaluate_validated_summary(
    evaluator: RepresentationEvaluator,
    representation: RepresentationVersion,
    tasks: Sequence[TaskExpectation],
) -> EvaluationSummary:
    if type(evaluator) is not RepresentationEvaluator:
        raise ResearchInvariantError("repair gate requires an exact trusted evaluator")
    summary = RepresentationEvaluator.evaluate(evaluator, representation, tasks)
    if type(summary) is not EvaluationSummary:
        raise ResearchInvariantError("evaluator returned a nonstandard EvaluationSummary")
    if summary.representation_id != representation.representation_id:
        raise ResearchInvariantError("evaluation summary representation ID mismatch")
    if type(summary.total) is not int or summary.total != len(tasks):
        raise ResearchInvariantError("evaluation summary total does not match task count")
    if type(summary.passed) is not int or not 0 <= summary.passed <= summary.total:
        raise ResearchInvariantError("evaluation summary passed count is invalid")
    if type(summary.outcomes) is not tuple or len(summary.outcomes) != len(tasks):
        raise ResearchInvariantError("evaluation summary outcomes do not match task count")
    for outcome, expectation in zip(summary.outcomes, tasks):
        if type(outcome) is not SolverOutcome or type(outcome.status) is not SolveStatus:
            raise ResearchInvariantError("evaluation summary contains a nonstandard outcome")
        if outcome.query_id != expectation.query.query_id:
            raise ResearchInvariantError("evaluation outcome query ID mismatch")
    recomputed_passed = sum(
        outcome.status is SolveStatus.COMPLETE
        and outcome.answer == expectation.expected_answer
        for outcome, expectation in zip(summary.outcomes, tasks)
    )
    if summary.passed != recomputed_passed:
        raise ResearchInvariantError("evaluation summary passed count is inconsistent")
    if type(summary.all_passed) is not bool or summary.all_passed != (
        recomputed_passed == len(tasks)
    ):
        raise ResearchInvariantError("evaluation summary all_passed is inconsistent")
    return summary


class RepresentationRepairGate:
    """Protected no-regression gate; non-domination alone is insufficient."""

    gate_id = _MIGRATION_GATE_ID

    def __init__(
        self,
        evaluator: RepresentationEvaluator,
        *,
        candidate_cost_ceiling: CostBreakdown | None = None,
    ) -> None:
        if type(evaluator) is not RepresentationEvaluator:
            raise ResearchInvariantError("repair gate requires an exact RepresentationEvaluator")
        if candidate_cost_ceiling is not None and type(candidate_cost_ceiling) is not CostBreakdown:
            raise ResearchInvariantError("repair gate cost ceiling must be an exact CostBreakdown")
        self.evaluator = evaluator
        self.candidate_cost_ceiling = candidate_cost_ceiling

    @property
    def evaluator_hash(self) -> str:
        try:
            digest = self.evaluator.configuration_hash
        except (AttributeError, TypeError, ValueError) as exc:
            raise ResearchInvariantError(
                "repair evaluator configuration fingerprint is unavailable"
            ) from exc
        if not _is_normalized_sha256(digest):
            raise ResearchInvariantError(
                "repair evaluator configuration fingerprint must be normalized SHA-256"
            )
        return digest

    def cost_ceiling_for(self, parent: RepresentationVersion) -> CostBreakdown:
        return self.candidate_cost_ceiling or parent.cost

    def evaluate(
        self,
        parent: RepresentationVersion,
        candidate: RepresentationVersion,
        *,
        protected_tasks: Sequence[TaskExpectation],
        new_tasks: Sequence[TaskExpectation],
        protocol_hash: str,
    ) -> MigrationDecision:
        if type(parent) is not RepresentationVersion or type(candidate) is not RepresentationVersion:
            raise ResearchInvariantError("repair gate requires exact RepresentationVersion records")
        if type(parent.cost) is not CostBreakdown or type(candidate.cost) is not CostBreakdown:
            raise ResearchInvariantError("repair gate requires exact CostBreakdown records")
        _require_representation_cost_integrity(parent)
        _require_representation_cost_integrity(candidate)
        if not _is_normalized_sha256(protocol_hash):
            raise ResearchInvariantError(
                "repair protocol hash must be normalized lowercase SHA-256 hex"
            )
        evaluator_hash = self.evaluator_hash
        protected_manifest_hash = task_manifest_hash(protected_tasks)
        new_manifest_hash = task_manifest_hash(new_tasks)
        cost_ceiling = self.cost_ceiling_for(parent)
        cost_ceiling_hash = _cost_ceiling_hash(cost_ceiling)
        compatibility_error = _candidate_compatibility_error(parent, candidate)
        if candidate.validation_status not in _PROMOTABLE_VALIDATION_STATUSES:
            reason = "candidate_validation_" + candidate.validation_status.value
            return RepresentationRepairGate._issue_decision(
                self,
                parent,
                candidate,
                protocol_hash=protocol_hash,
                evaluator_hash=evaluator_hash,
                parent_payload={"evaluation_skipped": reason},
                candidate_payload={"evaluation_skipped": reason},
                status="reject",
                reason=reason,
                rollback_verified=False,
                protected_task_manifest_hash=protected_manifest_hash,
                new_task_manifest_hash=new_manifest_hash,
                cost_ceiling_hash=cost_ceiling_hash,
            )
        if compatibility_error is not None:
            return RepresentationRepairGate._issue_decision(
                self,
                parent,
                candidate,
                protocol_hash=protocol_hash,
                evaluator_hash=evaluator_hash,
                parent_payload={"evaluation_skipped": compatibility_error},
                candidate_payload={"evaluation_skipped": compatibility_error},
                status="reject",
                reason=compatibility_error,
                rollback_verified=False,
                protected_task_manifest_hash=protected_manifest_hash,
                new_task_manifest_hash=new_manifest_hash,
                cost_ceiling_hash=cost_ceiling_hash,
            )
        if not protected_tasks or not new_tasks:
            reason = "empty_gate_task_suite"
            return RepresentationRepairGate._issue_decision(
                self,
                parent,
                candidate,
                protocol_hash=protocol_hash,
                evaluator_hash=evaluator_hash,
                parent_payload={"evaluation_skipped": reason},
                candidate_payload={"evaluation_skipped": reason},
                status="reject",
                reason=reason,
                rollback_verified=False,
                protected_task_manifest_hash=protected_manifest_hash,
                new_task_manifest_hash=new_manifest_hash,
                cost_ceiling_hash=cost_ceiling_hash,
            )
        exceeded_cost_fields = tuple(
            field_name
            for field_name in MATCHED_RESOURCE_COST_FIELDS
            if getattr(candidate.cost, field_name) > getattr(cost_ceiling, field_name)
        )
        if exceeded_cost_fields:
            reason = "candidate_cost_ceiling_exceeded:" + ",".join(exceeded_cost_fields)
            return RepresentationRepairGate._issue_decision(
                self,
                parent,
                candidate,
                protocol_hash=protocol_hash,
                evaluator_hash=evaluator_hash,
                parent_payload={"evaluation_skipped": reason},
                candidate_payload={"evaluation_skipped": reason},
                status="reject",
                reason=reason,
                rollback_verified=False,
                protected_task_manifest_hash=protected_manifest_hash,
                new_task_manifest_hash=new_manifest_hash,
                cost_ceiling_hash=cost_ceiling_hash,
            )
        parent_old = _evaluate_validated_summary(self.evaluator, parent, protected_tasks)
        candidate_old = _evaluate_validated_summary(self.evaluator, candidate, protected_tasks)
        parent_new = _evaluate_validated_summary(self.evaluator, parent, new_tasks)
        candidate_new = _evaluate_validated_summary(self.evaluator, candidate, new_tasks)
        parent_old_replay = _evaluate_validated_summary(
            self.evaluator,
            parent,
            protected_tasks,
        )
        parent_new_replay = _evaluate_validated_summary(
            self.evaluator,
            parent,
            new_tasks,
        )
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
        else:
            status, reason = "promote", "protected_noninferiority_and_new_task_improvement"
        return RepresentationRepairGate._issue_decision(
            self,
            parent,
            candidate,
            protocol_hash=protocol_hash,
            evaluator_hash=evaluator_hash,
            parent_payload=parent_payload,
            candidate_payload=candidate_payload,
            status=status,
            reason=reason,
            rollback_verified=rollback_verified,
            protected_task_manifest_hash=protected_manifest_hash,
            new_task_manifest_hash=new_manifest_hash,
            cost_ceiling_hash=cost_ceiling_hash,
        )

    def _issue_decision(
        self,
        parent: RepresentationVersion,
        candidate: RepresentationVersion,
        *,
        protocol_hash: str,
        evaluator_hash: str,
        parent_payload: Mapping[str, Any],
        candidate_payload: Mapping[str, Any],
        status: str,
        reason: str,
        rollback_verified: bool,
        protected_task_manifest_hash: str,
        new_task_manifest_hash: str,
        cost_ceiling_hash: str,
    ) -> MigrationDecision:
        return MigrationDecision.from_content(
            parent_representation_id=parent.representation_id,
            candidate_representation_id=candidate.representation_id,
            parent_representation_hash=parent.content_hash,
            candidate_representation_hash=candidate.content_hash,
            protocol_hash=protocol_hash,
            evaluator_hash=evaluator_hash,
            parent_outcome_hash=sha256_text(canonical_json(parent_payload)),
            candidate_outcome_hash=sha256_text(canonical_json(candidate_payload)),
            status=status,
            reason=reason,
            rollback_verified=rollback_verified,
            gate_id=self.gate_id,
            protected_task_manifest_hash=protected_task_manifest_hash,
            new_task_manifest_hash=new_task_manifest_hash,
            cost_ceiling_hash=cost_ceiling_hash,
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
        incompatible_fields = tuple(
            field
            for field in (
                "source_ledger_hash",
                "family_id",
                "schema_id",
                "codec_id",
            )
            if getattr(source, field) != getattr(parent, field)
        )
        if incompatible_fields:
            raise ResearchInvariantError(
                "repair source has foreign provenance: mismatched "
                + ", ".join(incompatible_fields)
            )
        if (
            source.source_component_manifest_hash
            != parent.source_component_manifest_hash
        ):
            raise ResearchInvariantError(
                "repair source has foreign provenance: full-source component "
                "manifest mismatch"
            )
        source_component = next(
            (item for item in source.components if item.component_id == missing_component_id),
            None,
        )
        if source_component is None:
            raise ResearchInvariantError("missing component is absent from the source representation")
        trusted_manifest_entry = next(
            (
                item
                for item in parent.source_component_manifest
                if item.component_id == missing_component_id
            ),
            None,
        )
        if (
            trusted_manifest_entry is None
            or trusted_manifest_entry.content_hash != source_component.content_hash
            or trusted_manifest_entry.component_kind
            is not source_component.component_kind
        ):
            raise ResearchInvariantError(
                "repair component is not an exact member of the parent's trusted "
                "full-source manifest"
            )
        if any(item.component_id == missing_component_id for item in parent.components):
            raise ResearchInvariantError("parent already contains the requested component")
        components = tuple(sorted((*parent.components, source_component), key=lambda item: item.component_id))
        packet_bytes = RepresentationVersion.compute_packet_bytes(
            components,
            parent.source_component_manifest,
            parent.source_component_manifest_hash,
        )
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
    metaheldout_episode_count: int = 0
    metaheldout_replication_count: int = 0
    proposer_before_success_count: int = 0
    proposer_after_success_count: int = 0
    meta_ablation_success_count: int = 0
    meta_ablation_control: str = ""

    def __post_init__(self) -> None:
        if (
            type(self.total_cost_before) is not CostBreakdown
            or type(self.total_cost_after) is not CostBreakdown
        ):
            raise ResearchInvariantError(
                "improvement cycles require exact CostBreakdown resource records"
            )
        identifiers = {
            "cycle_id": self.cycle_id,
            "protocol_hash": self.protocol_hash,
            "evaluator_hash": self.evaluator_hash,
            "proposer_before_hash": self.proposer_before_hash,
            "proposer_after_hash": self.proposer_after_hash,
            "train_manifest_hash": self.train_manifest_hash,
            "selection_manifest_hash": self.selection_manifest_hash,
            "metaheldout_manifest_hash": self.metaheldout_manifest_hash,
        }
        missing = tuple(
            name
            for name, value in identifiers.items()
            if not isinstance(value, str) or not value.strip()
        )
        if missing:
            raise ResearchInvariantError(
                "improvement cycles require nonempty " + ", ".join(missing)
            )
        if self.proposer_before_hash == self.proposer_after_hash:
            raise ResearchInvariantError("before and after proposer hashes must differ")
        manifests = (
            self.train_manifest_hash,
            self.selection_manifest_hash,
            self.metaheldout_manifest_hash,
        )
        if len(set(manifests)) != len(manifests):
            raise ResearchInvariantError("train, selection, and metaheldout manifests must differ")
        counts = (
            self.metaheldout_episode_count,
            self.metaheldout_replication_count,
            self.proposer_before_success_count,
            self.proposer_after_success_count,
            self.meta_ablation_success_count,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ResearchInvariantError("metaheldout evidence counts must be nonnegative integers")
        if self.metaheldout_replication_count > self.metaheldout_episode_count:
            raise ResearchInvariantError(
                "metaheldout replication count cannot exceed episode count"
            )
        if any(value > self.metaheldout_episode_count for value in counts[2:]):
            raise ResearchInvariantError("metaheldout success counts cannot exceed episode count")

    @property
    def matched_resource_costs(self) -> bool:
        """Whether every preregistered CostBreakdown resource field is equal."""

        return all(
            getattr(self.total_cost_before, field_name)
            == getattr(self.total_cost_after, field_name)
            for field_name in MATCHED_RESOURCE_COST_FIELDS
        )

    @property
    def admissible_recursive_evidence(self) -> bool:
        return (
            not self.benchmark_changed
            and not self.evaluator_changed
            and not self.heldout_leakage_detected
            and self.compute_matched
            and self.matched_resource_costs
            and self.human_input_matched
            and self.rollback_verified
            and self.control_arm == "frozen"
            and self.meta_ablation_control in {"shuffled_meta", "no_meta"}
            and self.metaheldout_episode_count >= 2
            and self.metaheldout_replication_count >= 2
            and self.proposer_after_success_count > self.proposer_before_success_count
            and self.meta_ablation_success_count <= self.proposer_before_success_count
        )
