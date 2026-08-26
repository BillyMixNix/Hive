from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from hive_reference.demo import build_demo_ledger, build_demo_tasks
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
    canonical_json,
)
from hive_reference.representation import (
    ComponentKind,
    DeterministicReferenceSolver,
    ReferenceCompressor,
    RepresentationInvariantError,
    RepresentationRootCommitment,
    RepresentationVersion,
    SelectiveDecompressor,
    SolveStatus,
    TaskKind,
    TaskQuery,
    make_causal_rule_component,
)
from hive_reference.research import (
    DeterministicMissingDependencyProposer,
    ResearchInvariantError,
)


def _trusted_decompressor(
    representation: RepresentationVersion,
) -> SelectiveDecompressor:
    root = RepresentationRootCommitment.from_trusted_representation(representation)
    return SelectiveDecompressor((root,))


def _observation(name: str, recorded_at: int) -> Observation:
    return Observation.create(
        f"o_{name}",
        "representation_audit_fixture",
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
    op: EffectOp = EffectOp.SET,
    expected_previous=None,
    increment_by=None,
    valid_to: int | None = None,
    supersedes: tuple[str, ...] = (),
    requirements: tuple[Requirement, ...] = (),
    hard_dependencies: tuple[str, ...] = (),
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
        valid_to=valid_to,
        recorded_at=recorded_at,
        evidence=(evidence,),
        supersedes_claim_ids=supersedes,
    )
    return CanonicalEvent(
        event_id=f"e_{name}",
        event_type="audit_transition",
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
            ),
        ),
        claims=(claim,),
        causal_parents=(),
        hard_dependencies=hard_dependencies,
        evidence=(evidence,),
    )


def _append(ledger: EventLedger, observation: Observation, event: CanonicalEvent) -> None:
    ledger.append_observation(observation)
    ledger.append_event(event)


def test_plain_string_component_kind_cannot_evade_executable_contract() -> None:
    key = FactKey("typed_component", "value")
    observation = _observation("typed_component", 1)
    event = _event(
        "typed_component",
        key,
        "A",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    _append(ledger, observation, event)
    representation = ReferenceCompressor().compress(
        ledger, representation_id="typed-component"
    )
    transition = next(
        item
        for item in representation.components
        if item.component_kind is ComponentKind.TRANSITION
    )

    with pytest.raises(RepresentationInvariantError, match="ComponentKind"):
        replace(transition, component_kind="transition")


def test_selective_replay_includes_prior_plain_set_needed_to_reject_overwrite() -> None:
    owner = FactKey("seal", "owner")
    downstream = FactKey("coronation", "status")
    first_observation = _observation("first_owner", 1)
    overwrite_observation = _observation("unlicensed_overwrite", 2)
    downstream_observation = _observation("downstream", 3)
    first = _event(
        "first_owner",
        owner,
        "Ari",
        observation=first_observation,
        effective_time=1,
        recorded_at=10,
    )
    overwrite = _event(
        "unlicensed_overwrite",
        owner,
        "Bea",
        observation=overwrite_observation,
        effective_time=2,
        recorded_at=20,
    )
    dependent = _event(
        "downstream",
        downstream,
        "should-not-exist",
        observation=downstream_observation,
        effective_time=3,
        recorded_at=30,
        hard_dependencies=(overwrite.event_id,),
    )
    ledger = EventLedger()
    for observation, event in (
        (first_observation, first),
        (overwrite_observation, overwrite),
        (downstream_observation, dependent),
    ):
        _append(ledger, observation, event)

    canonical = ledger.replay(valid_at=3, known_at=30)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="audit-unlicensed-overwrite",
    )
    query = TaskQuery("q_downstream", TaskKind.VALUE_AT, (downstream,), 3, 30)
    view = _trusted_decompressor(representation).decompress(representation, query)
    outcome = DeterministicReferenceSolver().solve(view, query)

    overwrite_component = next(
        item
        for item in representation.components
        if item.component_id == "component:event:e_unlicensed_overwrite"
    )
    assert {tuple(sorted(item.items())) for item in overwrite_component.payload()["input_keys"]} == {
        (("predicate", owner.predicate), ("subject", owner.subject))
    }
    assert "component:event:e_first_owner" in view.selected_component_ids
    assert canonical.value(owner) == "Ari"
    assert canonical.value(downstream) is None
    assert outcome.status is SolveStatus.COMPLETE
    assert outcome.answer == canonical.value(downstream)


