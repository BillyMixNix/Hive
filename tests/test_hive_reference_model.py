from __future__ import annotations

from dataclasses import replace

import pytest

from hive_reference.demo import build_demo_ledger, build_demo_tasks, run_demo
from hive_reference.model import (
    Authority,
    CanonicalEvent,
    ClaimRevision,
    DecisionStatus,
    EffectOp,
    EvidenceBasis,
    EvidenceRef,
    EventLedger,
    FactKey,
    ModelInvariantError,
    Observation,
    Requirement,
    RequirementOp,
    StateEffect,
    TemporalStatus,
    TruthStatus,
)
from hive_reference.representation import (
    DeterministicReferenceSolver,
    ReferenceCompressor,
    RepresentationAblator,
    RepresentationEvaluator,
    SelectiveDecompressor,
    SolveStatus,
    make_causal_rule_component,
)


def _observation(name: str, record: int) -> Observation:
    return Observation.create(
        f"o_{name}",
        "test_registry",
        record,
        {"text": name},
        provenance=("test_fixture",),
    )


def _event(
    name: str,
    key: FactKey,
    value,
    *,
    observation: Observation,
    effective: int,
    record: int,
    basis: EvidenceBasis = EvidenceBasis.OBSERVED,
    truth: TruthStatus = TruthStatus.ACCEPTED,
    authority: Authority = Authority.CANONICAL,
    expected=None,
    requirements=(),
    dependencies=(),
    supersedes=(),
) -> CanonicalEvent:
    evidence = EvidenceRef.from_observation(observation)
    claim = ClaimRevision(
        claim_id=f"c_{name}",
        key=key,
        value=value,
        basis=basis,
        truth=truth,
        authority=authority,
        valid_from=effective,
        valid_to=None,
        recorded_at=record,
        evidence=(evidence,),
        supersedes_claim_ids=tuple(supersedes),
        confidence=1.0,
    )
    return CanonicalEvent(
        event_id=f"e_{name}",
        event_type=name,
        effective_time=effective,
        recorded_at=record,
        entities=(key.subject,),
        requirements=tuple(requirements),
        effects=(StateEffect(claim.claim_id, key, EffectOp.SET, value, expected),),
        claims=(claim,),
        causal_parents=(),
        hard_dependencies=tuple(dependencies),
        evidence=(evidence,),
    )


def _ledger_with(events: list[tuple[Observation, CanonicalEvent]]) -> EventLedger:
    ledger = EventLedger()
    for observation, _ in events:
        ledger.append_observation(observation)
    for _, event in events:
        ledger.append_event(event)
    return ledger


def _demo_representation():
    ledger, refs = build_demo_ledger()
    rule = make_causal_rule_component(
        component_id="component:rule:containment_owner_v1",
        keys=(FactKey("gem", "inside"), FactKey("chest", "owner")),
        rule_id="containment_owner_v1",
        rule="contained item inherits effective owner from container",
        source_event_ids=("e_inside", "e_owner_ari"),
        evidence=(refs["o_inside"], refs["o_owner"]),
        available_from_record=11,
    )
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="test-full",
        extra_components=(rule,),
    )
    return ledger, representation


def test_demo_separates_plan_intent_current_state_and_dispute() -> None:
    ledger, _ = build_demo_ledger()
    t2 = ledger.replay(valid_at=2)
    t4 = ledger.replay(valid_at=4)

    assert t2.value(FactKey("chest", "owner")) == "Ari"
    assert t4.value(FactKey("chest", "owner")) == "Cato"
    assert t4.value(FactKey("ari", "intends_transfer_chest_to")) == "Bea"
    plan = next(item for item in ledger.decisions if item.event_id == "e_plan_transfer")
    assert plan.status is DecisionStatus.REJECT
    assert plan.reason == "non_promotable_basis"
    assert len(t4.contradictions) == 1
    assert t4.contradictions[0].resolution == "authority"
    assert set(t4.contradictions[0].claim_ids) == {"c_disputed_bea", "c_owner_cato"}


def test_prediction_and_high_confidence_do_not_promote() -> None:
    key = FactKey("vault", "open")
    observation = _observation("prediction", 1)
    event = _event(
        "prediction",
        key,
        True,
        observation=observation,
        effective=5,
        record=10,
        basis=EvidenceBasis.PREDICTED,
        authority=Authority.MODEL,
    )
    ledger = _ledger_with([(observation, event)])
    assert ledger.replay(valid_at=99).value(key) is None
    assert ledger.decisions[0].status is DecisionStatus.REJECT


