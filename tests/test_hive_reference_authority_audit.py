from __future__ import annotations

from dataclasses import replace

import pytest

from hive_reference.model import (
    Authority,
    AuthorityPolicy,
    CanonicalEvent,
    ClaimRevision,
    DecisionStatus,
    EdgeKind,
    EffectOp,
    EvidenceBasis,
    EvidenceRef,
    EventLedger,
    FactKey,
    ModelInvariantError,
    Observation,
    PromotionDecision,
    Requirement,
    RequirementOp,
    StateEffect,
    TemporalStatus,
    TruthStatus,
    canonical_json,
)


def _observation(name: str, recorded_at: int = 0) -> Observation:
    return Observation.create(
        f"o_{name}",
        "authority_audit",
        recorded_at,
        {"name": name},
        provenance=("adversarial_test",),
    )


def _event(
    name: str,
    key: FactKey,
    value,
    *,
    observation: Observation,
    effective_time: int,
    recorded_at: int,
    op: EffectOp = EffectOp.SET,
    truth: TruthStatus = TruthStatus.ACCEPTED,
    valid_to: int | None = None,
    expected_previous=None,
    expected_previous_specified: bool = False,
    increment_by=None,
    requirements: tuple[Requirement, ...] = (),
    hard_dependencies: tuple[str, ...] = (),
    causal_parents: tuple[str, ...] = (),
    claim_dependencies: tuple[str, ...] = (),
    supersedes: tuple[str, ...] = (),
    basis: EvidenceBasis = EvidenceBasis.OBSERVED,
    authority: Authority = Authority.CANONICAL,
    event_evidence: tuple[EvidenceRef, ...] | None = None,
    claim_evidence: tuple[EvidenceRef, ...] | None = None,
) -> CanonicalEvent:
    evidence = EvidenceRef.from_observation(observation)
    claim = ClaimRevision(
        claim_id=f"c_{name}",
        key=key,
        value=value,
        basis=basis,
        truth=truth,
        authority=authority,
        valid_from=effective_time,
        valid_to=valid_to,
        recorded_at=recorded_at,
        evidence=claim_evidence or (evidence,),
        depends_on_claim_ids=claim_dependencies,
        supersedes_claim_ids=supersedes,
    )
    return CanonicalEvent(
        event_id=f"e_{name}",
        event_type="authority_audit",
        effective_time=effective_time,
        recorded_at=recorded_at,
        entities=(key.subject,),
        requirements=requirements,
        effects=(
            StateEffect(
                claim.claim_id,
                key,
                op,
                value,
                expected_previous,
                increment_by,
                expected_previous_specified,
            ),
        ),
        claims=(claim,),
        causal_parents=causal_parents,
        hard_dependencies=hard_dependencies,
        evidence=event_evidence or (evidence,),
        edges=tuple((EdgeKind.CAUSE, item) for item in causal_parents),
    )


def _append(
    ledger: EventLedger,
    observations: tuple[Observation, ...],
    events: tuple[CanonicalEvent, ...],
) -> None:
    for observation in observations:
        ledger.append_observation(observation)
    for event in events:
        ledger.append_event(event)


def test_rejected_causal_parent_gates_child_but_informational_edge_does_not() -> None:
    parent_key = FactKey("permit", "planned")
    child_key = FactKey("sale", "status")
    informational_key = FactKey("note", "status")
    parent_o = _observation("rejected_causal_parent", 1)
    child_o = _observation("causal_child", 2)
    info_o = _observation("informational_child", 3)
    parent = _event(
        "rejected_causal_parent",
        parent_key,
        True,
        observation=parent_o,
        effective_time=1,
        recorded_at=10,
        basis=EvidenceBasis.PLANNED,
        authority=Authority.MODEL,
    )
    child = _event(
        "causal_child",
        child_key,
        "completed",
        observation=child_o,
        effective_time=2,
        recorded_at=20,
        causal_parents=(parent.event_id,),
    )
    informational = replace(
        _event(
            "informational_child",
            informational_key,
            "recorded",
            observation=info_o,
            effective_time=2,
            recorded_at=30,
        ),
        edges=((EdgeKind.CAUSE, parent.event_id),),
    )
    ledger = EventLedger()
    _append(ledger, (parent_o, child_o, info_o), (parent, child, informational))

    snapshot = ledger.replay(valid_at=2)
    decisions = {item.event_id: item for item in snapshot.decisions}
    assert decisions[parent.event_id].reason == "non_promotable_basis"
    assert decisions[child.event_id].reason == "missing_causal_parent"
    assert snapshot.value(child_key) is None
    assert decisions[informational.event_id].admitted is True
    assert snapshot.value(informational_key) == "recorded"


