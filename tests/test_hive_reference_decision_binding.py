from __future__ import annotations

from dataclasses import replace

import pytest

from hive_reference.model import sha256_text
from hive_reference.representation import (
    CostBreakdown,
    DeterministicReferenceSolver,
    OriginKind,
    OriginManifest,
    RepresentationEvaluator,
    RepresentationRootCommitment,
    RepresentationVersion,
    SelectiveDecompressor,
    TaskExpectation,
    TaskKind,
    TaskQuery,
    ValidationStatus,
)
from hive_reference.research import (
    MigrationDecision,
    RepresentationRegistry,
    RepresentationRepairGate,
    ResearchInvariantError,
)


def _representation(
    representation_id: str,
    *,
    parent_id: str | None = None,
    version: int = 1,
    schema_id: str = "schema-v1",
) -> RepresentationVersion:
    manifest_hash = RepresentationVersion.compute_source_component_manifest_hash(())
    return RepresentationVersion(
        representation_id=representation_id,
        family_id="decision-binding-family",
        version=version,
        parent_id=parent_id,
        source_ledger_hash="ledger",
        codec_id="codec",
        schema_id=schema_id,
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


def _promotion(parent: RepresentationVersion, candidate: RepresentationVersion) -> MigrationDecision:
    return MigrationDecision.from_content(
        parent_representation_id=parent.representation_id,
        candidate_representation_id=candidate.representation_id,
        parent_representation_hash=parent.content_hash,
        candidate_representation_hash=candidate.content_hash,
        protocol_hash=sha256_text("protocol"),
        evaluator_hash=sha256_text("evaluator"),
        parent_outcome_hash=sha256_text("parent-outcome"),
        candidate_outcome_hash=sha256_text("candidate-outcome"),
        status="promote",
        reason="test",
        rollback_verified=True,
        gate_id=RepresentationRepairGate.gate_id,
        protected_task_manifest_hash=sha256_text("protected"),
        new_task_manifest_hash=sha256_text("new"),
        cost_ceiling_hash=sha256_text("cost"),
    )


def _task(query_id: str) -> TaskExpectation:
    return TaskExpectation(
        query=TaskQuery(query_id, TaskKind.VALUE_AT, (), 0, 0),
        expected_answer=None,
    )


def _registry() -> RepresentationRegistry:
    root = RepresentationRootCommitment.from_trusted_representation(
        _representation("root")
    )
    evaluator = RepresentationEvaluator(
        SelectiveDecompressor((root,)),
        DeterministicReferenceSolver(),
    )
    return RepresentationRegistry(
        gate=RepresentationRepairGate(evaluator),
        protected_tasks=(_task("protected"),),
        new_tasks=(_task("new"),),
        protocol_hash=sha256_text("decision-binding-protocol"),
    )


def test_registration_rejects_candidate_incompatible_with_parent_content() -> None:
    evaluated_parent = _representation("root", schema_id="evaluated-schema")
    registered_parent = replace(evaluated_parent, schema_id="changed-after-evaluation")
    candidate = _representation("child", parent_id="root", version=2)
    decision = _promotion(evaluated_parent, candidate)
    registry = _registry()
    registry.register(registered_parent)
    with pytest.raises(ResearchInvariantError, match="schema_id_mismatch"):
        registry.register(candidate)
    assert decision.gate_id == RepresentationRepairGate.gate_id


def test_activation_rejects_decision_evaluated_against_different_candidate_content() -> None:
    parent = _representation("root")
    evaluated_candidate = _representation(
        "child", parent_id="root", version=2, schema_id="evaluated-schema"
    )
    registered_candidate = replace(
        evaluated_candidate,
        schema_id=parent.schema_id,
        cost=replace(evaluated_candidate.cost, input_tokens=1),
    )
    decision = _promotion(parent, evaluated_candidate)
    registry = _registry()
    registry.register(parent)
    registry.register(registered_candidate)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="direct activation is forbidden"):
        registry.activate("child", decision)


def test_direct_activation_rejects_even_exact_caller_constructed_decision() -> None:
    parent = _representation("root")
    candidate = _representation("child", parent_id="root", version=2)
    registry = _registry()
    registry.register(parent)
    registry.register(candidate)
    registry.bootstrap("root")

    decision = _promotion(parent, candidate)
    assert decision.gate_id == RepresentationRepairGate.gate_id
    with pytest.raises(ResearchInvariantError, match="direct activation is forbidden"):
        registry.activate("child", decision)
    assert registry.active is parent
