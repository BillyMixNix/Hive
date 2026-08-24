from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from hive_reference.model import (
    Authority,
    CanonicalEvent,
    ClaimRevision,
    EffectOp,
    EvidenceBasis,
    EvidenceRef,
    EventLedger,
    FactKey,
    Observation,
    Requirement,
    RequirementOp,
    StateEffect,
    TruthStatus,
)
from hive_reference.representation import (
    ConceptDefinition,
    DeterministicReferenceSolver,
    ReferenceCompressor,
    RepresentationInvariantError,
    SelectiveDecompressor,
    SolveStatus,
    TaskKind,
    TaskQuery,
    make_causal_rule_component,
)


def _observation(name: str, recorded_at: int) -> Observation:
    return Observation.create(
        f"o_{name}",
        "dependency_provenance_fixture",
        recorded_at,
        {"name": name},
        provenance=("deterministic_test",),
    )


def _event(
    name: str,
    key: FactKey,
    value,
    *,
    observation: Observation,
    effective_time: int,
    recorded_at: int,
    requirements: tuple[Requirement, ...] = (),
) -> CanonicalEvent:
    evidence = EvidenceRef.from_observation(observation)
    claim = ClaimRevision(
        claim_id=f"c_{name}",
        key=key,
        value=value,
        basis=EvidenceBasis.OBSERVED,
        truth=TruthStatus.ACCEPTED,
        authority=Authority.CANONICAL,
        valid_from=effective_time,
        valid_to=None,
        recorded_at=recorded_at,
        evidence=(evidence,),
    )
    return CanonicalEvent(
        event_id=f"e_{name}",
        event_type="test_transition",
        effective_time=effective_time,
        recorded_at=recorded_at,
        entities=(key.subject,),
        requirements=requirements,
        effects=(StateEffect(claim.claim_id, key, EffectOp.SET, value),),
        claims=(claim,),
        causal_parents=(),
        hard_dependencies=(),
        evidence=(evidence,),
    )


def _ledger(*pairs: tuple[Observation, CanonicalEvent]) -> EventLedger:
    ledger = EventLedger()
    for observation, _ in pairs:
        ledger.append_observation(observation)
    for _, event in pairs:
        ledger.append_event(event)
    return ledger


def _base_ledger() -> tuple[EventLedger, Observation, CanonicalEvent]:
    key = FactKey("x", "ready")
    observation = _observation("x", 1)
    event = _event(
        "x",
        key,
        True,
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    return _ledger((observation, event)), observation, event


def _rule(
    observation: Observation,
    *,
    available_from_record: int = 10,
):
    return make_causal_rule_component(
        component_id="component:rule:x_ready",
        keys=(FactKey("x", "ready"),),
        rule_id="x_ready_v1",
        rule="x is ready when the cited observation establishes it",
        source_event_ids=("e_x",),
        evidence=(EvidenceRef.from_observation(observation),),
        available_from_record=available_from_record,
    )


def test_decompression_follows_dynamic_requirement_support_without_explicit_edge() -> None:
    x = FactKey("x", "ready")
    y = FactKey("y", "status")
    x_observation = _observation("x", 1)
    y_observation = _observation("y", 2)
    x_event = _event(
        "x",
        x,
        True,
        observation=x_observation,
        effective_time=1,
        recorded_at=10,
    )
    y_event = _event(
        "y",
        y,
        "admitted",
        observation=y_observation,
        effective_time=2,
        recorded_at=20,
        requirements=(Requirement(x, RequirementOp.EQ, True),),
    )
    assert y_event.hard_dependencies == ()
    ledger = _ledger((x_observation, x_event), (y_observation, y_event))
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="dynamic-requirement-support",
    )
    query = TaskQuery("q_y", TaskKind.VALUE_AT, (y,), 2, 20)

    view = SelectiveDecompressor().decompress(representation, query)
    outcome = DeterministicReferenceSolver().solve(view, query)

    assert view.completeness is SolveStatus.COMPLETE
    assert set(view.selected_component_ids) == {
        "component:event:e_x",
        "component:event:e_y",
    }
    assert outcome.status is SolveStatus.COMPLETE
    assert outcome.answer == ledger.replay(valid_at=2, known_at=20).value(y) == "admitted"


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda component: replace(component, source_event_ids=("e_missing",)), "unknown source event"),
        (lambda component: replace(component, source_claim_ids=("c_missing",)), "unknown source claim"),
        (
            lambda component: replace(
                component,
                evidence=(
                    replace(component.evidence[0], observation_id="o_missing"),
                ),
            ),
            "unknown evidence observation",
        ),
        (
            lambda component: replace(
                component,
                evidence=(
                    replace(component.evidence[0], source_sha256="0" * 64),
                ),
            ),
            "identity or hash",
        ),
        (lambda component: replace(component, available_from_record=9), "latest cited source"),
    ),
)
def test_extra_component_lineage_fails_closed(mutation, message: str) -> None:
    ledger, observation, _ = _base_ledger()
    forged = mutation(_rule(observation))

    with pytest.raises(RepresentationInvariantError, match=message):
        ReferenceCompressor().compress(
            ledger,
            representation_id="forged-lineage",
            extra_components=(forged,),
        )


def test_extra_component_accepts_exact_ledger_lineage_and_claim_availability() -> None:
    ledger, observation, _ = _base_ledger()
    component = replace(_rule(observation), source_claim_ids=("c_x",))

    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="verified-lineage",
        extra_components=(component,),
    )

    assert component.component_id in {
        item.component_id for item in representation.components
    }


def test_real_but_unrelated_evidence_cannot_be_laundered_as_component_lineage() -> None:
    ledger, observation, _ = _base_ledger()
    unrelated = _observation("unrelated", 2)
    ledger.append_observation(unrelated)
    component = replace(
        _rule(observation),
        evidence=(EvidenceRef.from_observation(unrelated),),
    )

    with pytest.raises(RepresentationInvariantError, match="not attached"):
        ReferenceCompressor().compress(
            ledger,
            representation_id="unrelated-evidence",
            extra_components=(component,),
        )


def test_rule_and_concept_builders_require_explicit_availability() -> None:
    assert (
        inspect.signature(make_causal_rule_component)
        .parameters["available_from_record"]
        .default
        is inspect.Parameter.empty
    )
    assert (
        inspect.signature(ConceptDefinition.to_component)
        .parameters["available_from_record"]
        .default
        is inspect.Parameter.empty
    )