def test_future_effect_and_late_evidence_are_bitemporal() -> None:
    key = FactKey("seal", "owner")
    first_o = _observation("first", 1)
    late_o = _observation("late", 2)
    first = _event("first", key, "Ari", observation=first_o, effective=2, record=10)
    late = _event(
        "late",
        key,
        "Bea",
        observation=late_o,
        effective=2,
        record=20,
        expected="Ari",
        supersedes=("c_first",),
    )
    ledger = _ledger_with([(first_o, first), (late_o, late)])

    assert ledger.replay(valid_at=1, known_at=99).value(key) is None
    assert ledger.replay(valid_at=2, known_at=15).value(key) == "Ari"
    assert ledger.replay(valid_at=2, known_at=25).value(key) == "Bea"
    assert ledger.temporal_status("c_first", valid_at=2, known_at=15) is TemporalStatus.CURRENT
    assert ledger.temporal_status("c_first", valid_at=2, known_at=25) is TemporalStatus.SUPERSEDED
    assert ledger.temporal_status("c_late", valid_at=2, known_at=15) is TemporalStatus.FUTURE


def test_same_time_unordered_writes_are_explicit_conflict_and_order_independent() -> None:
    key = FactKey("seal", "owner")
    a_o, b_o = _observation("a", 1), _observation("b", 2)
    a = _event("a", key, "Ari", observation=a_o, effective=1, record=10)
    b = _event("b", key, "Bea", observation=b_o, effective=1, record=11)
    forward = _ledger_with([(a_o, a), (b_o, b)])

    reverse = EventLedger()
    reverse.append_observation(b_o)
    reverse.append_observation(a_o)
    reverse.append_event(b)
    reverse.append_event(a)
    left = forward.replay(valid_at=1)
    right = reverse.replay(valid_at=1)

    assert left.value(key) is None
    assert left.ambiguous_keys == (key,)
    assert left.digest == right.digest
    assert left.contradictions[0].resolution == "unresolved"


def test_same_time_explicit_dependency_permits_deterministic_transition() -> None:
    key = FactKey("seal", "owner")
    a_o, b_o = _observation("a", 1), _observation("b", 2)
    a = _event("a", key, "Ari", observation=a_o, effective=1, record=10)
    b = _event(
        "b",
        key,
        "Bea",
        observation=b_o,
        effective=1,
        record=11,
        expected="Ari",
        dependencies=("e_a",),
        supersedes=("c_a",),
    )
    ledger = _ledger_with([(a_o, a), (b_o, b)])
    state = ledger.replay(valid_at=1)
    assert state.value(key) == "Bea"
    assert not state.ambiguous_keys
    assert [item.before for item in state.history] == [None, "Ari"]


def test_failed_precondition_rejects_multi_effect_event_atomically() -> None:
    owner = FactKey("seal", "owner")
    location = FactKey("seal", "location")
    base_o, move_o = _observation("base", 1), _observation("move", 2)
    base = _event("base", owner, "Ari", observation=base_o, effective=1, record=10)
    evidence = EvidenceRef.from_observation(move_o)
    claims = (
        ClaimRevision("c_move_owner", owner, "Bea", EvidenceBasis.OBSERVED, TruthStatus.ACCEPTED, Authority.CANONICAL, 2, None, 20, (evidence,)),
        ClaimRevision("c_move_location", location, "Dock", EvidenceBasis.OBSERVED, TruthStatus.ACCEPTED, Authority.CANONICAL, 2, None, 20, (evidence,)),
    )
    move = CanonicalEvent(
        "e_move",
        "move",
        2,
        20,
        ("seal",),
        (Requirement(owner, RequirementOp.EQ, "Cira"),),
        (
            StateEffect("c_move_owner", owner, EffectOp.SET, "Bea", "Cira"),
            StateEffect("c_move_location", location, EffectOp.SET, "Dock"),
        ),
        claims,
        (),
        (),
        (evidence,),
    )
    ledger = _ledger_with([(base_o, base), (move_o, move)])
    state = ledger.replay(valid_at=2)
    assert state.value(owner) == "Ari"
    assert state.value(location) is None
    assert next(item for item in state.decisions if item.event_id == "e_move").reason == "precondition_failed"


