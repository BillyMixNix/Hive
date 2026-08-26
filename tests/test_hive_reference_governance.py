from __future__ import annotations

from dataclasses import replace
import pytest

from hive_reference.model import sha256_text
from hive_reference.representation import (
    CostBreakdown,
    OriginKind,
    OriginManifest,
    RepresentationEvaluator,
    RepresentationVersion,
    SolveStatus,
    SolverOutcome,
    TaskExpectation,
    TaskKind,
    TaskQuery,
    ValidationStatus,
)
from hive_reference.research import (
    FitnessVector,
    MigrationDecision,
    RepresentationRegistry,
    RepresentationRepairGate,
    ResearchInvariantError,
    pareto_frontier,
)


def _representation(
    representation_id: str,
    *,
    parent_id: str | None = None,
    version: int = 1,
) -> RepresentationVersion:
    manifest_hash = RepresentationVersion.compute_source_component_manifest_hash(())
    return RepresentationVersion(
        representation_id=representation_id,
        family_id="governance-test-family",
        version=version,
        parent_id=parent_id,
        source_ledger_hash="ledger",
        codec_id="codec",
        schema_id="schema",
        components=(),
        preservation_scope=(),
        known_failure_modes=(),
        origin=OriginManifest(OriginKind.HANDCRAFTED, discovery_automatic=False),
        validation_status=ValidationStatus.DETERMINISTICALLY_VALIDATED,
        cost=CostBreakdown(
            packet_bytes=RepresentationVersion.compute_packet_bytes(
                (), (), manifest_hash
            ),
        ),
        source_component_manifest_hash=manifest_hash,
    )


def _decision(
    parent_id: str,
    candidate_id: str,
    *,
    status: str = "promote",
    rollback_verified: bool = True,
    parent_hash: str | None = None,
    candidate_hash: str | None = None,
) -> MigrationDecision:
    return MigrationDecision.from_content(
        parent_representation_id=parent_id,
        candidate_representation_id=candidate_id,
        parent_representation_hash=parent_hash or _representation(parent_id).content_hash,
        candidate_representation_hash=candidate_hash
        or _representation(candidate_id, parent_id=parent_id, version=2).content_hash,
        protocol_hash=sha256_text("protocol"),
        evaluator_hash=sha256_text("evaluator"),
        parent_outcome_hash=sha256_text("parent-outcome"),
        candidate_outcome_hash=sha256_text("candidate-outcome"),
        status=status,
        reason="test",
        rollback_verified=rollback_verified,
        gate_id=RepresentationRepairGate.gate_id,
        protected_task_manifest_hash=sha256_text("protected"),
        new_task_manifest_hash=sha256_text("new"),
        cost_ceiling_hash=sha256_text("cost"),
    )


def _fitness(
    representation_id: str,
    *,
    hard_gates_passed: bool,
    accuracy: float,
    packet_bytes: int,
) -> FitnessVector:
    return FitnessVector(
        protocol_id="protocol",
        solver_id="solver",
        task_set_hash="tasks",
        representation_id=representation_id,
        sample_size=10,
        hard_gates_passed=hard_gates_passed,
        reconstruction_accuracy=accuracy,
        task_accuracy=accuracy,
        causal_accuracy=accuracy,
        temporal_accuracy=accuracy,
        authority_accuracy=accuracy,
        provenance_retention=accuracy,
        transfer_accuracy=accuracy,
        robustness=accuracy,
        cost=CostBreakdown(packet_bytes=packet_bytes),
    )


def _task(query_id: str) -> TaskExpectation:
    return TaskExpectation(
        query=TaskQuery(
            query_id=query_id,
            kind=TaskKind.VALUE_AT,
            keys=(),
            valid_at=0,
            known_at=0,
        ),
        expected_answer="pass",
    )


PROTECTED_TASKS = (_task("protected"),)
NEW_TASKS = (_task("new"),)
PROTOCOL_HASH = sha256_text("governance-fixed-protocol")


class _MarkerDecompressor:
    configuration_hash = sha256_text("governance-marker-decompressor-v1")

    def decompress(self, representation, query):
        return type("View", (), {"representation_id": representation.representation_id})()


class _ImprovementSolver:
    solver_id = "governance-improvement-solver"
    configuration_hash = sha256_text("governance-improvement-solver-v1")

    def solve(self, view, query):
        answer = (
            "pass"
            if query.query_id == "protected" or view.representation_id != "root"
            else "fail"
        )
        return SolverOutcome(
            query_id=query.query_id,
            status=SolveStatus.COMPLETE,
            answer=answer,
            used_component_ids=(),
            evidence_observation_ids=(),
        )