def test_ablated_prior_set_is_detected_from_full_source_manifest() -> None:
    owner = FactKey("seal", "owner")
    base_observation = _observation("manifest_base", 1)
    overwrite_observation = _observation("manifest_overwrite", 2)
    base = _event(
        "manifest_base",
        owner,
        "Ari",
        observation=base_observation,
        effective_time=1,
        recorded_at=10,
    )
    overwrite = _event(
        "manifest_overwrite",
        owner,
        "Bea",
        observation=overwrite_observation,
        effective_time=2,
        recorded_at=20,
    )
    ledger = EventLedger()
    _append(ledger, base_observation, base)
    _append(ledger, overwrite_observation, overwrite)
    full = ReferenceCompressor().compress(
        ledger,
        representation_id="manifest-full",
    )
    ablated = full.subset(
        ("component:event:e_manifest_overwrite",),
        representation_id="manifest-ablated",
    )
    query = TaskQuery("q_manifest_ablated", TaskKind.VALUE_AT, (owner,), 2, 20)

    view = _trusted_decompressor(ablated).decompress(ablated, query)
    outcome = DeterministicReferenceSolver().solve(view, query)

    assert (
        full.source_component_manifest_hash
        == ablated.source_component_manifest_hash
    )
    expected_packet_bytes = len(
        canonical_json(
            {
                "components": [asdict(item) for item in ablated.components],
                "source_component_manifest": [
                    item.to_mapping()
                    for item in ablated.source_component_manifest
                ],
                "source_component_manifest_hash": (
                    ablated.source_component_manifest_hash
                ),
            }
        ).encode("utf-8")
    )
    assert ablated.cost.packet_bytes == expected_packet_bytes
    assert "component:event:e_manifest_base" in view.missing_dependencies
    assert view.completeness is SolveStatus.INCOMPLETE
    assert outcome.status is SolveStatus.INCOMPLETE
    assert outcome.answer is None


def test_full_source_manifest_commitment_rejects_dual_ablation_attack() -> None:
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
    full = ReferenceCompressor().compress(
        ledger,
        representation_id="manifest-commitment-full",
        extra_components=(rule,),
    )
    query = build_demo_tasks(ledger.head_record_seq)[0].query
    full_outcome = DeterministicReferenceSolver().solve(
        _trusted_decompressor(full).decompress(full, query),
        query,
    )
    assert full_outcome.status is SolveStatus.COMPLETE
    assert full_outcome.answer == "Ari"

    removed_id = "component:event:e_inside"
    attacked_components = tuple(
        item for item in full.components if item.component_id != removed_id
    )
    attacked_manifest = tuple(
        item
        for item in full.source_component_manifest
        if item.component_id != removed_id
    )
    attacked_packet_bytes = RepresentationVersion.compute_packet_bytes(
        attacked_components,
        attacked_manifest,
        full.source_component_manifest_hash,
    )

    with pytest.raises(
        RepresentationInvariantError,
        match="sealed commitment",
    ):
        replace(
            full,
            representation_id="manifest-commitment-dual-ablation",
            components=attacked_components,
            source_component_manifest=attacked_manifest,
            cost=replace(full.cost, packet_bytes=attacked_packet_bytes),
        )

    attacked_manifest_hash = (
        RepresentationVersion.compute_source_component_manifest_hash(
            attacked_manifest
        )
    )
    cleared_commitment_packet_bytes = RepresentationVersion.compute_packet_bytes(
        attacked_components,
        attacked_manifest,
        attacked_manifest_hash,
    )
    with pytest.raises(
        RepresentationInvariantError,
        match="explicit normalized SHA-256 commitment",
    ):
        replace(
            full,
            representation_id="manifest-commitment-cleared-ablation",
            components=attacked_components,
            source_component_manifest=attacked_manifest,
            source_component_manifest_hash=None,
            cost=replace(
                full.cost,
                packet_bytes=cleared_commitment_packet_bytes,
            ),
        )

    # A candidate can make the reduced packet internally self-consistent by
    # committing to its own reduced manifest while retaining the original
    # ledger hash.  The packet-local commitment is not authority: a
    # decompressor sealed to the independently accepted original root rejects
    # it before selection or replay.
    forged = replace(
        full,
        representation_id="manifest-commitment-recomputed-ablation",
        components=attacked_components,
        source_component_manifest=attacked_manifest,
        source_component_manifest_hash=attacked_manifest_hash,
        cost=replace(
            full.cost,
            packet_bytes=cleared_commitment_packet_bytes,
        ),
    )
    original_root = RepresentationRootCommitment.from_trusted_representation(full)
    original_decompressor = SelectiveDecompressor((original_root,))
    forged_view = original_decompressor.decompress(forged, query)
    forged_outcome = DeterministicReferenceSolver().solve(forged_view, query)

    assert forged.source_ledger_hash == full.source_ledger_hash
    assert (
        forged.source_component_manifest_hash
        != full.source_component_manifest_hash
    )
    assert forged_view.completeness is SolveStatus.INCOMPLETE
    assert forged_view.missing_dependencies == ("untrusted_representation_root",)
    assert forged_view.selected_components == ()
    assert forged_outcome.status is SolveStatus.INCOMPLETE
    assert forged_outcome.answer is None


