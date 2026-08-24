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
    requirements: tuple[Requirement, ...] = (),
    hard_dependencies: tuple[str, ...] = (),
    causal_parents: tuple[str, ...] = (),
    claim_dependencies: tuple[str, ...] = (),
    supersedes: tuple[str, ...] = (),
    basis: EvidenceBasis = EvidenceBasis.OBSERVED,
    authority: Authority = Authority.CANONICAL,
    derivation_rule_id: str | None = None,
) -> CanonicalEvent:
    evidence = EvidenceRef.from_observation(observation)
    claim = ClaimRevision(
        claim_id=f"c_{name}",
        key=key,
        value=value,
        basis=basis,
        truth=TruthStatus.ACCEPTED,
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
                op=EffectOp.SET,
                value=value,
                expected_previous=expected_previous,
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
    view = SelectiveDecompressor().decompress(representation, query)
    outcome = DeterministicReferenceSolver().solve(view, query)
    assert outcome.status is SolveStatus.COMPLETE
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

    compressed, _ = _compressed_answer(ledger, key, valid_at=1, known_at=99)
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
