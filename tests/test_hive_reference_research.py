from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hive_reference.adapter import (
    FrozenDecompressionAdapter,
    capability_gate_from_result,
    load_result,
)
from hive_reference.demo import build_demo_ledger, build_demo_tasks
from hive_reference.representation import (
    ComponentKind,
    CompressionKind,
    CostBreakdown,
    DeterministicReferenceSolver,
    OriginKind,
    OriginManifest,
    ReferenceCompressor,
    RepresentationComponent,
    RepresentationEvaluator,
    RepresentationInvariantError,
    SelectiveDecompressor,
    TaskKind,
    ValidationStatus,
    make_causal_rule_component,
)
from hive_reference.model import EvidenceRef, FactKey, canonical_json
from hive_reference.research import (
    DeterministicMissingDependencyProposer,
    EvidenceLevel,
    EvidenceRegistry,
    ExperimentEvidence,
    FitnessVector,
    ImprovementCycle,
    RepresentationRegistry,
    RepresentationRepairGate,
    ResearchInvariantError,
    pareto_frontier,
)


ROOT = Path(__file__).resolve().parents[1]


def _full_representation():
    ledger, refs = build_demo_ledger()
    rule = make_causal_rule_component(
        component_id="component:rule:containment_owner_v1",
        keys=(FactKey("gem", "inside"), FactKey("chest", "owner")),
        rule_id="containment_owner_v1",
        rule="contained item inherits effective owner",
        source_event_ids=("e_inside", "e_owner_ari"),
        evidence=(refs["o_inside"], refs["o_owner"]),
        available_from_record=11,
    )
    return ledger, ReferenceCompressor().compress(
        ledger,
        representation_id="full-v1",
        extra_components=(rule,),
        schema_bytes=100,
        ontology_bytes=100,
        code_config_bytes=100,
        human_authored_domain_bytes=100,
    )


def _fitness(rep_id: str, *, accuracy: float, packet: int, transfer: float = 1.0) -> FitnessVector:
    return FitnessVector(
        protocol_id="protocol",
        solver_id="solver",
        task_set_hash="tasks",
        representation_id=rep_id,
        sample_size=20,
        hard_gates_passed=True,
        reconstruction_accuracy=accuracy,
        task_accuracy=accuracy,
        causal_accuracy=accuracy,
        temporal_accuracy=accuracy,
        authority_accuracy=accuracy,
        provenance_retention=accuracy,
        transfer_accuracy=transfer,
        robustness=accuracy,
        cost=CostBreakdown(packet_bytes=packet),
    )


def test_preserve_discard_overlap_and_missing_dependency_fail_closed() -> None:
    ledger, full = _full_representation()
    component = full.components[0]
    with pytest.raises(RepresentationInvariantError, match="disjoint"):
        replace(
            component,
            preserved_distinctions=("same",),
            discarded_distinctions=("same",),
        )

    with pytest.raises(RepresentationInvariantError, match="missing dependencies"):
        replace(
            full,
            representation_id="broken",
            components=(replace(component, dependency_component_ids=("absent",)),),
        )


def test_pareto_keeps_tradeoff_and_rejects_smaller_inaccurate_dominance() -> None:
    accurate_large = _fitness("accurate", accuracy=1.0, packet=100)
    small_lossy = _fitness("lossy", accuracy=0.8, packet=10, transfer=0.7)
    equal_small = _fitness("equal-small", accuracy=1.0, packet=50)

    assert not small_lossy.dominates(accurate_large)
    assert equal_small.dominates(accurate_large)
    assert {item.representation_id for item in pareto_frontier((accurate_large, small_lossy))} == {
        "accurate",
        "lossy",
    }

    incomparable = replace(equal_small, solver_id="other")
    assert not incomparable.dominates(accurate_large)


def test_evidence_registry_retains_scopes_and_invalid_evidence_cannot_upgrade() -> None:
    registry = EvidenceRegistry.load(ROOT / "hive_reference/spec/claims.json")
    assert registry.get("HIVE-C001").evidence_level is EvidenceLevel.PROVEN
    assert registry.get("HIVE-C015").evidence_level is EvidenceLevel.SPECULATIVE
    assert registry.get("HIVE-C021").evidence_level is EvidenceLevel.FALSIFIED

    invalid = ExperimentEvidence("bad", "hash", "INVALID", "favorable", ("artifact",))
    with pytest.raises(ResearchInvariantError, match="invalid experiments"):
        registry.validate_upgrade(invalid, EvidenceLevel.SUPPORTED)