def test_subset_rejects_unknown_component_ids() -> None:
    observation = _observation("subset_known", 1)
    event = _event(
        "subset_known",
        FactKey("seal", "owner"),
        "Ari",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    _append(ledger, observation, event)
    full = ReferenceCompressor().compress(
        ledger,
        representation_id="subset-known-full",
    )

    with pytest.raises(RepresentationInvariantError, match="unknown component IDs"):
        full.subset(
            (
                "component:event:e_subset_known",
                "component:event:e_missing",
            )
        )


def test_manifest_does_not_require_same_time_producer_before_known_at() -> None:
    owner = FactKey("seal", "owner")
    early_observation = _observation("known_early", 1)
    late_observation = _observation("known_late", 2)
    early = _event(
        "known_early",
        owner,
        "Ari",
        observation=early_observation,
        effective_time=1,
        recorded_at=10,
    )
    late_peer = _event(
        "known_late",
        owner,
        "Bea",
        observation=late_observation,
        effective_time=1,
        recorded_at=20,
    )
    ledger = EventLedger()
    _append(ledger, early_observation, early)
    _append(ledger, late_observation, late_peer)
    full = ReferenceCompressor().compress(
        ledger,
        representation_id="known-at-full",
    )
    without_late_peer = full.subset(
        ("component:event:e_known_early",),
        representation_id="known-at-subset",
    )

    early_query = TaskQuery("q_known_early", TaskKind.VALUE_AT, (owner,), 1, 15)
    early_view = _trusted_decompressor(without_late_peer).decompress(
        without_late_peer, early_query
    )
    early_outcome = DeterministicReferenceSolver().solve(early_view, early_query)
    assert early_view.completeness is SolveStatus.COMPLETE
    assert "component:event:e_known_late" not in early_view.missing_dependencies
    assert early_outcome.answer == "Ari"

    late_query = replace(early_query, query_id="q_known_late", known_at=20)
    late_view = _trusted_decompressor(without_late_peer).decompress(
        without_late_peer, late_query
    )
    late_outcome = DeterministicReferenceSolver().solve(late_view, late_query)
    assert "component:event:e_known_late" in late_view.missing_dependencies
    assert late_view.completeness is SolveStatus.INCOMPLETE
    assert late_outcome.status is SolveStatus.INCOMPLETE


def test_manifest_detects_ablated_later_writer_for_direct_state_query() -> None:
    owner = FactKey("seal", "owner")
    early_observation = _observation("later_writer_base", 1)
    late_observation = _observation("later_writer_update", 2)
    early = _event(
        "later_writer_base",
        owner,
        "Ari",
        observation=early_observation,
        effective_time=1,
        recorded_at=10,
    )
    late = _event(
        "later_writer_update",
        owner,
        "Bea",
        observation=late_observation,
        effective_time=4,
        recorded_at=20,
        expected_previous="Ari",
    )
    ledger = EventLedger()
    _append(ledger, early_observation, early)
    _append(ledger, late_observation, late)
    full = ReferenceCompressor().compress(
        ledger,
        representation_id="later-writer-full",
    )
    stale_subset = full.subset(
        ("component:event:e_later_writer_base",),
        representation_id="later-writer-ablated",
    )
    query = TaskQuery("q_later_writer", TaskKind.VALUE_AT, (owner,), 5, 20)

    view = _trusted_decompressor(stale_subset).decompress(stale_subset, query)
    outcome = DeterministicReferenceSolver().solve(view, query)

    assert ledger.replay(valid_at=5, known_at=20).value(owner) == "Bea"
    assert "component:event:e_later_writer_update" in view.missing_dependencies
    assert view.completeness is SolveStatus.INCOMPLETE
    assert outcome.status is SolveStatus.INCOMPLETE
    assert outcome.answer is None


@pytest.mark.parametrize(
    "component_kind",
    (ComponentKind.TRANSITION, ComponentKind.CONSTRAINT),
)
def test_compressor_rejects_malformed_executable_extra_component(
    component_kind: ComponentKind,
) -> None:
    key = FactKey("seal", "owner")
    observation = _observation("malformed_extra", 1)
    event = _event(
        "malformed_extra",
        key,
        "Ari",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    _append(ledger, observation, event)
    generated = ReferenceCompressor().compress(ledger, representation_id="generated")
    malformed = replace(
        generated.components[0],
        component_id="component:injected:malformed",
        component_kind=component_kind,
        payload_json="{}",
    )

    with pytest.raises(RepresentationInvariantError, match="cannot inject executable"):
        ReferenceCompressor().compress(
            ledger,
            representation_id="malformed-injection",
            extra_components=(malformed,),
        )


def test_compressor_rejects_fake_mallory_transition_extra_component() -> None:
    key = FactKey("seal", "owner")
    observation = _observation("mallory_extra", 1)
    event = _event(
        "mallory_extra",
        key,
        "Ari",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    _append(ledger, observation, event)
    generated = ReferenceCompressor().compress(ledger, representation_id="generated")
    payload = dict(generated.components[0].payload())
    payload["event_id"] = "e_fake_mallory"
    payload["effects"] = [dict(payload["effects"][0], value="Mallory")]
    fake = replace(
        generated.components[0],
        component_id="component:event:e_fake_mallory",
        payload_json=canonical_json(payload),
    )

    with pytest.raises(RepresentationInvariantError, match="cannot inject executable"):
        ReferenceCompressor().compress(
            ledger,
            representation_id="mallory-injection",
            extra_components=(fake,),
        )


def test_same_time_set_delete_conflict_matches_canonical_replay() -> None:
    owner = FactKey("seal", "owner")
    base_observation = _observation("conflict_base", 1)
    set_observation = _observation("conflict_set", 2)
    delete_observation = _observation("conflict_delete", 3)
    base = _event(
        "conflict_base",
        owner,
        "Ari",
        observation=base_observation,
        effective_time=1,
        recorded_at=10,
    )
    simultaneous_set = _event(
        "conflict_set",
        owner,
        "Bea",
        observation=set_observation,
        effective_time=2,
        recorded_at=20,
        expected_previous="Ari",
    )
    simultaneous_delete = _event(
        "conflict_delete",
        owner,
        None,
        observation=delete_observation,
        effective_time=2,
        recorded_at=30,
        op=EffectOp.DELETE,
        expected_previous="Ari",
    )
    ledger = EventLedger()
    for observation, event in (
        (base_observation, base),
        (set_observation, simultaneous_set),
        (delete_observation, simultaneous_delete),
    ):
        _append(ledger, observation, event)

    canonical = ledger.replay(valid_at=2, known_at=30)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="audit-set-delete-conflict",
    )
    query = TaskQuery("q_conflict", TaskKind.VALUE_AT, (owner,), 2, 30)
    view = _trusted_decompressor(representation).decompress(representation, query)
    outcome = DeterministicReferenceSolver().solve(view, query)

    assert canonical.value(owner) is None
    assert canonical.ambiguous_keys == (owner,)
    assert outcome.status is SolveStatus.INCOMPLETE
    assert outcome.failure_reason == "ambiguous_state"
    assert outcome.answer == canonical.value(owner)


def test_inapplicable_same_time_peer_does_not_create_compressed_conflict() -> None:
    owner = FactKey("seal", "owner")
    gate = FactKey("gate", "open")
    base_observation = _observation("eligible_base", 1)
    set_observation = _observation("eligible_set", 2)
    blocked_observation = _observation("blocked_delete", 3)
    base = _event(
        "eligible_base",
        owner,
        "Ari",
        observation=base_observation,
        effective_time=1,
        recorded_at=10,
    )
    eligible_set = _event(
        "eligible_set",
        owner,
        "Bea",
        observation=set_observation,
        effective_time=2,
        recorded_at=20,
        expected_previous="Ari",
    )
    blocked_delete = _event(
        "blocked_delete",
        owner,
        None,
        observation=blocked_observation,
        effective_time=2,
        recorded_at=30,
        op=EffectOp.DELETE,
        expected_previous="Ari",
        requirements=(Requirement(gate, RequirementOp.EQ, True),),
    )
    ledger = EventLedger()
    for observation, event in (
        (base_observation, base),
        (set_observation, eligible_set),
        (blocked_observation, blocked_delete),
    ):
        _append(ledger, observation, event)

    canonical = ledger.replay(valid_at=2, known_at=30)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="audit-inapplicable-peer",
    )
    query = TaskQuery("q_inapplicable", TaskKind.VALUE_AT, (owner,), 2, 30)
    view = _trusted_decompressor(representation).decompress(representation, query)
    outcome = DeterministicReferenceSolver().solve(view, query)

    assert canonical.value(owner) == "Bea"
    assert canonical.ambiguous_keys == ()
    assert outcome.status is SolveStatus.COMPLETE
    assert outcome.answer == canonical.value(owner)


def test_same_stage_peer_uses_shared_pre_stage_state() -> None:
    source = FactKey("seal", "owner")
    result = FactKey("audit", "peer_result")
    observations = {
        name: _observation(name, index)
        for index, name in enumerate(
            ("stage_base", "stage_left", "stage_right", "stage_consumer"),
            start=1,
        )
    }
    base = _event(
        "stage_base",
        source,
        "Prior",
        observation=observations["stage_base"],
        effective_time=1,
        recorded_at=10,
    )
    left = _event(
        "stage_left",
        source,
        "Ari",
        observation=observations["stage_left"],
        effective_time=2,
        recorded_at=20,
        expected_previous="Prior",
    )
    right = _event(
        "stage_right",
        source,
        "Bea",
        observation=observations["stage_right"],
        effective_time=2,
        recorded_at=30,
        expected_previous="Prior",
    )
    consumer = _event(
        "stage_consumer",
        result,
        "applied",
        observation=observations["stage_consumer"],
        effective_time=2,
        recorded_at=40,
        requirements=(Requirement(source, RequirementOp.EQ, "Prior"),),
    )
    ledger = EventLedger()
    for event in (base, left, right, consumer):
        _append(ledger, observations[event.event_id.removeprefix("e_")], event)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="shared-pre-stage-state",
    )
    query = TaskQuery("q_stage_peer", TaskKind.VALUE_AT, (result,), 2, 40)

    outcome = DeterministicReferenceSolver().solve(
        _trusted_decompressor(representation).decompress(representation, query),
        query,
    )
    assert outcome.status is SolveStatus.COMPLETE
    assert outcome.answer == "applied"


