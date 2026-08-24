from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from hive_reference.representation import (
    CostBreakdown,
    EvaluationSummary,
    OriginKind,
    OriginManifest,
    RepresentationVersion,
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
        cost=CostBreakdown(),
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
    return MigrationDecision(
        decision_id=f"decision:{parent_id}:{candidate_id}",
        parent_representation_id=parent_id,
        candidate_representation_id=candidate_id,
        parent_representation_hash=parent_hash or _representation(parent_id).content_hash,
        candidate_representation_hash=candidate_hash
        or _representation(candidate_id, parent_id=parent_id, version=2).content_hash,
        protocol_hash="protocol",
        evaluator_hash="evaluator",
        parent_outcome_hash="parent-outcome",
        candidate_outcome_hash="candidate-outcome",
        status=status,
        reason="test",
        rollback_verified=rollback_verified,
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


def test_activation_requires_current_parent_lineage_and_verified_rollback() -> None:
    root = _representation("root")
    child = _representation("child", parent_id="root", version=2)
    wrong_lineage = _representation("wrong-lineage", parent_id="root", version=2)
    registry = RepresentationRegistry()
    for representation in (root, child, wrong_lineage):
        registry.register(representation)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="verified deterministic rollback"):
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
    with pytest.raises(ResearchInvariantError, match="decision parent"):
        registry.activate("child", _decision("someone-else", "child"))

    registry.activate(
        "child",
        _decision(
            "root",
            "child",
            parent_hash=root.content_hash,
            candidate_hash=child.content_hash,
        ),
    )
    with pytest.raises(ResearchInvariantError, match="descend directly"):
        registry.activate("wrong-lineage", _decision("child", "wrong-lineage"))


def test_activation_requires_a_matching_promotion_decision() -> None:
    root = _representation("root")
    child = _representation("child", parent_id="root", version=2)
    registry = RepresentationRegistry()
    registry.register(root)
    registry.register(child)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="matching promotion"):
        registry.activate("child", _decision("root", "different-candidate"))
    with pytest.raises(ResearchInvariantError, match="matching promotion"):
        registry.activate("child", _decision("root", "child", status="reject"))


def test_rollback_rejects_registered_but_never_active_target() -> None:
    root = _representation("root")
    approved = _representation("approved", parent_id="root", version=2)
    unapproved = _representation("unapproved", parent_id="root", version=2)
    registry = RepresentationRegistry()
    for representation in (root, approved, unapproved):
        registry.register(representation)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="active previously"):
        registry.rollback("unapproved", reason="must-not-authorize-by-registration")

    registry.activate(
        "approved",
        _decision(
            "root",
            "approved",
            parent_hash=root.content_hash,
            candidate_hash=approved.content_hash,
        ),
    )
    registry.rollback("root", reason="verified-regression")
    assert registry.active_id == "root"
    with pytest.raises(ResearchInvariantError, match="differ"):
        registry.rollback("root", reason="no-op")


class _NondeterministicParentEvaluator:
    """Minimal adversary whose parent result changes only on protected replay."""

    def __init__(self) -> None:
        self.solver = SimpleNamespace(solver_id="nondeterministic-test-solver")
        self._parent_calls = 0

    def evaluate(self, representation, tasks):
        if representation.representation_id == "parent":
            self._parent_calls += 1
            passed = len(tasks) if self._parent_calls != 3 else 0
        else:
            passed = len(tasks)
        return EvaluationSummary(
            representation_id=representation.representation_id,
            all_passed=passed == len(tasks),
            passed=passed,
            total=len(tasks),
            outcomes=(),
        )


def test_repair_gate_fails_closed_when_parent_re_evaluation_changes() -> None:
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    protected = (SimpleNamespace(),)
    new = (SimpleNamespace(),)

    decision = RepresentationRepairGate(_NondeterministicParentEvaluator()).evaluate(
        parent,
        candidate,
        protected_tasks=protected,
        new_tasks=new,
        protocol_hash="fixed",
    )

    assert decision.status == "reject"
    assert decision.reason == "parent_replay_nondeterministic"
    assert not decision.rollback_verified