def test_repair_is_new_version_gated_and_rollback_preserves_both_versions() -> None:
    ledger, full = _full_representation()
    missing_id = "component:event:e_inside"
    lossy = full.subset(
        (item.component_id for item in full.components if item.component_id != missing_id),
        representation_id="lossy-v1",
    )
    proposer = DeterministicMissingDependencyProposer()
    candidate, proposal = proposer.propose(
        lossy,
        full,
        missing_component_id=missing_id,
        candidate_id="candidate-v2",
    )
    assert candidate.parent_id == lossy.representation_id
    assert candidate.origin.origin is OriginKind.DETERMINISTIC_HEURISTIC
    assert candidate.origin.oracle_assisted
    assert proposal.oracle_assisted

    tasks = build_demo_tasks(ledger.head_record_seq)
    evaluator = RepresentationEvaluator(SelectiveDecompressor(), DeterministicReferenceSolver())
    decision = RepresentationRepairGate(evaluator).evaluate(
        lossy,
        candidate,
        protected_tasks=tasks[2:],
        new_tasks=tasks[:2],
        protocol_hash="fixed",
    )
    assert decision.status == "promote"

    registry = RepresentationRegistry()
    registry.register(lossy)
    registry.bootstrap(lossy.representation_id)
    registry.register(candidate)
    registry.activate(candidate.representation_id, decision)
    candidate_hash = registry.active.content_hash
    registry.rollback(lossy.representation_id, reason="test")
    assert registry.active.content_hash == lossy.content_hash
    assert registry.get(candidate.representation_id).content_hash == candidate_hash


def test_repair_gate_rejects_no_improvement_and_protected_regression() -> None:
    ledger, full = _full_representation()
    tasks = build_demo_tasks(ledger.head_record_seq)
    evaluator = RepresentationEvaluator(SelectiveDecompressor(), DeterministicReferenceSolver())
    decision = RepresentationRepairGate(evaluator).evaluate(
        full,
        replace(full, representation_id="same-v2", version=2, parent_id=full.representation_id),
        protected_tasks=tasks[2:],
        new_tasks=tasks[:2],
        protocol_hash="fixed",
    )
    assert decision.status == "reject"
    assert decision.reason == "no_positive_new_task_improvement"


def test_recursive_evidence_requires_stable_protocol_controls_and_matched_resources() -> None:
    cost = CostBreakdown(packet_bytes=10)
    safe = ImprovementCycle(
        "cycle",
        "protocol",
        "evaluator",
        "before",
        "after",
        "train",
        "select",
        "heldout",
        "shuffled_meta",
        cost,
        cost,
        False,
        False,
        False,
        True,
        True,
        True,
    )
    assert safe.admissible_recursive_evidence
    assert not replace(safe, benchmark_changed=True).admissible_recursive_evidence
    assert not replace(safe, heldout_leakage_detected=True).admissible_recursive_evidence
    assert not replace(safe, compute_matched=False).admissible_recursive_evidence


def test_frozen_decompression_adapter_reuses_all_twenty_cases_without_inference() -> None:
    report = FrozenDecompressionAdapter().inspect(ROOT / "benchmarks/decompression_test/CASE_PACK.json")
    assert report.case_count == 20
    assert len(set(report.case_ids)) == 20
    assert report.all_source_hashes_recomputed
    assert report.all_compressed_replay_matches
    assert report.compressed_required_ref_recall == 1.0
    assert report.compressed_total_bytes < report.raw_total_bytes
    assert report.inference_calls == 0


def test_valid_qwen_result_fails_raw_capability_gate_without_becoming_invalid() -> None:
    result_path = ROOT / ".hive/benchmarks/decompression_test/smoke-v2-1-001/RESULT.json"
    if not result_path.exists():
        pytest.skip("sealed local Qwen artifact is not present in this checkout")
    result = load_result(result_path)
    gate = capability_gate_from_result(result, solver_id="qwen2.5-coder:7b", required_accuracy=0.8)
    assert result["validity"] == "VALID"
    assert (gate.raw_correct, gate.raw_total) == (5, 20)
    assert not gate.passed
    assert not gate.representation_interpretation_allowed


def test_machine_readable_specs_are_consistent_and_do_not_claim_learning() -> None:
    architecture = json.loads((ROOT / "hive_reference/spec/architecture.json").read_text(encoding="utf-8"))
    dag = json.loads((ROOT / "hive_reference/spec/research_dag.json").read_text(encoding="utf-8"))
    claims = json.loads((ROOT / "hive_reference/spec/claims.json").read_text(encoding="utf-8"))
    node_ids = {item["id"] for item in architecture["nodes"]}
    assert all(edge["from"] in node_ids and edge["to"] in node_ids for edge in architecture["edges"])
    dag_ids = {item["id"] for item in dag["nodes"]}
    assert all(set(item["prerequisites"]) <= dag_ids for item in dag["nodes"])
    claim_ids = {item["claim_id"] for item in claims["claims"]}
    assert len(claim_ids) == len(claims["claims"])
    learned = next(item for item in claims["claims"] if item["claim_id"] == "HIVE-C011")
    recursive = next(item for item in claims["claims"] if item["claim_id"] == "HIVE-C015")
    assert learned["evidence_level"] == "SPECULATIVE"
    assert recursive["evidence_level"] == "SPECULATIVE"