def test_ambiguity_does_not_satisfy_absent_can_apply_requirement() -> None:
    owner = FactKey("seal", "owner")
    result = FactKey("coronation", "status")
    left_observation = _observation("absent_left", 1)
    right_observation = _observation("absent_right", 2)
    target_observation = _observation("absent_target", 3)
    left = _event(
        "absent_left",
        owner,
        "Ari",
        observation=left_observation,
        effective_time=1,
        recorded_at=10,
    )
    right = _event(
        "absent_right",
        owner,
        "Bea",
        observation=right_observation,
        effective_time=1,
        recorded_at=20,
    )
    target = _event(
        "absent_target",
        result,
        "admitted",
        observation=target_observation,
        effective_time=2,
        recorded_at=30,
        requirements=(Requirement(owner, RequirementOp.ABSENT),),
    )
    ledger = EventLedger()
    for observation, event in (
        (left_observation, left),
        (right_observation, right),
        (target_observation, target),
    ):
        _append(ledger, observation, event)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="ambiguity-is-not-absence",
    )
    query = TaskQuery(
        "q_ambiguity_can_apply",
        TaskKind.CAN_APPLY,
        (owner,),
        2,
        30,
        canonical_json({"event_id": target.event_id}),
    )

    canonical = ledger.replay(valid_at=2, known_at=30)
    view = _trusted_decompressor(representation).decompress(representation, query)
    outcome = DeterministicReferenceSolver().solve(view, query)

    target_decision = next(
        item for item in canonical.decisions if item.event_id == target.event_id
    )
    assert target_decision.reason == "precondition_failed"
    assert outcome.status is SolveStatus.INCOMPLETE
    assert outcome.failure_reason == "ambiguous_state"
    assert outcome.answer is None


