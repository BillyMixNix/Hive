from __future__ import annotations

import pytest

from hive_reference.model import (
    Authority,
    AuthorityPolicy,
    CanonicalEvent,
    ClaimRevision,
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
    TruthStatus,
)
from hive_reference.representation import (
    DeterministicReferenceSolver,
    ReferenceCompressor,
    RepresentationRootCommitment,
    SelectiveDecompressor,
    SolveStatus,
    TaskKind,
    TaskQuery,
)


def _observation(name: str, recorded_at: int) -> Observation:
    return Observation.create(
        f"o_{name}",
        "temporal_equivalence_fixture",
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
    valid_to: int | None = None,
    expected_previous=None,
    expected_previous_specified: bool = False,
    op: EffectOp = EffectOp.SET,
    increment_by=None,
    requirements: tuple[Requirement, ...] = (),
    hard_dependencies: tuple[str, ...] = (),
    causal_parents: tuple[str, ...] = (),
    claim_dependencies: tuple[str, ...] = (),
    supersedes: tuple[str, ...] = (),
    basis: EvidenceBasis = EvidenceBasis.OBSERVED,
    truth: TruthStatus = TruthStatus.ACCEPTED,
    authority: Authority = Authority.CANONICAL,
    derivation_rule_id: str | None = None,
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
        evidence=(evidence,),
        depends_on_claim_ids=claim_dependencies,
        supersedes_claim_ids=supersedes,
        derivation_rule_id=derivation_rule_id,
    )
    return CanonicalEvent(
        event_id=f"e_{name}",
        event_type="test_transition",
        effective_time=effective_time,
        recorded_at=recorded_at,
        entities=(key.subject,),
        requirements=requirements,
        effects=(
            StateEffect(
                claim_id=claim.claim_id,
                key=key,
                op=op,
                value=value,
                expected_previous=expected_previous,
                increment_by=increment_by,
                expected_previous_specified=expected_previous_specified,
            ),
        ),
        claims=(claim,),
        causal_parents=causal_parents,
        hard_dependencies=hard_dependencies,
        evidence=(evidence,),
    )


def _ledger(
    pairs: list[tuple[Observation, CanonicalEvent]],
    *,
    policy: AuthorityPolicy | None = None,
) -> EventLedger:
    ledger = EventLedger(policy)
    for observation, _ in pairs:
        ledger.append_observation(observation)
    for _, event in pairs:
        ledger.append_event(event)
    return ledger


def _compressed_answer(
    ledger: EventLedger,
    key: FactKey,
    *,
    valid_at: int,
    known_at: int,
    expected_status: SolveStatus = SolveStatus.COMPLETE,
):
    representation = ReferenceCompressor().compress(
        ledger, representation_id="temporal-equivalence"
    )
    query = TaskQuery(
        "q",
        TaskKind.VALUE_AT,
        (key,),
        valid_at,
        known_at,
    )
    root = RepresentationRootCommitment.from_trusted_representation(representation)
    view = SelectiveDecompressor((root,)).decompress(representation, query)
    outcome = DeterministicReferenceSolver().solve(view, query)
    assert outcome.status is expected_status
    return outcome.answer, view


def test_effect_claim_time_must_match_event_time() -> None:
    key = FactKey("seal", "owner")
    observation = _observation("mismatched", 1)
    evidence = EvidenceRef.from_observation(observation)
    claim = ClaimRevision(
        "c_mismatched",
        key,
        "Ari",
        EvidenceBasis.OBSERVED,
        TruthStatus.ACCEPTED,
        Authority.CANONICAL,
        2,
        None,
        10,
        (evidence,),
    )
    with pytest.raises(ModelInvariantError, match="valid_from"):
        CanonicalEvent(
            "e_mismatched",
            "test_transition",
            1,
            10,
            ("seal",),
            (),
            (StateEffect("c_mismatched", key, EffectOp.SET, "Ari"),),
            (claim,),
            (),
            (),
            (evidence,),
        )


def test_compressed_replay_honors_bitemporal_knowledge_cutoff() -> None:
    key = FactKey("seal", "owner")
    first_o = _observation("first", 1)
    late_o = _observation("late", 2)
    first = _event(
        "first",
        key,
        "Ari",
        observation=first_o,
        effective_time=2,
        recorded_at=10,
    )
    late = _event(
        "late",
        key,
        "Bea",
        observation=late_o,
        effective_time=2,
        recorded_at=20,
        expected_previous="Ari",
        supersedes=("c_first",),
    )
    ledger = _ledger([(first_o, first), (late_o, late)])

    early, early_view = _compressed_answer(ledger, key, valid_at=2, known_at=15)
    late_answer, late_view = _compressed_answer(ledger, key, valid_at=2, known_at=25)

    assert early == ledger.replay(valid_at=2, known_at=15).value(key) == "Ari"
    assert late_answer == ledger.replay(valid_at=2, known_at=25).value(key) == "Bea"
    assert "component:event:e_late" not in early_view.selected_component_ids
    assert "component:event:e_late" in late_view.selected_component_ids


