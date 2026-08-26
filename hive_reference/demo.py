"""Cheap deterministic whole-system Hive reference demonstration."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Sequence

from hive_reference.model import (
    Authority,
    CanonicalEvent,
    ClaimRevision,
    EdgeKind,
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
    sha256_text,
)
from hive_reference.representation import (
    DeterministicReferenceSolver,
    ReferenceCompressor,
    RepresentationAblator,
    RepresentationEvaluator,
    RepresentationRootCommitment,
    SelectiveDecompressor,
    TaskExpectation,
    TaskKind,
    TaskQuery,
    ValidationStatus,
    make_causal_rule_component,
)
from hive_reference.research import (
    DeterministicMissingDependencyProposer,
    EvidenceRegistry,
    RepresentationRegistry,
    RepresentationRepairGate,
)


def _observation(
    observation_id: str,
    record_seq: int,
    text: str,
    *,
    source: str = "demo_registry",
) -> Observation:
    return Observation.create(
        observation_id,
        source,
        record_seq,
        {"text": text},
        provenance=("hive_reference_demo_fixture_v1",),
    )


def _claim(
    claim_id: str,
    key: FactKey,
    value: Any,
    *,
    evidence: EvidenceRef,
    effective: int,
    record_seq: int,
    basis: EvidenceBasis = EvidenceBasis.OBSERVED,
    truth: TruthStatus = TruthStatus.ACCEPTED,
    authority: Authority = Authority.CANONICAL,
    depends_on: Sequence[str] = (),
    supersedes: Sequence[str] = (),
) -> ClaimRevision:
    return ClaimRevision(
        claim_id=claim_id,
        key=key,
        value=value,
        basis=basis,
        truth=truth,
        authority=authority,
        valid_from=effective,
        valid_to=None,
        recorded_at=record_seq,
        evidence=(evidence,),
        depends_on_claim_ids=tuple(depends_on),
        supersedes_claim_ids=tuple(supersedes),
        confidence=1.0,
    )


def _event(
    event_id: str,
    event_type: str,
    effective: int,
    record_seq: int,
    claim: ClaimRevision,
    *,
    effect: StateEffect,
    evidence: EvidenceRef,
    requirements: Sequence[Requirement] = (),
    hard_dependencies: Sequence[str] = (),
    causal_parents: Sequence[str] = (),
    edges: Sequence[tuple[EdgeKind, str]] = (),
) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        event_type=event_type,
        effective_time=effective,
        recorded_at=record_seq,
        entities=(claim.key.subject,),
        requirements=tuple(requirements),
        effects=(effect,),
        claims=(claim,),
        causal_parents=tuple(causal_parents),
        hard_dependencies=tuple(hard_dependencies),
        evidence=(evidence,),
        edges=tuple(edges),
    )


def build_demo_ledger() -> tuple[EventLedger, dict[str, EvidenceRef]]:
    """Hand-canonicalize the fixture; this intentionally does not claim NLP."""

    descriptions = {
        "o_owner": "At T1 the registry records that Ari owns the chest.",
        "o_inside": "At T1 the registry records that the gem is inside the chest.",
        "o_plan": "At T2 Ari plans to sell the chest to Bea.",
        "o_intent": "At T2 the observed intention is Ari intends to transfer the chest to Bea.",
        "o_transfer": "At T3 the registry completes a chest transfer from Ari to Cato.",
        "o_claim": "At T3 an untrusted caller claims Bea owns the chest.",
        "o_sale": "At T4 Bea attempts to sell the chest to Dana.",
        "o_color": "The chest is red.",
    }
    observations = {
        name: _observation(name, index + 1, text)
        for index, (name, text) in enumerate(descriptions.items())
    }
    refs = {name: EvidenceRef.from_observation(value) for name, value in observations.items()}
    ledger = EventLedger()
    for observation in observations.values():
        ledger.append_observation(observation)

    owner = FactKey("chest", "owner")
    inside = FactKey("gem", "inside")
    intent = FactKey("ari", "intends_transfer_chest_to")
    color = FactKey("chest", "color")

    c_owner_ari = _claim("c_owner_ari", owner, "Ari", evidence=refs["o_owner"], effective=1, record_seq=10)
    ledger.append_event(
        _event(
            "e_owner_ari",
            "ownership_created",
            1,
            10,
            c_owner_ari,
            effect=StateEffect(c_owner_ari.claim_id, owner, EffectOp.SET, "Ari"),
            evidence=refs["o_owner"],
        )
    )

    c_inside = _claim("c_inside", inside, "chest", evidence=refs["o_inside"], effective=1, record_seq=11)
    ledger.append_event(
        _event(
            "e_inside",
            "containment_created",
            1,
            11,
            c_inside,
            effect=StateEffect(c_inside.claim_id, inside, EffectOp.SET, "chest"),
            evidence=refs["o_inside"],
            edges=((EdgeKind.CONTAINS, "chest"),),
        )
    )

    c_plan = _claim(
        "c_plan_owner_bea",
        owner,
        "Bea",
        evidence=refs["o_plan"],
        effective=2,
        record_seq=20,
        basis=EvidenceBasis.PLANNED,
        authority=Authority.MODEL,
    )
    ledger.append_event(
        _event(
            "e_plan_transfer",
            "planned_transfer",
            2,
            20,
            c_plan,
            effect=StateEffect(c_plan.claim_id, owner, EffectOp.SET, "Bea", "Ari"),
            evidence=refs["o_plan"],
        )
    )

    c_intent = _claim(
        "c_intent_bea",
        intent,
        "Bea",
        evidence=refs["o_intent"],
        effective=2,
        record_seq=21,
    )
    ledger.append_event(
        _event(
            "e_observed_intent",
            "observed_intent",
            2,
            21,
            c_intent,
            effect=StateEffect(c_intent.claim_id, intent, EffectOp.SET, "Bea"),
            evidence=refs["o_intent"],
        )
    )

    c_owner_cato = _claim(
        "c_owner_cato",
        owner,
        "Cato",
        evidence=refs["o_transfer"],
        effective=3,
        record_seq=30,
        depends_on=(c_owner_ari.claim_id,),
        supersedes=(c_owner_ari.claim_id,),
    )
    ledger.append_event(
        _event(
            "e_transfer_cato",
            "completed_transfer",
            3,
            30,
            c_owner_cato,
            effect=StateEffect(c_owner_cato.claim_id, owner, EffectOp.SET, "Cato", "Ari"),
            evidence=refs["o_transfer"],
            requirements=(Requirement(owner, RequirementOp.EQ, "Ari"),),
            hard_dependencies=("e_owner_ari",),
            causal_parents=("e_owner_ari",),
            edges=((EdgeKind.SUPERSEDES, c_owner_ari.claim_id),),
        )
    )

    c_disputed = _claim(
        "c_disputed_bea",
        owner,
        "Bea",
        evidence=refs["o_claim"],
        effective=3,
        record_seq=31,
        truth=TruthStatus.DISPUTED,
        authority=Authority.EXTERNAL,
    )
    ledger.append_event(
        _event(
            "e_disputed_claim",
            "external_claim",
            3,
            31,
            c_disputed,
            effect=StateEffect(c_disputed.claim_id, owner, EffectOp.SET, "Bea", "Ari"),
            evidence=refs["o_claim"],
        )
    )

    c_sale = _claim(
        "c_owner_dana",
        owner,
        "Dana",
        evidence=refs["o_sale"],
        effective=4,
        record_seq=40,
        depends_on=(c_owner_cato.claim_id,),
    )
    ledger.append_event(
        _event(
            "e_bea_sale_attempt",
            "attempted_sale",
            4,
            40,
            c_sale,
            effect=StateEffect(c_sale.claim_id, owner, EffectOp.SET, "Dana", "Bea"),
            evidence=refs["o_sale"],
            requirements=(Requirement(owner, RequirementOp.EQ, "Bea"),),
            causal_parents=("e_transfer_cato",),
            edges=((EdgeKind.PRECONDITION, owner.text),),
        )
    )

    c_color = _claim("c_color", color, "red", evidence=refs["o_color"], effective=1, record_seq=41)
    ledger.append_event(
        _event(
            "e_color",
            "descriptive_fact",
            1,
            41,
            c_color,
            effect=StateEffect(c_color.claim_id, color, EffectOp.SET, "red"),
            evidence=refs["o_color"],
        )
    )
    return ledger, refs


def build_demo_tasks(known_at: int) -> tuple[TaskExpectation, ...]:
    owner = FactKey("chest", "owner")
    inside = FactKey("gem", "inside")
    causal_params = canonical_json(
        {"derive": "owner_through_containment", "item": "gem", "rule_id": "containment_owner_v1"}
    )
    return (
        TaskExpectation(TaskQuery("q_gem_owner_t2", TaskKind.VALUE_AT, (inside, owner), 2, known_at, causal_params), "Ari"),
        TaskExpectation(TaskQuery("q_gem_owner_t4", TaskKind.VALUE_AT, (inside, owner), 4, known_at, causal_params), "Cato"),
        TaskExpectation(
            TaskQuery(
                "q_bea_can_sell",
                TaskKind.CAN_APPLY,
                (owner,),
                4,
                known_at,
                canonical_json({"event_id": "e_bea_sale_attempt"}),
            ),
            False,
        ),
        TaskExpectation(
            TaskQuery(
                "q_plan_rejected",
                TaskKind.REJECT_PROMOTION,
                (owner,),
                4,
                known_at,
                canonical_json({"event_id": "e_plan_transfer"}),
            ),
            True,
        ),
        TaskExpectation(
            TaskQuery(
                "q_owner_change",
                TaskKind.CHANGES,
                (owner,),
                4,
                known_at,
                canonical_json({"from_time": 2, "to_time": 4}),
            ),
            {"before": "Ari", "after": "Cato"},
        ),
    )


def run_demo(*, claims_path: str | Path | None = None) -> dict[str, Any]:
    ledger, refs = build_demo_ledger()
    snapshot_t2 = ledger.replay(valid_at=2)
    snapshot_t4 = ledger.replay(valid_at=4)
    counterfactual = ledger.counterfactual(valid_at=4, exclude_event_ids=("e_transfer_cato",))

    rule = make_causal_rule_component(
        component_id="component:rule:containment_owner_v1",
        keys=(FactKey("gem", "inside"), FactKey("chest", "owner")),
        rule_id="containment_owner_v1",
        rule="an item's effective owner is the owner of its containing object",
        source_event_ids=("e_inside", "e_owner_ari"),
        evidence=(refs["o_inside"], refs["o_owner"]),
        available_from_record=11,
    )
    compressor = ReferenceCompressor()
    full = compressor.compress(
        ledger,
        representation_id="demo-representation-full-v1",
        extra_components=(rule,),
        schema_bytes=512,
        ontology_bytes=128,
        code_config_bytes=256,
        human_authored_domain_bytes=384,
    )
    tasks = build_demo_tasks(ledger.head_record_seq)
    trusted_root = RepresentationRootCommitment.from_trusted_representation(full)
    decompressor = SelectiveDecompressor((trusted_root,))
    solver = DeterministicReferenceSolver()
    evaluator = RepresentationEvaluator(decompressor, solver)
    full_evaluation = evaluator.evaluate(full, tasks)
    ablation = RepresentationAblator(evaluator, exact_limit=12).minimize(full, tasks)

    omitted_id = "component:event:e_inside"
    lossy_ids = tuple(item.component_id for item in full.components if item.component_id != omitted_id)
    lossy = full.subset(lossy_ids, representation_id="demo-representation-lossy-v1")
    lossy_evaluation = evaluator.evaluate(lossy, tasks)
    lossy = replace(
        lossy,
        validation_status=ValidationStatus.DETERMINISTICALLY_VALIDATED,
    )

    proposer = DeterministicMissingDependencyProposer()
    repaired, proposal = proposer.propose(
        lossy,
        full,
        missing_component_id=omitted_id,
        candidate_id="demo-representation-repaired-v2",
    )
    protected_tasks = tasks[2:]
    new_tasks = tasks[:2]
    protocol_hash = sha256_text("hive-reference-demo-protocol-v1")
    gate = RepresentationRepairGate(
        evaluator,
        candidate_cost_ceiling=repaired.cost,
    )

    registry = RepresentationRegistry(
        gate=gate,
        protected_tasks=protected_tasks,
        new_tasks=new_tasks,
        protocol_hash=protocol_hash,
    )
    registry.register(lossy)
    bootstrap = registry.bootstrap(lossy.representation_id)
    registry.register(repaired)
    migration, activation = registry.evaluate_and_activate(repaired.representation_id)
    if activation is None:
        raise RuntimeError(f"deterministic demo repair was rejected: {migration.reason}")
    repaired_hash = registry.active.content_hash if registry.active else None
    rollback = registry.rollback(lossy.representation_id, reason="demo_rollback_verification")
    rollback_hash_matches = registry.active is not None and registry.active.content_hash == lossy.content_hash

    claim_summary: dict[str, Any] = {}
    if claims_path is not None:
        evidence_registry = EvidenceRegistry.load(claims_path)
        claim_summary = {
            claim_id: {
                "evidence_level": evidence_registry.get(claim_id).evidence_level.value,
                "scope": evidence_registry.get(claim_id).scope,
            }
            for claim_id in ("HIVE-C001", "HIVE-C011", "HIVE-C013", "HIVE-C015", "HIVE-C021")
        }

    result: dict[str, Any] = {
        "architecture_id": "hive-reference-architecture-v0.1",
        "canonicalization": {
            "mode": "handcrafted_exact_schema",
            "learned": False,
            "observation_count": len(ledger.observations),
            "event_count": len(ledger.events),
        },
        "claims": claim_summary,
        "counterfactual": {
            "canonical_ledger_unchanged": ledger.digest == full.source_ledger_hash,
            "noncanonical": counterfactual.noncanonical,
            "owner_without_transfer": counterfactual.value(FactKey("chest", "owner")),
        },
        "ledger": {
            "digest": ledger.digest,
            "plan_decision": next(
                asdict(item) for item in ledger.decisions if item.event_id == "e_plan_transfer"
            ),
        },
        "state": {
            "t2_digest": snapshot_t2.digest,
            "t2_owner": snapshot_t2.value(FactKey("chest", "owner")),
            "t4_contradictions": [asdict(item) for item in snapshot_t4.contradictions],
            "t4_digest": snapshot_t4.digest,
            "t4_intent": snapshot_t4.value(FactKey("ari", "intends_transfer_chest_to")),
            "t4_owner": snapshot_t4.value(FactKey("chest", "owner")),
        },
        "representation": {
            "codec_id": full.codec_id,
            "component_count": len(full.components),
            "content_hash": full.content_hash,
            "cost": asdict(full.cost),
            "learned": False,
            "origin": asdict(full.origin),
        },
        "evaluation": {
            "full": asdict(full_evaluation),
            "lossy": asdict(lossy_evaluation),
            "compression_loss_detected": full_evaluation.all_passed and not lossy_evaluation.all_passed,
        },
        "ablation": asdict(ablation),
        "repair": {
            "activation": asdict(activation),
            "bootstrap": asdict(bootstrap),
            "candidate_hash": repaired.content_hash,
            "migration": asdict(migration),
            "proposal": asdict(proposal),
            "repaired_active_hash": repaired_hash,
            "rollback": asdict(rollback),
            "rollback_hash_matches": rollback_hash_matches,
            "representation_learning_demonstrated": False,
            "status": "deterministic_oracle_assisted_repair_plumbing",
        },
        "model_calls": 0,
        "scope_boundary": (
            "This proves deterministic pipeline and governance behavior on one fixture; "
            "it does not prove learned abstraction, transfer, self-diagnosis, or recursion."
        ),
    }
    result["payload_sha256"] = sha256_text(canonical_json(result))
    return result


def write_demo_result(output_path: str | Path, *, claims_path: str | Path | None = None) -> dict[str, Any]:
    result = run_demo(claims_path=claims_path)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Research artifacts are append-only evidence.  Exclusive creation makes
    # an accidental rerun fail closed instead of overwriting the first result.
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return result