def test_ambiguous_changes_query_fails_closed() -> None:
    owner = FactKey("seal", "owner")
    left_observation = _observation("changes_left", 1)
    right_observation = _observation("changes_right", 2)
    left = _event(
        "changes_left",
        owner,
        "Ari",
        observation=left_observation,
        effective_time=1,
        recorded_at=10,
    )
    right = _event(
        "changes_right",
        owner,
        "Bea",
        observation=right_observation,
        effective_time=1,
        recorded_at=20,
    )
    ledger = EventLedger()
    _append(ledger, left_observation, left)
    _append(ledger, right_observation, right)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="ambiguous-changes",
    )
    query = TaskQuery(
        "q_ambiguous_changes",
        TaskKind.CHANGES,
        (owner,),
        1,
        20,
        canonical_json({"from_time": 0, "to_time": 1}),
    )

    outcome = DeterministicReferenceSolver().solve(
        _trusted_decompressor(representation).decompress(representation, query),
        query,
    )
    assert outcome.status is SolveStatus.INCOMPLETE
    assert outcome.answer is None
    assert outcome.failure_reason == "ambiguous_state"


def test_derived_owner_traversal_fails_on_ambiguous_intermediate_key() -> None:
    inside = FactKey("gem", "inside")
    owner = FactKey("chest", "owner")
    inside_observation = _observation("derived_inside", 1)
    left_observation = _observation("derived_owner_left", 2)
    right_observation = _observation("derived_owner_right", 3)
    inside_event = _event(
        "derived_inside",
        inside,
        "chest",
        observation=inside_observation,
        effective_time=1,
        recorded_at=10,
    )
    left = _event(
        "derived_owner_left",
        owner,
        "Ari",
        observation=left_observation,
        effective_time=1,
        recorded_at=20,
    )
    right = _event(
        "derived_owner_right",
        owner,
        "Bea",
        observation=right_observation,
        effective_time=1,
        recorded_at=30,
    )
    ledger = EventLedger()
    for observation, event in (
        (inside_observation, inside_event),
        (left_observation, left),
        (right_observation, right),
    ):
        _append(ledger, observation, event)
    rule = make_causal_rule_component(
        component_id="component:rule:derived-owner-audit",
        keys=(inside, owner),
        rule_id="containment_owner_v1",
        rule="contained item inherits effective owner from container",
        source_event_ids=(inside_event.event_id, left.event_id),
        evidence=(
            EvidenceRef.from_observation(inside_observation),
            EvidenceRef.from_observation(left_observation),
        ),
        available_from_record=30,
    )
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="ambiguous-derived-owner",
        extra_components=(rule,),
    )
    query = TaskQuery(
        "q_ambiguous_derived_owner",
        TaskKind.VALUE_AT,
        (inside, owner),
        1,
        30,
        canonical_json(
            {
                "derive": "owner_through_containment",
                "item": "gem",
                "rule_id": "containment_owner_v1",
            }
        ),
    )

    outcome = DeterministicReferenceSolver().solve(
        _trusted_decompressor(representation).decompress(representation, query),
        query,
    )
    assert outcome.status is SolveStatus.INCOMPLETE
    assert outcome.answer is None
    assert outcome.failure_reason == "ambiguous_state"