def test_expiring_fact_can_satisfy_earlier_event_before_final_query_time() -> None:
    active = FactKey("permit", "active")
    result = FactKey("sale", "status")
    permit_o = _observation("permit", 1)
    sale_o = _observation("sale", 2)
    permit = _event(
        "permit",
        active,
        True,
        observation=permit_o,
        effective_time=1,
        recorded_at=10,
        valid_to=5,
    )
    sale = _event(
        "sale",
        result,
        "completed",
        observation=sale_o,
        effective_time=4,
        recorded_at=20,
        requirements=(Requirement(active, RequirementOp.EQ, True),),
        hard_dependencies=("e_permit",),
    )
    ledger = _ledger([(permit_o, permit), (sale_o, sale)])

    compressed, _ = _compressed_answer(ledger, result, valid_at=10, known_at=99)
    assert compressed == ledger.replay(valid_at=10).value(result) == "completed"
    assert ledger.replay(valid_at=10).value(active) is None


def test_rejected_causal_parent_gates_compressed_child_identically() -> None:
    parent_key = FactKey("permit", "planned")
    child_key = FactKey("sale", "status")
    parent_o = _observation("compressed_rejected_parent", 1)
    child_o = _observation("compressed_causal_child", 2)
    parent = _event(
        "compressed_rejected_parent",
        parent_key,
        True,
        observation=parent_o,
        effective_time=1,
        recorded_at=10,
        basis=EvidenceBasis.PLANNED,
        authority=Authority.MODEL,
    )
    child = _event(
        "compressed_causal_child",
        child_key,
        "completed",
        observation=child_o,
        effective_time=2,
        recorded_at=20,
        causal_parents=(parent.event_id,),
    )
    ledger = _ledger([(parent_o, parent), (child_o, child)])

    compressed, _ = _compressed_answer(
        ledger, child_key, valid_at=2, known_at=99
    )
    assert compressed == ledger.replay(valid_at=2).value(child_key) is None