def test_missing_dependency_cycle_future_dependency_and_tampered_evidence_fail_closed() -> None:
    key = FactKey("x", "value")
    observation = _observation("one", 1)
    event = _event("one", key, 1, observation=observation, effective=1, record=10, dependencies=("missing",))
    ledger = EventLedger()
    ledger.append_observation(observation)
    with pytest.raises(ModelInvariantError, match="unknown event dependency"):
        ledger.append_event(event)

    with pytest.raises(ModelInvariantError, match="hash"):
        Observation(
            observation.observation_id,
            observation.source_id,
            observation.recorded_at,
            observation.payload_json,
            "0" * 64,
            observation.provenance,
        )


def test_unregistered_or_unmet_inference_cannot_promote() -> None:
    base_key = FactKey("x", "observed")
    derived_key = FactKey("x", "derived")
    base_o, inferred_o = _observation("base", 1), _observation("inferred", 2)
    base = _event("base", base_key, True, observation=base_o, effective=1, record=10)
    evidence = EvidenceRef.from_observation(inferred_o)
    claim = ClaimRevision(
        "c_inferred",
        derived_key,
        True,
        EvidenceBasis.INFERRED,
        TruthStatus.ACCEPTED,
        Authority.DERIVED,
        2,
        None,
        20,
        (evidence,),
        depends_on_claim_ids=("c_base",),
        derivation_rule_id="rule_v1",
    )
    event = CanonicalEvent(
        "e_inferred",
        "inference",
        2,
        20,
        ("x",),
        (),
        (StateEffect("c_inferred", derived_key, EffectOp.SET, True),),
        (claim,),
        (),
        (),
        (evidence,),
    )
    unregistered = _ledger_with([(base_o, base), (inferred_o, event)])
    assert unregistered.replay(valid_at=2).value(derived_key) is None

    from hive_reference.model import AuthorityPolicy

    registered = EventLedger(AuthorityPolicy(("rule_v1",)))
    registered.append_observation(base_o)
    registered.append_observation(inferred_o)
    registered.append_event(base)
    registered.append_event(event)
    assert registered.replay(valid_at=2).value(derived_key) is True


def test_counterfactual_propagates_dependency_without_mutating_canonical_history() -> None:
    ledger, _ = build_demo_ledger()
    before = ledger.digest
    branch = ledger.counterfactual(valid_at=4, exclude_event_ids=("e_owner_ari",))
    assert branch.noncanonical
    assert branch.value(FactKey("chest", "owner")) is None
    assert ledger.digest == before


def test_compression_decompression_and_ablation_are_closed_and_provenance_bearing() -> None:
    ledger, representation = _demo_representation()
    tasks = build_demo_tasks(ledger.head_record_seq)
    evaluator = RepresentationEvaluator(SelectiveDecompressor(), DeterministicReferenceSolver())
    result = evaluator.evaluate(representation, tasks)
    assert result.all_passed
    assert all(outcome.evidence_observation_ids for outcome in result.outcomes)

    without_rule = representation.subset(
        item.component_id
        for item in representation.components
        if item.component_id != "component:rule:containment_owner_v1"
    )
    missing_rule_result = evaluator.evaluate(without_rule, tasks[:2])
    assert not missing_rule_result.all_passed
    assert all(item.status is SolveStatus.INCOMPLETE for item in missing_rule_result.outcomes)

    report = RepresentationAblator(evaluator, exact_limit=12).minimize(representation, tasks)
    assert report.algorithm == "exact_subset_minimum"
    assert "component:event:e_inside" in report.singleton_essential
    assert "component:event:e_color" in report.singleton_redundant
    assert report.minimum_component_count == 6


def test_demo_is_byte_deterministic_and_scoped() -> None:
    first = run_demo()
    second = run_demo()
    assert first == second
    assert first["model_calls"] == 0
    assert first["evaluation"]["full"]["all_passed"] is True
    assert first["evaluation"]["lossy"]["all_passed"] is False
    assert first["repair"]["migration"]["status"] == "promote"
    assert first["repair"]["rollback_hash_matches"] is True
    assert first["repair"]["representation_learning_demonstrated"] is False