def test_expired_conflict_restores_prior_cell_in_compressed_replay() -> None:
    owner = FactKey("seal", "owner")
    base_observation = _observation("restore_base", 1)
    left_observation = _observation("restore_left", 2)
    right_observation = _observation("restore_right", 3)
    base = _event(
        "restore_base",
        owner,
        "Original",
        observation=base_observation,
        effective_time=1,
        recorded_at=10,
    )
    left = _event(
        "restore_left",
        owner,
        "Ari",
        observation=left_observation,
        effective_time=2,
        recorded_at=20,
        expected_previous="Original",
        valid_to=4,
    )
    right = _event(
        "restore_right",
        owner,
        "Bea",
        observation=right_observation,
        effective_time=2,
        recorded_at=30,
        expected_previous="Original",
        valid_to=4,
    )
    ledger = EventLedger()
    for observation, event in (
        (base_observation, base),
        (left_observation, left),
        (right_observation, right),
    ):
        _append(ledger, observation, event)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="conflict-expiry-restoration",
    )

    for valid_at, expected, status in (
        (3, None, SolveStatus.INCOMPLETE),
        (5, "Original", SolveStatus.COMPLETE),
    ):
        query = TaskQuery(
            f"q_restore_{valid_at}",
            TaskKind.VALUE_AT,
            (owner,),
            valid_at,
            30,
        )
        outcome = DeterministicReferenceSolver().solve(
            _trusted_decompressor(representation).decompress(representation, query),
            query,
        )
        canonical = ledger.replay(valid_at=valid_at, known_at=30)
        assert outcome.status is status
        assert outcome.answer == canonical.value(owner) == expected