def _registry() -> RepresentationRegistry:
    evaluator = RepresentationEvaluator(_MarkerDecompressor(), _ImprovementSolver())
    return RepresentationRegistry(
        gate=RepresentationRepairGate(evaluator),
        protected_tasks=PROTECTED_TASKS,
        new_tasks=NEW_TASKS,
        protocol_hash=PROTOCOL_HASH,
    )


def test_pareto_frontier_excludes_every_hard_gate_failure() -> None:
    admitted = _fitness("admitted", hard_gates_passed=True, accuracy=0.8, packet_bytes=100)
    failed_but_apparently_better = _fitness(
        "failed",
        hard_gates_passed=False,
        accuracy=1.0,
        packet_bytes=1,
    )

    assert pareto_frontier((failed_but_apparently_better, admitted)) == (admitted,)
    assert pareto_frontier((failed_but_apparently_better,)) == ()


def test_activation_requires_registry_owned_gate_and_current_parent_lineage() -> None:
    root = _representation("root")
    child = _representation("child", parent_id="root", version=2)
    wrong_lineage = _representation("wrong-lineage", parent_id="root", version=2)
    registry = _registry()
    for representation in (root, child, wrong_lineage):
        registry.register(representation)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="direct activation is forbidden"):
        registry.activate(
            "child",
            _decision(
                "root",
                "child",
                rollback_verified=False,
                parent_hash=root.content_hash,
                candidate_hash=child.content_hash,
            ),
        )
    with pytest.raises(ResearchInvariantError, match="direct activation is forbidden"):
        registry.activate("child", _decision("someone-else", "child"))

    decision, event = registry.evaluate_and_activate("child")
    assert decision.status == "promote"
    assert event is not None
    rejection, rejected_event = registry.evaluate_and_activate("wrong-lineage")
    assert rejection.reason == "candidate_parent_mismatch"
    assert rejected_event is None


def test_activation_requires_a_matching_promotion_decision() -> None:
    root = _representation("root")
    child = _representation("child", parent_id="root", version=2)
    registry = _registry()
    registry.register(root)
    registry.register(child)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="direct activation is forbidden"):
        registry.activate("child", _decision("root", "different-candidate"))
    with pytest.raises(ResearchInvariantError, match="direct activation is forbidden"):
        registry.activate("child", _decision("root", "child", status="reject"))


def test_rollback_rejects_registered_but_never_active_target() -> None:
    root = _representation("root")
    approved = _representation("approved", parent_id="root", version=2)
    unapproved = _representation("unapproved", parent_id="root", version=2)
    registry = _registry()
    for representation in (root, approved, unapproved):
        registry.register(representation)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="active previously"):
        registry.rollback("unapproved", reason="must-not-authorize-by-registration")

    decision, event = registry.evaluate_and_activate("approved")
    assert decision.status == "promote"
    assert event is not None
    registry.rollback("root", reason="verified-regression")
    assert registry.active_id == "root"
    with pytest.raises(ResearchInvariantError, match="differ"):
        registry.rollback("root", reason="no-op")


class _NondeterministicParentSolver:
    """Parent result changes only on its protected replay."""

    def __init__(self) -> None:
        self.solver_id = "nondeterministic-test-solver"
        self.configuration_hash = sha256_text("nondeterministic-test-solver-v1")
        self._parent_calls = 0

    def solve(self, view, query):
        if view.representation_id == "parent":
            self._parent_calls += 1
            answer = (
                "fail"
                if query.query_id == "new" or self._parent_calls == 3
                else "pass"
            )
        else:
            answer = "pass"
        return SolverOutcome(
            query_id=query.query_id,
            status=SolveStatus.COMPLETE,
            answer=answer,
            used_component_ids=(),
            evidence_observation_ids=(),
        )


def test_repair_gate_fails_closed_when_parent_re_evaluation_changes() -> None:
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    evaluator = RepresentationEvaluator(_MarkerDecompressor(), _NondeterministicParentSolver())

    decision = RepresentationRepairGate(evaluator).evaluate(
        parent,
        candidate,
        protected_tasks=PROTECTED_TASKS,
        new_tasks=NEW_TASKS,
        protocol_hash=PROTOCOL_HASH,
    )

    assert decision.status == "reject"
    assert decision.reason == "parent_replay_nondeterministic"
    assert not decision.rollback_verified