def test_null_state_requires_an_explicit_null_guard_to_replace() -> None:
    key = FactKey("nullable", "value")
    base_o = _observation("nullable_base", 1)
    blocked_o = _observation("nullable_blocked", 2)
    allowed_o = _observation("nullable_allowed", 2)
    base = _event(
        "nullable_base",
        key,
        None,
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    blocked = _event(
        "nullable_blocked",
        key,
        "B",
        observation=blocked_o,
        effective_time=2,
        recorded_at=20,
    )
    blocked_ledger = EventLedger()
    _append(blocked_ledger, (base_o, blocked_o), (base, blocked))
    blocked_snapshot = blocked_ledger.replay(valid_at=2)
    assert blocked_snapshot.cell(key) is not None
    assert blocked_snapshot.cell(key).source_claim_id == base.effects[0].claim_id
    assert {item.event_id: item.reason for item in blocked_snapshot.decisions}[
        blocked.event_id
    ] == "unlicensed_supersession"

    allowed = _event(
        "nullable_allowed",
        key,
        "B",
        observation=allowed_o,
        effective_time=2,
        recorded_at=20,
        expected_previous=None,
        expected_previous_specified=True,
    )
    allowed_ledger = EventLedger()
    _append(allowed_ledger, (base_o, allowed_o), (base, allowed))
    allowed_snapshot = allowed_ledger.replay(valid_at=2)
    assert allowed_snapshot.value(key) == "B"
    assert allowed_snapshot.cell(key).source_claim_id == allowed.effects[0].claim_id


def test_unguarded_delete_cannot_erase_existing_state() -> None:
    key = FactKey("artifact", "owner")
    base_o = _observation("delete_base", 1)
    delete_o = _observation("delete_unlicensed", 2)
    base = _event(
        "delete_base",
        key,
        "A",
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    deletion = _event(
        "delete_unlicensed",
        key,
        None,
        observation=delete_o,
        effective_time=2,
        recorded_at=20,
        op=EffectOp.DELETE,
    )
    ledger = EventLedger()
    _append(ledger, (base_o, delete_o), (base, deletion))

    snapshot = ledger.replay(valid_at=2)
    assert snapshot.value(key) == "A"
    assert {item.event_id: item.reason for item in snapshot.decisions}[
        deletion.event_id
    ] == "unlicensed_deletion"


def test_same_value_set_cannot_silently_change_expiry() -> None:
    key = FactKey("permit", "status")
    base_o = _observation("expiry_base", 1)
    shortening_o = _observation("expiry_shortening", 2)
    base = _event(
        "expiry_base",
        key,
        "active",
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    shortening = _event(
        "expiry_shortening",
        key,
        "active",
        observation=shortening_o,
        effective_time=2,
        recorded_at=20,
        valid_to=3,
    )
    ledger = EventLedger()
    _append(ledger, (base_o, shortening_o), (base, shortening))

    snapshot = ledger.replay(valid_at=4)
    assert snapshot.value(key) == "active"
    assert {item.event_id: item.reason for item in snapshot.decisions}[
        shortening.event_id
    ] == "unlicensed_supersession"


@pytest.mark.parametrize("transition_kind", ("set", "delete", "increment"))
def test_applied_guarded_transition_supersedes_replaced_claim(
    transition_kind: str,
) -> None:
    key = FactKey("counter", "value")
    base_value = 10
    base_o = _observation(f"lineage_base_{transition_kind}", 1)
    next_o = _observation(f"lineage_next_{transition_kind}", 2)
    base = _event(
        f"lineage_base_{transition_kind}",
        key,
        base_value,
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    if transition_kind == "set":
        next_event = _event(
            "lineage_next_set",
            key,
            12,
            observation=next_o,
            effective_time=2,
            recorded_at=20,
            expected_previous=10,
        )
    elif transition_kind == "delete":
        next_event = _event(
            "lineage_next_delete",
            key,
            None,
            observation=next_o,
            effective_time=2,
            recorded_at=20,
            op=EffectOp.DELETE,
            expected_previous=10,
        )
    else:
        next_event = _event(
            "lineage_next_increment",
            key,
            12,
            observation=next_o,
            effective_time=2,
            recorded_at=20,
            op=EffectOp.INCREMENT,
            expected_previous=10,
            increment_by=2,
        )
    ledger = EventLedger()
    _append(ledger, (base_o, next_o), (base, next_event))

    snapshot = ledger.replay(valid_at=2)
    assert {item.event_id: item.admitted for item in snapshot.decisions}[
        next_event.event_id
    ] is True
    assert any(
        item.source_event_id == next_event.event_id
        and item.replaced_claim_id == base.claims[0].claim_id
        for item in snapshot.history
    )
    assert ledger.temporal_status(
        base.claims[0].claim_id, valid_at=2
    ) is TemporalStatus.SUPERSEDED
    assert ledger.temporal_status(
        next_event.claims[0].claim_id, valid_at=2
    ) is TemporalStatus.CURRENT


@pytest.mark.parametrize(
    ("cell_value", "required_value", "op"),
    (
        (1, True, RequirementOp.EQ),
        (True, 1, RequirementOp.EQ),
        (1, True, RequirementOp.GTE),
    ),
)
def test_preconditions_use_type_sensitive_json_scalar_semantics(
    cell_value,
    required_value,
    op: RequirementOp,
) -> None:
    key = FactKey("typed", "value")
    result = FactKey("typed", "result")
    base_o = _observation(f"typed_base_{cell_value}_{required_value}_{op.value}", 1)
    child_o = _observation(f"typed_child_{cell_value}_{required_value}_{op.value}", 2)
    base = _event(
        f"typed_base_{cell_value}_{required_value}_{op.value}",
        key,
        cell_value,
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    child = _event(
        f"typed_child_{cell_value}_{required_value}_{op.value}",
        result,
        "incorrectly_admitted",
        observation=child_o,
        effective_time=2,
        recorded_at=20,
        requirements=(Requirement(key, op, required_value),),
    )
    ledger = EventLedger()
    _append(ledger, (base_o, child_o), (base, child))

    snapshot = ledger.replay(valid_at=2)
    assert snapshot.value(result) is None
    assert {item.event_id: item.reason for item in snapshot.decisions}[
        child.event_id
    ] == "precondition_failed"


def test_authority_policy_configuration_is_immutable_and_identity_is_derived() -> None:
    policy = AuthorityPolicy()
    original_id = policy.policy_id
    with pytest.raises((AttributeError, TypeError)):
        policy.registered_inference_rules = frozenset({"evil_rule"})
    assert policy.policy_id == original_id
    assert policy.registered_inference_rules == frozenset()


def test_all_model_enum_boundaries_reject_plain_strings() -> None:
    key = FactKey("enum", "boundary")
    observation = _observation("enum_boundary", 1)
    evidence = EvidenceRef.from_observation(observation)
    valid_claim = ClaimRevision(
        "c_enum",
        key,
        "value",
        EvidenceBasis.OBSERVED,
        TruthStatus.ACCEPTED,
        Authority.CANONICAL,
        1,
        None,
        10,
        (evidence,),
    )
    valid_event = CanonicalEvent(
        "e_enum",
        "enum",
        1,
        10,
        ("enum",),
        (),
        (StateEffect(valid_claim.claim_id, key, EffectOp.SET, "value"),),
        (valid_claim,),
        (),
        (),
        (evidence,),
    )

    with pytest.raises(ModelInvariantError, match="RequirementOp"):
        Requirement(key, "eq", "value")
    for field_name, bad_value in (
        ("basis", "observed"),
        ("truth", "accepted"),
        ("authority", "canonical"),
    ):
        with pytest.raises(ModelInvariantError):
            replace(valid_claim, **{field_name: bad_value})
    with pytest.raises(ModelInvariantError, match="EffectOp"):
        StateEffect(valid_claim.claim_id, key, "set", "value")
    with pytest.raises(ModelInvariantError, match="EdgeKind"):
        replace(valid_event, edges=(("cause", "e_parent"),))
    with pytest.raises(ModelInvariantError, match="DecisionStatus"):
        PromotionDecision(
            valid_event.event_id,
            "admit",
            "policy",
            "reason",
            "0" * 64,
            valid_event.content_hash,
        )

    ledger = EventLedger()
    ledger.append_observation(observation)
    ledger.append_event(valid_event)
    assert type(ledger.temporal_status(valid_claim.claim_id, valid_at=1)) is TemporalStatus


def test_canonical_json_orders_sets_but_preserves_sequence_order() -> None:
    assert canonical_json({"items": {"b", "a"}}) == '{"items":["a","b"]}'
    assert canonical_json({"items": frozenset((2, 1))}) == '{"items":[1,2]}'
    assert canonical_json(["b", "a"]) == '["b","a"]'


@pytest.mark.parametrize(
    "truth", (TruthStatus.DISPUTED, TruthStatus.UNKNOWN)
)
def test_lone_epistemic_uncertainty_is_not_absence(truth: TruthStatus) -> None:
    uncertain_key = FactKey("artifact", f"status_{truth.value}")
    promoted_key = FactKey("consumer", f"promoted_{truth.value}")
    uncertain_o = _observation(f"lone_{truth.value}", 1)
    consumer_o = _observation(f"lone_{truth.value}_consumer", 2)
    uncertain = _event(
        f"lone_{truth.value}",
        uncertain_key,
        "possibly_present",
        observation=uncertain_o,
        effective_time=1,
        recorded_at=10,
        truth=truth,
    )
    consumer = _event(
        f"lone_{truth.value}_consumer",
        promoted_key,
        True,
        observation=consumer_o,
        effective_time=2,
        recorded_at=20,
        requirements=(Requirement(uncertain_key, RequirementOp.ABSENT),),
    )
    ledger = EventLedger()
    _append(ledger, (uncertain_o, consumer_o), (uncertain, consumer))

    snapshot = ledger.replay(valid_at=2)
    assert uncertain_key in snapshot.ambiguous_keys
    assert snapshot.cell(uncertain_key) is None
    assert snapshot.value(promoted_key) is None
    assert {item.event_id: item.reason for item in snapshot.decisions}[
        consumer.event_id
    ] == "precondition_failed"
    epistemic = next(
        item
        for item in snapshot.contradictions
        if item.claim_ids == (uncertain.claims[0].claim_id,)
    )
    assert epistemic.resolution == "unresolved"


def test_nonpromotable_intent_does_not_create_world_state_uncertainty() -> None:
    key = FactKey("artifact", "planned_status")
    result = FactKey("consumer", "planned_absence")
    planned_o = _observation("unknown_plan", 1)
    consumer_o = _observation("unknown_plan_consumer", 2)
    planned = _event(
        "unknown_plan",
        key,
        "possibly_present",
        observation=planned_o,
        effective_time=1,
        recorded_at=10,
        truth=TruthStatus.UNKNOWN,
        basis=EvidenceBasis.PLANNED,
        authority=Authority.MODEL,
    )
    consumer = _event(
        "unknown_plan_consumer",
        result,
        True,
        observation=consumer_o,
        effective_time=2,
        recorded_at=20,
        requirements=(Requirement(key, RequirementOp.ABSENT),),
    )
    ledger = EventLedger()
    _append(ledger, (planned_o, consumer_o), (planned, consumer))

    snapshot = ledger.replay(valid_at=2)
    assert key not in snapshot.ambiguous_keys
    assert snapshot.value(result) is True


def test_precondition_failed_uncertain_assertion_has_no_epistemic_authority() -> None:
    gate = FactKey("gate", "open")
    key = FactKey("artifact", "conditional_unknown")
    result = FactKey("consumer", "conditional_absence")
    uncertain_o = _observation("conditional_unknown", 1)
    consumer_o = _observation("conditional_unknown_consumer", 2)
    uncertain = _event(
        "conditional_unknown",
        key,
        "possibly_present",
        observation=uncertain_o,
        effective_time=1,
        recorded_at=10,
        truth=TruthStatus.DISPUTED,
        requirements=(Requirement(gate, RequirementOp.EQ, True),),
    )
    consumer = _event(
        "conditional_unknown_consumer",
        result,
        True,
        observation=consumer_o,
        effective_time=2,
        recorded_at=20,
        requirements=(Requirement(key, RequirementOp.ABSENT),),
    )
    ledger = EventLedger()
    _append(ledger, (uncertain_o, consumer_o), (uncertain, consumer))

    snapshot = ledger.replay(valid_at=2)
    assert key not in snapshot.ambiguous_keys
    assert snapshot.value(result) is True


def test_epistemic_uncertainty_respects_knowledge_and_validity_intervals() -> None:
    key = FactKey("artifact", "bounded_unknown")
    uncertain_o = _observation("bounded_unknown", 20)
    uncertain = _event(
        "bounded_unknown",
        key,
        "possibly_present",
        observation=uncertain_o,
        effective_time=2,
        recorded_at=20,
        valid_to=4,
        truth=TruthStatus.UNKNOWN,
    )
    ledger = EventLedger()
    _append(ledger, (uncertain_o,), (uncertain,))

    assert key not in ledger.replay(valid_at=3, known_at=19).ambiguous_keys
    assert key in ledger.replay(valid_at=3, known_at=20).ambiguous_keys
    expired = ledger.replay(valid_at=4, known_at=20)
    assert key not in expired.ambiguous_keys
    assert expired.contradictions == ()


def test_explicit_supersession_resolves_lone_epistemic_uncertainty() -> None:
    key = FactKey("artifact", "resolved_unknown")
    uncertain_o = _observation("resolved_unknown", 1)
    resolver_o = _observation("resolved_unknown_resolver", 2)
    uncertain = _event(
        "resolved_unknown",
        key,
        "possibly_present",
        observation=uncertain_o,
        effective_time=1,
        recorded_at=10,
        truth=TruthStatus.DISPUTED,
    )
    resolver = _event(
        "resolved_unknown_resolver",
        key,
        "confirmed",
        observation=resolver_o,
        effective_time=2,
        recorded_at=20,
        supersedes=(uncertain.claims[0].claim_id,),
    )
    ledger = EventLedger()
    _append(ledger, (uncertain_o, resolver_o), (uncertain, resolver))

    snapshot = ledger.replay(valid_at=2)
    assert snapshot.value(key) == "confirmed"
    assert key not in snapshot.ambiguous_keys
    epistemic = next(
        item
        for item in snapshot.contradictions
        if uncertain.claims[0].claim_id in item.claim_ids
    )
    assert epistemic.resolution == "superseded"
    assert epistemic.resolved_by_claim_id == resolver.claims[0].claim_id


@pytest.mark.parametrize("reverse_record_order", (False, True))
def test_same_stage_uncertain_peers_use_one_immutable_pre_stage_view(
    reverse_record_order: bool,
) -> None:
    x_key = FactKey("peer", "x")
    y_key = FactKey("peer", "y")
    result_key = FactKey("peer", "absence_consumer")
    x_o = _observation(f"peer_x_{reverse_record_order}", 1)
    y_o = _observation(f"peer_y_{reverse_record_order}", 2)
    consumer_o = _observation(f"peer_consumer_{reverse_record_order}", 3)
    x_record, y_record = ((20, 10) if reverse_record_order else (10, 20))
    x_event = _event(
        f"peer_x_{reverse_record_order}",
        x_key,
        "unknown_x",
        observation=x_o,
        effective_time=1,
        recorded_at=x_record,
        truth=TruthStatus.UNKNOWN,
        requirements=(Requirement(y_key, RequirementOp.ABSENT),),
    )
    y_event = _event(
        f"peer_y_{reverse_record_order}",
        y_key,
        "unknown_y",
        observation=y_o,
        effective_time=1,
        recorded_at=y_record,
        truth=TruthStatus.DISPUTED,
        requirements=(Requirement(x_key, RequirementOp.ABSENT),),
    )
    consumer = _event(
        f"peer_consumer_{reverse_record_order}",
        result_key,
        True,
        observation=consumer_o,
        effective_time=1,
        recorded_at=30,
        requirements=(Requirement(x_key, RequirementOp.ABSENT),),
    )
    ledger = EventLedger()
    _append(
        ledger,
        (x_o, y_o, consumer_o),
        (x_event, y_event, consumer),
    )

    snapshot = ledger.replay(valid_at=1)
    assert snapshot.ambiguous_keys == (x_key, y_key)
    assert {
        item.claim_ids for item in snapshot.contradictions
    } == {
        (x_event.claims[0].claim_id,),
        (y_event.claims[0].claim_id,),
    }
    assert snapshot.value(result_key) is None
    assert {item.event_id: item.reason for item in snapshot.decisions}[
        consumer.event_id
    ] == "precondition_failed"


@pytest.mark.parametrize(
    ("effect_key", "claim_value", "effect_value", "op"),
    (
        (FactKey("wrong", "key"), "Ari", "Ari", EffectOp.SET),
        (FactKey("seal", "owner"), "Ari", "Bea", EffectOp.SET),
        (FactKey("seal", "owner"), 1, 2, EffectOp.INCREMENT),
        (FactKey("seal", "owner"), "Ari", None, EffectOp.DELETE),
    ),
)
def test_effect_key_and_value_are_bound_to_the_cited_claim(
    effect_key: FactKey,
    claim_value,
    effect_value,
    op: EffectOp,
) -> None:
    key = FactKey("seal", "owner")
    observation = _observation("binding")
    evidence = EvidenceRef.from_observation(observation)
    claim = ClaimRevision(
        "c_binding",
        key,
        claim_value,
        EvidenceBasis.OBSERVED,
        TruthStatus.ACCEPTED,
        Authority.CANONICAL,
        1,
        None,
        10,
        (evidence,),
    )

    with pytest.raises(ModelInvariantError, match="key and value"):
        CanonicalEvent(
            "e_binding",
            "binding",
            1,
            10,
            ("seal",),
            (),
            (
                StateEffect(
                    claim.claim_id,
                    effect_key,
                    op,
                    effect_value,
                    0 if op is EffectOp.INCREMENT else None,
                    2 if op is EffectOp.INCREMENT else None,
                ),
            ),
            (claim,),
            (),
            (),
            (evidence,),
        )


def test_delete_effect_rejects_a_non_null_value_at_construction() -> None:
    with pytest.raises(ModelInvariantError, match="DELETE.*null"):
        StateEffect(
            "c_delete",
            FactKey("seal", "owner"),
            EffectOp.DELETE,
            "Ari",
        )


def test_duplicate_effect_keys_within_one_event_are_rejected() -> None:
    key = FactKey("seal", "owner")
    observation = _observation("duplicate_effect_key")
    evidence = EvidenceRef.from_observation(observation)
    claims = (
        ClaimRevision(
            "c_duplicate_set",
            key,
            "Ari",
            EvidenceBasis.OBSERVED,
            TruthStatus.ACCEPTED,
            Authority.CANONICAL,
            1,
            None,
            10,
            (evidence,),
        ),
        ClaimRevision(
            "c_duplicate_delete",
            key,
            None,
            EvidenceBasis.OBSERVED,
            TruthStatus.ACCEPTED,
            Authority.CANONICAL,
            1,
            None,
            10,
            (evidence,),
        ),
    )

    with pytest.raises(ModelInvariantError, match="effect keys.*unique"):
        CanonicalEvent(
            "e_duplicate_effect_key",
            "duplicate_effect_key",
            1,
            10,
            ("seal",),
            (),
            (
                StateEffect(claims[0].claim_id, key, EffectOp.SET, "Ari"),
                StateEffect(claims[1].claim_id, key, EffectOp.DELETE, None),
            ),
            claims,
            (),
            (),
            (evidence,),
        )


@pytest.mark.parametrize("future_on", ("event", "claim"))
def test_evidence_recorded_after_its_citing_record_is_rejected(future_on: str) -> None:
    key = FactKey("seal", "owner")
    old = _observation("old", 1)
    future = _observation("future", 30)
    old_ref = EvidenceRef.from_observation(old)
    future_ref = EvidenceRef.from_observation(future)
    event = _event(
        f"future_{future_on}",
        key,
        "Ari",
        observation=old,
        effective_time=1,
        recorded_at=20,
        event_evidence=(future_ref,) if future_on == "event" else (old_ref,),
        claim_evidence=(future_ref,) if future_on == "claim" else (old_ref,),
    )
    ledger = EventLedger()
    ledger.append_observation(old)
    ledger.append_observation(future)

    with pytest.raises(ModelInvariantError, match="recorded after"):
        ledger.append_event(event)


@pytest.mark.parametrize("dependency_kind", ("hard", "causal", "claim"))
def test_dependencies_recorded_in_the_future_are_rejected(
    dependency_kind: str,
) -> None:
    key = FactKey("seal", "owner")
    target_o = _observation("future_dependency", 1)
    dependent_o = _observation(f"dependent_{dependency_kind}", 2)
    target = _event(
        "future_dependency",
        key,
        "Ari",
        observation=target_o,
        effective_time=1,
        recorded_at=20,
    )
    kwargs = {
        "hard_dependencies": (target.event_id,) if dependency_kind == "hard" else (),
        "causal_parents": (target.event_id,) if dependency_kind == "causal" else (),
        "claim_dependencies": ("c_future_dependency",)
        if dependency_kind == "claim"
        else (),
    }
    dependent = _event(
        f"dependent_{dependency_kind}",
        FactKey("seal", f"dependent_{dependency_kind}"),
        True,
        observation=dependent_o,
        effective_time=2,
        recorded_at=10,
        **kwargs,
    )
    ledger = EventLedger()
    _append(ledger, (target_o, dependent_o), (target,))

    with pytest.raises(ModelInvariantError, match="recorded in the future"):
        ledger.append_event(dependent)


def test_promotion_decision_binds_full_event_content_and_replay_checks_it() -> None:
    key = FactKey("seal", "owner")
    observation = _observation("decision")
    event = _event(
        "decision",
        key,
        "Ari",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    ledger.append_observation(observation)

    decision = ledger.append_event(event)

    assert decision.evidence_sha256
    assert decision.event_content_hash == event.content_hash
    ledger._events[event.event_id] = replace(event, event_type="tampered")
    with pytest.raises(ModelInvariantError, match="recomputed authority decision"):
        ledger.replay(valid_at=1)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda item: replace(item, event_id="e_other"),
        lambda item: replace(item, status=DecisionStatus.REJECT),
        lambda item: replace(item, policy_id="forged-policy"),
        lambda item: replace(item, reason="forged-reason"),
        lambda item: replace(item, evidence_sha256="0" * 64),
        lambda item: replace(item, event_content_hash="0" * 64),
    ),
)
def test_replay_recomputes_and_checks_the_entire_promotion_decision(mutation) -> None:
    key = FactKey("seal", "decision_integrity")
    observation = _observation("decision_integrity")
    event = _event(
        "decision_integrity",
        key,
        True,
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    ledger.append_observation(observation)
    decision = ledger.append_event(event)
    ledger._decisions[event.event_id] = mutation(decision)

    with pytest.raises(ModelInvariantError, match="recomputed authority decision"):
        ledger.replay(valid_at=1)


@pytest.mark.parametrize(
    ("left_op", "left_value", "right_op", "right_value"),
    (
        (EffectOp.SET, 1, EffectOp.DELETE, None),
        (EffectOp.SET, 1, EffectOp.INCREMENT, 2),
        (EffectOp.DELETE, None, EffectOp.INCREMENT, 2),
    ),
)
@pytest.mark.parametrize("append_reversed", (False, True))
def test_all_incompatible_same_time_effect_pairs_are_order_independent_conflicts(
    left_op: EffectOp,
    left_value,
    right_op: EffectOp,
    right_value,
    append_reversed: bool,
) -> None:
    key = FactKey("counter", "value")
    base_o = _observation("effect_pair_base")
    left_o, right_o = _observation("left"), _observation("right")
    base = _event(
        "effect_pair_base",
        key,
        0,
        observation=base_o,
        effective_time=0,
        recorded_at=1,
    )
    left = _event(
        "left",
        key,
        left_value,
        observation=left_o,
        effective_time=1,
        recorded_at=10,
        op=left_op,
        expected_previous=0,
        increment_by=left_value if left_op is EffectOp.INCREMENT else None,
    )
    right = _event(
        "right",
        key,
        right_value,
        observation=right_o,
        effective_time=1,
        recorded_at=20,
        op=right_op,
        expected_previous=0,
        increment_by=right_value if right_op is EffectOp.INCREMENT else None,
    )
    events = (right, left) if append_reversed else (left, right)
    ledger = EventLedger()
    _append(ledger, (base_o, left_o, right_o), (base, *events))

    snapshot = ledger.replay(valid_at=1)

    assert snapshot.value(key) is None
    assert snapshot.ambiguous_keys == (key,)
    assert len(snapshot.contradictions) == 1
    assert snapshot.contradictions[0].resolution == "unresolved"
    assert {
        item.reason
        for item in snapshot.decisions
        if item.event_id in {left.event_id, right.event_id}
    } == {"unresolved_contradiction"}


def test_same_time_increments_conflict_without_explicit_ordering() -> None:
    key = FactKey("counter", "value")
    base_o = _observation("increment_base")
    left_o, right_o = _observation("increment_left"), _observation("increment_right")
    base = _event(
        "increment_base",
        key,
        0,
        observation=base_o,
        effective_time=0,
        recorded_at=1,
    )
    left = _event(
        "increment_left",
        key,
        2,
        observation=left_o,
        effective_time=1,
        recorded_at=10,
        op=EffectOp.INCREMENT,
        expected_previous=0,
        increment_by=2,
    )
    right = _event(
        "increment_right",
        key,
        3,
        observation=right_o,
        effective_time=1,
        recorded_at=20,
        op=EffectOp.INCREMENT,
        expected_previous=0,
        increment_by=3,
    )
    ledger = EventLedger()
    _append(ledger, (base_o, left_o, right_o), (base, right, left))

    snapshot = ledger.replay(valid_at=1)

    assert snapshot.value(key) is None
    assert snapshot.ambiguous_keys == (key,)
    assert snapshot.contradictions[0].resolution == "unresolved"


def test_increment_binds_expected_delta_and_result_to_claim_provenance() -> None:
    key = FactKey("counter", "bound_increment")
    with pytest.raises(ModelInvariantError, match="numeric expected_previous"):
        StateEffect("c_missing_increment_contract", key, EffectOp.INCREMENT, 12)
    with pytest.raises(ModelInvariantError, match="result must equal"):
        StateEffect(
            "c_bad_increment_result",
            key,
            EffectOp.INCREMENT,
            13,
            expected_previous=10,
            increment_by=2,
        )

    base_o = _observation("bound_increment_base")
    increment_o = _observation("bound_increment")
    base = _event(
        "bound_increment_base",
        key,
        10,
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    increment = _event(
        "bound_increment",
        key,
        12,
        observation=increment_o,
        effective_time=2,
        recorded_at=20,
        op=EffectOp.INCREMENT,
        expected_previous=10,
        increment_by=2,
    )
    ledger = EventLedger()
    _append(ledger, (base_o, increment_o), (base, increment))

    snapshot = ledger.replay(valid_at=2)

    assert increment.claims[0].value == 12
    assert increment.effects[0].increment_by == 2
    assert snapshot.value(key) == 12
    assert snapshot.cell(key).source_claim_id == increment.claims[0].claim_id


@pytest.mark.parametrize("append_reversed", (False, True))
def test_same_value_sets_with_different_validity_windows_conflict(
    append_reversed: bool,
) -> None:
    key = FactKey("seal", "same_value_owner")
    short_o = _observation("same_value_short")
    long_o = _observation("same_value_long")
    short = _event(
        "same_value_short",
        key,
        "Ari",
        observation=short_o,
        effective_time=1,
        recorded_at=10,
        valid_to=3,
    )
    long = _event(
        "same_value_long",
        key,
        "Ari",
        observation=long_o,
        effective_time=1,
        recorded_at=20,
        valid_to=5,
    )
    events = (long, short) if append_reversed else (short, long)
    ledger = EventLedger()
    _append(ledger, (short_o, long_o), events)

    snapshot = ledger.replay(valid_at=1)

    assert snapshot.value(key) is None
    assert snapshot.ambiguous_keys == (key,)
    assert snapshot.contradictions[0].overlap_to == 3


def test_same_value_sets_with_identical_validity_are_compatible() -> None:
    key = FactKey("seal", "identical_value_owner")
    left_o = _observation("identical_value_left")
    right_o = _observation("identical_value_right")
    left = _event(
        "identical_value_left",
        key,
        "Ari",
        observation=left_o,
        effective_time=1,
        recorded_at=10,
        valid_to=5,
    )
    right = _event(
        "identical_value_right",
        key,
        "Ari",
        observation=right_o,
        effective_time=1,
        recorded_at=20,
        valid_to=5,
    )
    ledger = EventLedger()
    _append(ledger, (left_o, right_o), (right, left))

    snapshot = ledger.replay(valid_at=1)

    assert snapshot.value(key) == "Ari"
    assert snapshot.ambiguous_keys == ()
    assert snapshot.contradictions == ()


@pytest.mark.parametrize(
    ("poison_recorded_at", "valid_recorded_at"), ((10, 20), (20, 10))
)
@pytest.mark.parametrize("append_reversed", (False, True))
def test_false_precondition_cannot_poison_a_valid_same_time_peer(
    poison_recorded_at: int,
    valid_recorded_at: int,
    append_reversed: bool,
) -> None:
    gate = FactKey("gate", "open")
    target = FactKey("seal", "owner")
    base_o = _observation("gate_closed")
    valid_o = _observation("valid")
    poison_o = _observation("poison")
    base = _event(
        "gate_closed",
        gate,
        False,
        observation=base_o,
        effective_time=1,
        recorded_at=1,
    )
    valid = _event(
        "valid",
        target,
        "Ari",
        observation=valid_o,
        effective_time=2,
        recorded_at=valid_recorded_at,
    )
    poison = _event(
        "poison",
        target,
        "Bea",
        observation=poison_o,
        effective_time=2,
        recorded_at=poison_recorded_at,
        requirements=(Requirement(gate, RequirementOp.EQ, True),),
    )
    peers = (valid, poison) if append_reversed else (poison, valid)
    ledger = EventLedger()
    _append(ledger, (base_o, valid_o, poison_o), (base, *peers))

    snapshot = ledger.replay(valid_at=2)
    reasons = {item.event_id: item.reason for item in snapshot.decisions}

    assert snapshot.value(target) == "Ari"
    assert not snapshot.ambiguous_keys
    assert not snapshot.contradictions
    assert reasons[valid.event_id] == "admitted"
    assert reasons[poison.event_id] == "precondition_failed"


@pytest.mark.parametrize("peer_order", ((0, 1, 2), (2, 1, 0)))
def test_unordered_peer_reads_pre_stage_state_despite_a_peer_write_conflict(
    peer_order: tuple[int, int, int],
) -> None:
    source = FactKey("source", "value")
    result = FactKey("reader", "result")
    base_o = _observation("peer_read_base")
    left_o = _observation("peer_read_left")
    right_o = _observation("peer_read_right")
    reader_o = _observation("peer_read_consumer")
    base = _event(
        "peer_read_base",
        source,
        "base",
        observation=base_o,
        effective_time=0,
        recorded_at=1,
    )
    left = _event(
        "peer_read_left",
        source,
        "A",
        observation=left_o,
        effective_time=1,
        recorded_at=10,
        expected_previous="base",
    )
    right = _event(
        "peer_read_right",
        source,
        "B",
        observation=right_o,
        effective_time=1,
        recorded_at=20,
        expected_previous="base",
    )
    reader = _event(
        "peer_read_consumer",
        result,
        "read-ok",
        observation=reader_o,
        effective_time=1,
        recorded_at=30,
        requirements=(Requirement(source, RequirementOp.EQ, "base"),),
    )
    peers = (left, right, reader)
    ledger = EventLedger()
    _append(
        ledger,
        (base_o, left_o, right_o, reader_o),
        (base, *(peers[index] for index in peer_order)),
    )

    snapshot = ledger.replay(valid_at=1)
    reasons = {item.event_id: item.reason for item in snapshot.decisions}

    assert snapshot.value(source) is None
    assert snapshot.ambiguous_keys == (source,)
    assert snapshot.value(result) == "read-ok"
    assert reasons[left.event_id] == "unresolved_contradiction"
    assert reasons[right.event_id] == "unresolved_contradiction"
    assert reasons[reader.event_id] == "admitted"


def _ledger_with_prior_and_conflict(
    *,
    left_valid_to: int | None,
    right_valid_to: int | None,
) -> tuple[EventLedger, FactKey, CanonicalEvent, CanonicalEvent, CanonicalEvent]:
    key = FactKey("seal", "conflicted_owner")
    prior_o = _observation("overlay_prior")
    left_o = _observation("overlay_left")
    right_o = _observation("overlay_right")
    prior = _event(
        "overlay_prior",
        key,
        "Prior",
        observation=prior_o,
        effective_time=0,
        recorded_at=1,
    )
    left = _event(
        "overlay_left",
        key,
        "Ari",
        observation=left_o,
        effective_time=1,
        recorded_at=10,
        valid_to=left_valid_to,
        expected_previous="Prior",
        supersedes=(prior.claims[0].claim_id,),
    )
    right = _event(
        "overlay_right",
        key,
        "Bea",
        observation=right_o,
        effective_time=1,
        recorded_at=20,
        valid_to=right_valid_to,
        expected_previous="Prior",
        supersedes=(prior.claims[0].claim_id,),
    )
    ledger = EventLedger()
    _append(ledger, (prior_o, left_o, right_o), (prior, left, right))
    return ledger, key, prior, left, right


def test_ambiguous_state_is_unknown_and_does_not_satisfy_absent() -> None:
    ledger, key, _, _, _ = _ledger_with_prior_and_conflict(
        left_valid_to=None,
        right_valid_to=None,
    )
    result = FactKey("audit", "absent_result")
    observation = _observation("absent_consumer")
    consumer = _event(
        "absent_consumer",
        result,
        "incorrectly_admitted",
        observation=observation,
        effective_time=2,
        recorded_at=30,
        requirements=(Requirement(key, RequirementOp.ABSENT),),
    )
    ledger.append_observation(observation)
    ledger.append_event(consumer)

    snapshot = ledger.replay(valid_at=2)
    reasons = {item.event_id: item.reason for item in snapshot.decisions}

    assert snapshot.value(key) is None
    assert snapshot.cell(key) is None
    assert all(cell.key != key for cell in snapshot.cells)
    assert key in snapshot.ambiguous_keys
    assert snapshot.value(result) is None
    assert reasons[consumer.event_id] == "precondition_failed"


def test_ambiguity_expires_only_after_all_conflicting_claims_and_prior_reappears() -> None:
    ledger, key, _, _, _ = _ledger_with_prior_and_conflict(
        left_valid_to=2,
        right_valid_to=4,
    )

    during_overlap = ledger.replay(valid_at=1)
    after_one_expiry = ledger.replay(valid_at=2)
    after_all_expire = ledger.replay(valid_at=4)

    assert during_overlap.value(key) is None
    assert during_overlap.contradictions[0].overlap_to == 2
    assert after_one_expiry.value(key) is None
    assert after_one_expiry.ambiguous_keys == (key,)
    assert after_one_expiry.contradictions[0].resolution == "unresolved"
    assert after_all_expire.value(key) == "Prior"
    assert after_all_expire.ambiguous_keys == ()
    assert after_all_expire.contradictions[0].resolution == "expired"


@pytest.mark.parametrize("append_reversed", (False, True))
def test_later_full_supersession_resolves_conflict_and_clears_ambiguity(
    append_reversed: bool,
) -> None:
    key = FactKey("seal", "owner")
    a_o, b_o, resolver_o = (
        _observation("resolver_a"),
        _observation("resolver_b"),
        _observation("resolver"),
    )
    a = _event(
        "resolver_a",
        key,
        "Ari",
        observation=a_o,
        effective_time=1,
        recorded_at=10,
    )
    b = _event(
        "resolver_b",
        key,
        "Bea",
        observation=b_o,
        effective_time=1,
        recorded_at=20,
    )
    resolver = _event(
        "resolver",
        key,
        "Cato",
        observation=resolver_o,
        effective_time=2,
        recorded_at=30,
        supersedes=(a.claims[0].claim_id, b.claims[0].claim_id),
    )
    peers = (b, a) if append_reversed else (a, b)
    ledger = EventLedger()
    _append(ledger, (a_o, b_o, resolver_o), (*peers, resolver))

    snapshot = ledger.replay(valid_at=2)
    contradiction = snapshot.contradictions[0]

    assert snapshot.value(key) == "Cato"
    assert snapshot.ambiguous_keys == ()
    assert contradiction.resolution == "superseded"
    assert contradiction.resolved_by_claim_id == resolver.claims[0].claim_id
    assert next(
        item for item in snapshot.decisions if item.event_id == resolver.event_id
    ).admitted


def test_partial_supersession_does_not_resolve_a_conflict() -> None:
    key = FactKey("seal", "owner")
    a_o, b_o, partial_o = (
        _observation("partial_a"),
        _observation("partial_b"),
        _observation("partial"),
    )
    a = _event(
        "partial_a", key, "Ari", observation=a_o, effective_time=1, recorded_at=10
    )
    b = _event(
        "partial_b", key, "Bea", observation=b_o, effective_time=1, recorded_at=20
    )
    partial = _event(
        "partial",
        key,
        "Cato",
        observation=partial_o,
        effective_time=2,
        recorded_at=30,
        supersedes=(a.claims[0].claim_id,),
    )
    ledger = EventLedger()
    _append(ledger, (a_o, b_o, partial_o), (a, b, partial))

    snapshot = ledger.replay(valid_at=2)
    partial_decision = next(
        item for item in snapshot.decisions if item.event_id == partial.event_id
    )

    assert not partial_decision.admitted
    assert partial_decision.reason == "unresolved_contradiction"
    assert snapshot.value(key) is None
    assert snapshot.ambiguous_keys == (key,)
    assert snapshot.contradictions[0].resolution == "unresolved"


def test_resolver_only_needs_to_supersede_conflicting_claims_active_at_its_time() -> None:
    ledger, key, _, left, right = _ledger_with_prior_and_conflict(
        left_valid_to=2,
        right_valid_to=5,
    )
    resolver_o = _observation("active_only_resolver")
    resolver = _event(
        "active_only_resolver",
        key,
        "Cato",
        observation=resolver_o,
        effective_time=3,
        recorded_at=30,
        supersedes=(right.claims[0].claim_id,),
    )
    ledger.append_observation(resolver_o)
    ledger.append_event(resolver)

    snapshot = ledger.replay(valid_at=3)

    assert left.claims[0].claim_id not in resolver.claims[0].supersedes_claim_ids
    assert snapshot.value(key) == "Cato"
    assert snapshot.ambiguous_keys == ()
    assert snapshot.contradictions[0].resolution == "superseded"
    assert snapshot.contradictions[0].resolved_by_claim_id == resolver.claims[0].claim_id


@pytest.mark.parametrize("rejection_kind", ("planned", "precondition"))
def test_rejected_superseders_have_no_temporal_or_contradiction_authority(
    rejection_kind: str,
) -> None:
    key = FactKey("seal", f"rejected_superseder_{rejection_kind}")
    base_o = _observation(f"superseder_base_{rejection_kind}")
    disputed_o = _observation(f"superseder_disputed_{rejection_kind}")
    rejected_o = _observation(f"superseder_rejected_{rejection_kind}")
    base = _event(
        f"superseder_base_{rejection_kind}",
        key,
        "Ari",
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    disputed = _event(
        f"superseder_disputed_{rejection_kind}",
        key,
        "Bea",
        observation=disputed_o,
        effective_time=1,
        recorded_at=20,
        truth=TruthStatus.DISPUTED,
    )
    rejected = _event(
        f"superseder_rejected_{rejection_kind}",
        key,
        "Cato",
        observation=rejected_o,
        effective_time=2,
        recorded_at=30,
        requirements=(
            (Requirement(FactKey("gate", "open"), RequirementOp.EQ, True),)
            if rejection_kind == "precondition"
            else ()
        ),
        supersedes=(base.claims[0].claim_id, disputed.claims[0].claim_id),
        basis=(
            EvidenceBasis.PLANNED
            if rejection_kind == "planned"
            else EvidenceBasis.OBSERVED
        ),
        authority=(
            Authority.MODEL
            if rejection_kind == "planned"
            else Authority.CANONICAL
        ),
    )
    ledger = EventLedger()
    _append(
        ledger,
        (base_o, disputed_o, rejected_o),
        (base, disputed, rejected),
    )

    snapshot = ledger.replay(valid_at=2)
    contradiction = next(
        item
        for item in snapshot.contradictions
        if set(item.claim_ids)
        == {base.claims[0].claim_id, disputed.claims[0].claim_id}
    )

    assert snapshot.value(key) == "Ari"
    assert contradiction.resolution == "authority"
    assert ledger.temporal_status(
        base.claims[0].claim_id, valid_at=2
    ) is TemporalStatus.CURRENT
    assert ledger.temporal_status(
        disputed.claims[0].claim_id, valid_at=2
    ) is TemporalStatus.CURRENT
    assert not next(
        item for item in snapshot.decisions if item.event_id == rejected.event_id
    ).admitted


def test_expired_nonoverlapping_disputed_claim_has_no_present_contradiction() -> None:
    key = FactKey("seal", "nonoverlap")
    disputed_o = _observation("nonoverlap_disputed")
    accepted_o = _observation("nonoverlap_accepted")
    disputed = _event(
        "nonoverlap_disputed",
        key,
        "Bea",
        observation=disputed_o,
        effective_time=1,
        recorded_at=10,
        valid_to=2,
        truth=TruthStatus.DISPUTED,
    )
    accepted = _event(
        "nonoverlap_accepted",
        key,
        "Ari",
        observation=accepted_o,
        effective_time=3,
        recorded_at=20,
    )
    ledger = EventLedger()
    _append(ledger, (disputed_o, accepted_o), (disputed, accepted))

    snapshot = ledger.replay(valid_at=3)

    assert snapshot.value(key) == "Ari"
    assert snapshot.contradictions == ()


@pytest.mark.parametrize("truth", (TruthStatus.DISPUTED, TruthStatus.FALSE))
def test_temporal_status_is_independent_of_truth_status(truth: TruthStatus) -> None:
    key = FactKey("seal", truth.value)
    observation = _observation(f"temporal_{truth.value}")
    resolver_observation = _observation(f"temporal_{truth.value}_resolver")
    event = _event(
        f"temporal_{truth.value}",
        key,
        True,
        observation=observation,
        effective_time=2,
        recorded_at=10,
        valid_to=4,
        truth=truth,
    )
    resolver = _event(
        f"temporal_{truth.value}_resolver",
        key,
        False,
        observation=resolver_observation,
        effective_time=5,
        recorded_at=20,
        supersedes=(event.claims[0].claim_id,),
    )
    ledger = EventLedger()
    _append(ledger, (observation, resolver_observation), (event, resolver))

    assert {item.value for item in TemporalStatus} == {
        "current",
        "historical",
        "superseded",
        "future",
        "unknown",
    }
    assert ledger.temporal_status(
        event.claims[0].claim_id, valid_at=1, known_at=10
    ) is TemporalStatus.FUTURE
    assert ledger.temporal_status(
        event.claims[0].claim_id, valid_at=3, known_at=10
    ) is TemporalStatus.CURRENT
    assert ledger.temporal_status(
        event.claims[0].claim_id, valid_at=4, known_at=10
    ) is TemporalStatus.HISTORICAL
    assert ledger.temporal_status(
        event.claims[0].claim_id, valid_at=5, known_at=20
    ) is TemporalStatus.SUPERSEDED