def test_same_value_different_validity_is_a_compressed_conflict() -> None:
    owner = FactKey("seal", "owner")
    finite_observation = _observation("validity_finite", 1)
    durable_observation = _observation("validity_durable", 2)
    finite = _event(
        "validity_finite",
        owner,
        "Ari",
        observation=finite_observation,
        effective_time=1,
        recorded_at=10,
        valid_to=3,
    )
    durable = _event(
        "validity_durable",
        owner,
        "Ari",
        observation=durable_observation,
        effective_time=1,
        recorded_at=20,
    )
    ledger = EventLedger()
    _append(ledger, finite_observation, finite)
    _append(ledger, durable_observation, durable)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="same-value-validity-conflict",
    )
    query = TaskQuery("q_validity_conflict", TaskKind.VALUE_AT, (owner,), 1, 20)

    canonical = ledger.replay(valid_at=1, known_at=20)
    outcome = DeterministicReferenceSolver().solve(
        _trusted_decompressor(representation).decompress(representation, query),
        query,
    )
    assert canonical.ambiguous_keys == (owner,)
    assert outcome.status is SolveStatus.INCOMPLETE
    assert outcome.failure_reason == "ambiguous_state"
    assert outcome.answer == canonical.value(owner) is None


def test_only_applied_full_superseder_resolves_compressed_ambiguity() -> None:
    owner = FactKey("seal", "owner")
    gate = FactKey("gate", "open")
    observations = {
        name: _observation(name, index)
        for index, name in enumerate(
            ("resolver_left", "resolver_right", "resolver_blocked", "resolver_valid"),
            start=1,
        )
    }
    left = _event(
        "resolver_left",
        owner,
        "Ari",
        observation=observations["resolver_left"],
        effective_time=1,
        recorded_at=10,
    )
    right = _event(
        "resolver_right",
        owner,
        "Bea",
        observation=observations["resolver_right"],
        effective_time=1,
        recorded_at=20,
    )
    blocked = _event(
        "resolver_blocked",
        owner,
        "Mallory",
        observation=observations["resolver_blocked"],
        effective_time=2,
        recorded_at=30,
        supersedes=("c_resolver_left", "c_resolver_right"),
        requirements=(Requirement(gate, RequirementOp.EQ, True),),
    )
    resolver = _event(
        "resolver_valid",
        owner,
        "Cato",
        observation=observations["resolver_valid"],
        effective_time=3,
        recorded_at=40,
        supersedes=("c_resolver_left", "c_resolver_right"),
    )
    ledger = EventLedger()
    for event in (left, right, blocked, resolver):
        _append(ledger, observations[event.event_id.removeprefix("e_")], event)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="applied-resolver-only",
    )

    for valid_at, expected, status in (
        (2, None, SolveStatus.INCOMPLETE),
        (3, "Cato", SolveStatus.COMPLETE),
    ):
        query = TaskQuery(
            f"q_resolver_{valid_at}",
            TaskKind.VALUE_AT,
            (owner,),
            valid_at,
            40,
        )
        canonical = ledger.replay(valid_at=valid_at, known_at=40)
        outcome = DeterministicReferenceSolver().solve(
            _trusted_decompressor(representation).decompress(representation, query),
            query,
        )
        assert outcome.status is status
        assert outcome.answer == canonical.value(owner) == expected


def test_increment_payload_uses_explicit_delta_and_result() -> None:
    count = FactKey("treasury", "coins")
    base_observation = _observation("increment_base", 1)
    increment_observation = _observation("increment_result", 2)
    base = _event(
        "increment_base",
        count,
        10,
        observation=base_observation,
        effective_time=1,
        recorded_at=10,
    )
    increment = _event(
        "increment_result",
        count,
        13,
        observation=increment_observation,
        effective_time=2,
        recorded_at=20,
        op=EffectOp.INCREMENT,
        expected_previous=10,
        increment_by=3,
    )
    ledger = EventLedger()
    _append(ledger, base_observation, base)
    _append(ledger, increment_observation, increment)
    representation = ReferenceCompressor().compress(
        ledger,
        representation_id="increment-result-binding",
    )
    query = TaskQuery("q_increment", TaskKind.VALUE_AT, (count,), 2, 20)

    increment_payload = next(
        component.payload()
        for component in representation.components
        if component.component_id == "component:event:e_increment_result"
    )["effects"][0]
    outcome = DeterministicReferenceSolver().solve(
        _trusted_decompressor(representation).decompress(representation, query),
        query,
    )
    assert increment_payload["increment_by"] == 3
    assert increment_payload["value"] == 13
    assert outcome.status is SolveStatus.COMPLETE
    assert outcome.answer == ledger.replay(valid_at=2, known_at=20).value(count) == 13