def test_explicit_null_guard_has_compressed_replay_parity() -> None:
    key = FactKey("nullable", "value")
    base_o = _observation("compressed_nullable_base", 1)
    next_o = _observation("compressed_nullable_next", 2)
    base = _event(
        "compressed_nullable_base",
        key,
        None,
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    guarded = _event(
        "compressed_nullable_next",
        key,
        "B",
        observation=next_o,
        effective_time=2,
        recorded_at=20,
        expected_previous=None,
        expected_previous_specified=True,
    )
    ledger = _ledger([(base_o, base), (next_o, guarded)])

    compressed, _ = _compressed_answer(ledger, key, valid_at=2, known_at=99)
    assert compressed == ledger.replay(valid_at=2).value(key) == "B"


@pytest.mark.parametrize("transition_kind", ("delete", "validity"))
def test_transition_authority_has_compressed_replay_parity(
    transition_kind: str,
) -> None:
    key = FactKey("transition", "value")
    base_o = _observation(f"compressed_{transition_kind}_base", 1)
    next_o = _observation(f"compressed_{transition_kind}_next", 2)
    base = _event(
        f"compressed_{transition_kind}_base",
        key,
        "A",
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    if transition_kind == "delete":
        next_event = _event(
            "compressed_delete_next",
            key,
            None,
            observation=next_o,
            effective_time=2,
            recorded_at=20,
            op=EffectOp.DELETE,
        )
    else:
        next_event = _event(
            "compressed_validity_next",
            key,
            "A",
            observation=next_o,
            effective_time=2,
            recorded_at=20,
            valid_to=3,
        )
    ledger = _ledger([(base_o, base), (next_o, next_event)])

    compressed, _ = _compressed_answer(ledger, key, valid_at=4, known_at=99)
    assert compressed == ledger.replay(valid_at=4).value(key) == "A"


@pytest.mark.parametrize(
    ("cell_value", "required_value", "op"),
    (
        (1, True, RequirementOp.EQ),
        (True, 1, RequirementOp.EQ),
        (1, True, RequirementOp.GTE),
    ),
)
def test_typed_precondition_failures_have_compressed_replay_parity(
    cell_value,
    required_value,
    op: RequirementOp,
) -> None:
    key = FactKey("typed", "value")
    result = FactKey("typed", "result")
    suffix = f"{type(cell_value).__name__}_{type(required_value).__name__}_{op.value}"
    base_o = _observation(f"compressed_typed_base_{suffix}", 1)
    child_o = _observation(f"compressed_typed_child_{suffix}", 2)
    base = _event(
        f"compressed_typed_base_{suffix}",
        key,
        cell_value,
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    child = _event(
        f"compressed_typed_child_{suffix}",
        result,
        "incorrectly_admitted",
        observation=child_o,
        effective_time=2,
        recorded_at=20,
        requirements=(Requirement(key, op, required_value),),
    )
    ledger = _ledger([(base_o, base), (child_o, child)])

    compressed, _ = _compressed_answer(ledger, result, valid_at=2, known_at=99)
    assert compressed == ledger.replay(valid_at=2).value(result) is None


@pytest.mark.parametrize(
    "truth", (TruthStatus.DISPUTED, TruthStatus.UNKNOWN)
)
def test_lone_epistemic_unknown_has_compressed_replay_parity(
    truth: TruthStatus,
) -> None:
    key = FactKey("epistemic", truth.value)
    observation = _observation(f"compressed_epistemic_{truth.value}", 1)
    uncertain = _event(
        f"compressed_epistemic_{truth.value}",
        key,
        "possibly_present",
        observation=observation,
        effective_time=1,
        recorded_at=10,
        truth=truth,
    )
    ledger = _ledger([(observation, uncertain)])

    compressed, _ = _compressed_answer(
        ledger,
        key,
        valid_at=1,
        known_at=99,
        expected_status=SolveStatus.INCOMPLETE,
    )
    canonical = ledger.replay(valid_at=1)
    assert compressed == canonical.value(key) is None
    assert canonical.ambiguous_keys == (key,)


def test_epistemic_absence_guard_and_expiry_have_compressed_parity() -> None:
    key = FactKey("epistemic", "bounded")
    result = FactKey("epistemic", "absence_result")
    uncertain_o = _observation("compressed_bounded_unknown", 1)
    consumer_o = _observation("compressed_bounded_consumer", 2)
    uncertain = _event(
        "compressed_bounded_unknown",
        key,
        "possibly_present",
        observation=uncertain_o,
        effective_time=1,
        recorded_at=10,
        valid_to=3,
        truth=TruthStatus.UNKNOWN,
    )
    consumer = _event(
        "compressed_bounded_consumer",
        result,
        True,
        observation=consumer_o,
        effective_time=2,
        recorded_at=20,
        requirements=(Requirement(key, RequirementOp.ABSENT),),
    )
    ledger = _ledger([(uncertain_o, uncertain), (consumer_o, consumer)])

    during, _ = _compressed_answer(ledger, result, valid_at=2, known_at=99)
    after, _ = _compressed_answer(ledger, result, valid_at=3, known_at=99)
    assert during == ledger.replay(valid_at=2).value(result) is None
    # The consumer occurred while the key was unknown, so later expiry does
    # not retroactively admit that failed event.
    assert after == ledger.replay(valid_at=3).value(result) is None


def test_epistemic_supersession_has_compressed_replay_parity() -> None:
    key = FactKey("epistemic", "resolved")
    uncertain_o = _observation("compressed_resolved_unknown", 1)
    resolver_o = _observation("compressed_resolved_resolver", 2)
    uncertain = _event(
        "compressed_resolved_unknown",
        key,
        "possibly_present",
        observation=uncertain_o,
        effective_time=1,
        recorded_at=10,
        truth=TruthStatus.DISPUTED,
    )
    resolver = _event(
        "compressed_resolved_resolver",
        key,
        "confirmed",
        observation=resolver_o,
        effective_time=2,
        recorded_at=20,
        supersedes=(uncertain.claims[0].claim_id,),
    )
    ledger = _ledger([(uncertain_o, uncertain), (resolver_o, resolver)])

    compressed, _ = _compressed_answer(ledger, key, valid_at=2, known_at=99)
    assert compressed == ledger.replay(valid_at=2).value(key) == "confirmed"


@pytest.mark.parametrize("reverse_record_order", (False, True))
def test_same_stage_uncertain_peer_permutations_have_compressed_parity(
    reverse_record_order: bool,
) -> None:
    x_key = FactKey("compressed_peer", "x")
    y_key = FactKey("compressed_peer", "y")
    result_key = FactKey("compressed_peer", "consumer")
    x_o = _observation(f"compressed_peer_x_{reverse_record_order}", 1)
    y_o = _observation(f"compressed_peer_y_{reverse_record_order}", 2)
    consumer_o = _observation(
        f"compressed_peer_consumer_{reverse_record_order}", 3
    )
    x_record, y_record = ((20, 10) if reverse_record_order else (10, 20))
    x_event = _event(
        f"compressed_peer_x_{reverse_record_order}",
        x_key,
        "unknown_x",
        observation=x_o,
        effective_time=1,
        recorded_at=x_record,
        truth=TruthStatus.UNKNOWN,
        requirements=(Requirement(y_key, RequirementOp.ABSENT),),
    )
    y_event = _event(
        f"compressed_peer_y_{reverse_record_order}",
        y_key,
        "unknown_y",
        observation=y_o,
        effective_time=1,
        recorded_at=y_record,
        truth=TruthStatus.DISPUTED,
        requirements=(Requirement(x_key, RequirementOp.ABSENT),),
    )
    consumer = _event(
        f"compressed_peer_consumer_{reverse_record_order}",
        result_key,
        True,
        observation=consumer_o,
        effective_time=1,
        recorded_at=30,
        requirements=(Requirement(x_key, RequirementOp.ABSENT),),
    )
    ledger = _ledger(
        [(x_o, x_event), (y_o, y_event), (consumer_o, consumer)]
    )

    canonical = ledger.replay(valid_at=1)
    assert canonical.ambiguous_keys == (x_key, y_key)
    for key in (x_key, y_key):
        answer, _ = _compressed_answer(
            ledger,
            key,
            valid_at=1,
            known_at=99,
            expected_status=SolveStatus.INCOMPLETE,
        )
        assert answer is None
    consumer_answer, _ = _compressed_answer(
        ledger, result_key, valid_at=1, known_at=99
    )
    assert consumer_answer == canonical.value(result_key) is None


def test_equal_time_unordered_conflict_matches_canonical_replay() -> None:
    key = FactKey("seal", "owner")
    ari_o, bea_o = _observation("ari", 1), _observation("bea", 2)
    ari = _event(
        "ari",
        key,
        "Ari",
        observation=ari_o,
        effective_time=1,
        recorded_at=10,
    )
    bea = _event(
        "bea",
        key,
        "Bea",
        observation=bea_o,
        effective_time=1,
        recorded_at=20,
    )
    ledger = _ledger([(ari_o, ari), (bea_o, bea)])

    compressed, _ = _compressed_answer(
        ledger,
        key,
        valid_at=1,
        known_at=99,
        expected_status=SolveStatus.INCOMPLETE,
    )
    canonical = ledger.replay(valid_at=1)
    assert compressed == canonical.value(key) is None
    assert canonical.ambiguous_keys == (key,)


def test_unlicensed_supersession_matches_canonical_replay() -> None:
    key = FactKey("seal", "owner")
    ari_o, bea_o = _observation("ari", 1), _observation("bea", 2)
    ari = _event(
        "ari",
        key,
        "Ari",
        observation=ari_o,
        effective_time=1,
        recorded_at=10,
    )
    bea = _event(
        "bea",
        key,
        "Bea",
        observation=bea_o,
        effective_time=2,
        recorded_at=20,
    )
    ledger = _ledger([(ari_o, ari), (bea_o, bea)])

    compressed, _ = _compressed_answer(ledger, key, valid_at=2, known_at=99)
    assert compressed == ledger.replay(valid_at=2).value(key) == "Ari"


def test_claim_dependencies_are_preserved() -> None:
    base_key = FactKey("permit", "verified")
    derived_key = FactKey("sale", "allowed")
    base_o, derived_o = _observation("base", 1), _observation("derived", 2)
    base = _event(
        "base",
        base_key,
        True,
        observation=base_o,
        effective_time=1,
        recorded_at=10,
    )
    derived = _event(
        "derived",
        derived_key,
        True,
        observation=derived_o,
        effective_time=2,
        recorded_at=20,
        claim_dependencies=("c_base",),
        basis=EvidenceBasis.INFERRED,
        authority=Authority.DERIVED,
        derivation_rule_id="verified_permit_v1",
    )
    ledger = _ledger(
        [(base_o, base), (derived_o, derived)],
        policy=AuthorityPolicy(("verified_permit_v1",)),
    )

    compressed, view = _compressed_answer(
        ledger, derived_key, valid_at=2, known_at=99
    )
    assert compressed == ledger.replay(valid_at=2).value(derived_key) is True
    assert "component:event:e_base" in view.selected_component_ids


def test_causal_parent_orders_equal_time_writes() -> None:
    key = FactKey("seal", "owner")
    ari_o, bea_o = _observation("ari", 1), _observation("bea", 2)
    ari = _event(
        "ari",
        key,
        "Ari",
        observation=ari_o,
        effective_time=1,
        recorded_at=10,
    )
    bea = _event(
        "bea",
        key,
        "Bea",
        observation=bea_o,
        effective_time=1,
        recorded_at=20,
        causal_parents=("e_ari",),
        supersedes=("c_ari",),
    )
    ledger = _ledger([(ari_o, ari), (bea_o, bea)])

    compressed, _ = _compressed_answer(ledger, key, valid_at=1, known_at=99)
    canonical = ledger.replay(valid_at=1)
    assert compressed == canonical.value(key) == "Bea"
    assert canonical.ambiguous_keys == ()
