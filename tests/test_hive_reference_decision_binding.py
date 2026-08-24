from __future__ import annotations

from dataclasses import replace

import pytest

from hive_reference.representation import (
    CostBreakdown,
    OriginKind,
    OriginManifest,
    RepresentationVersion,
    ValidationStatus,
)
from hive_reference.research import (
    MigrationDecision,
    RepresentationRegistry,
    ResearchInvariantError,
)


def _representation(
    representation_id: str,
    *,
    parent_id: str | None = None,
    version: int = 1,
    schema_id: str = "schema-v1",
) -> RepresentationVersion:
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
        cost=CostBreakdown(),
    )


def _promotion(parent: RepresentationVersion, candidate: RepresentationVersion) -> MigrationDecision:
    return MigrationDecision(
        decision_id="migration:test",
        parent_representation_id=parent.representation_id,
        candidate_representation_id=candidate.representation_id,
        parent_representation_hash=parent.content_hash,
        candidate_representation_hash=candidate.content_hash,
        protocol_hash="protocol",
        evaluator_hash="evaluator",
        parent_outcome_hash="parent-outcome",
        candidate_outcome_hash="candidate-outcome",
        status="promote",
        reason="test",
        rollback_verified=True,
    )


def test_activation_rejects_decision_evaluated_against_different_parent_content() -> None:
    evaluated_parent = _representation("root", schema_id="evaluated-schema")
    registered_parent = replace(evaluated_parent, schema_id="changed-after-evaluation")
    candidate = _representation("child", parent_id="root", version=2)
    decision = _promotion(evaluated_parent, candidate)
    registry = RepresentationRegistry()
    registry.register(registered_parent)
    registry.register(candidate)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="parent content"):
        registry.activate("child", decision)


def test_activation_rejects_decision_evaluated_against_different_candidate_content() -> None:
    parent = _representation("root")
    evaluated_candidate = _representation(
        "child", parent_id="root", version=2, schema_id="evaluated-schema"
    )
    registered_candidate = replace(
        evaluated_candidate,
        schema_id="changed-after-evaluation",
    )
    decision = _promotion(parent, evaluated_candidate)
    registry = RepresentationRegistry()
    registry.register(parent)
    registry.register(registered_candidate)
    registry.bootstrap("root")

    with pytest.raises(ResearchInvariantError, match="candidate content"):
        registry.activate("child", decision)


def test_activation_accepts_the_exact_evaluated_parent_and_candidate_content() -> None:
    parent = _representation("root")
    candidate = _representation("child", parent_id="root", version=2)
    registry = RepresentationRegistry()
    registry.register(parent)
    registry.register(candidate)
    registry.bootstrap("root")

    event = registry.activate("child", _promotion(parent, candidate))

    assert event.new_active_id == "child"
    assert registry.active is candidate