@pytest.mark.parametrize(
    "field",
    ("source_ledger_hash", "family_id", "schema_id", "codec_id"),
)
def test_missing_dependency_proposer_rejects_incompatible_repair_source(field: str) -> None:
    key = FactKey("seal", "owner")
    observation = _observation("source", 1)
    event = _event(
        "source",
        key,
        "Ari",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    _append(ledger, observation, event)
    full = ReferenceCompressor().compress(ledger, representation_id="full")
    missing_id = "component:event:e_source"
    parent = full.subset((), representation_id="parent")
    source = replace(full, representation_id="foreign-source", **{field: f"foreign-{field}"})

    with pytest.raises(ResearchInvariantError, match=field):
        DeterministicMissingDependencyProposer().propose(
            parent,
            source,
            missing_component_id=missing_id,
            candidate_id="candidate",
        )


def test_missing_dependency_proposer_retains_sealed_source_manifest() -> None:
    key = FactKey("seal", "owner")
    observation = _observation("sealed_repair_source", 1)
    event = _event(
        "sealed_repair_source",
        key,
        "Ari",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    _append(ledger, observation, event)
    source = ReferenceCompressor().compress(
        ledger,
        representation_id="sealed-repair-source",
    )
    parent = source.subset((), representation_id="sealed-repair-parent")

    candidate, _ = DeterministicMissingDependencyProposer().propose(
        parent,
        source,
        missing_component_id="component:event:e_sealed_repair_source",
        candidate_id="sealed-repair-candidate",
    )

    assert candidate.source_component_manifest == parent.source_component_manifest
    assert (
        candidate.source_component_manifest_hash
        == parent.source_component_manifest_hash
        == source.source_component_manifest_hash
    )


def test_missing_dependency_proposer_cannot_launder_foreign_component_provenance() -> None:
    parent_key = FactKey("parent", "state")
    foreign_key = FactKey("foreign", "state")
    parent_observation = _observation("parent", 1)
    foreign_observation = _observation("foreign", 2)
    parent_event = _event(
        "parent",
        parent_key,
        "local",
        observation=parent_observation,
        effective_time=1,
        recorded_at=10,
    )
    foreign_event = _event(
        "foreign",
        foreign_key,
        "external",
        observation=foreign_observation,
        effective_time=1,
        recorded_at=20,
    )
    parent_ledger = EventLedger()
    foreign_ledger = EventLedger()
    _append(parent_ledger, parent_observation, parent_event)
    _append(foreign_ledger, foreign_observation, foreign_event)
    parent = ReferenceCompressor().compress(parent_ledger, representation_id="parent")
    foreign_source = ReferenceCompressor().compress(
        foreign_ledger,
        representation_id="foreign-source",
    )

    with pytest.raises(ResearchInvariantError, match="foreign provenance.*source_ledger_hash"):
        DeterministicMissingDependencyProposer().propose(
            parent,
            foreign_source,
            missing_component_id="component:event:e_foreign",
            candidate_id="laundered-candidate",
        )

    header_laundered = replace(
        foreign_source,
        source_ledger_hash=parent.source_ledger_hash,
        family_id=parent.family_id,
        schema_id=parent.schema_id,
        codec_id=parent.codec_id,
    )
    with pytest.raises(ResearchInvariantError, match="component manifest mismatch"):
        DeterministicMissingDependencyProposer().propose(
            parent,
            header_laundered,
            missing_component_id="component:event:e_foreign",
            candidate_id="header-laundered-candidate",
        )

    with pytest.raises(
        RepresentationInvariantError,
        match="sealed commitment",
    ):
        replace(
            header_laundered,
            source_component_manifest=parent.source_component_manifest,
        )


def test_representation_rejects_component_changed_under_trusted_manifest() -> None:
    key = FactKey("seal", "owner")
    observation = _observation("trusted_source", 1)
    event = _event(
        "trusted_source",
        key,
        "Ari",
        observation=observation,
        effective_time=1,
        recorded_at=10,
    )
    ledger = EventLedger()
    _append(ledger, observation, event)
    full = ReferenceCompressor().compress(ledger, representation_id="trusted-full")
    component = full.components[0]
    payload = dict(component.payload())
    payload["effects"] = [dict(payload["effects"][0], value="Mallory")]
    changed_component = replace(
        component,
        payload_json=canonical_json(payload),
    )
    with pytest.raises(RepresentationInvariantError, match="trusted manifest entries"):
        replace(
            full,
            representation_id="changed-source",
            components=(changed_component,),
        )
    with pytest.raises(RepresentationInvariantError, match="explicit trusted"):
        replace(
            full,
            representation_id="self-attested-source",
            source_component_manifest=(),
        )
