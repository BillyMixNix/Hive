from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hive_reference.adapter import capability_gate_from_result
from hive_reference.model import canonical_json, sha256_text
from hive_reference.representation import (
    ComponentKind,
    CostBreakdown,
    EvaluationSummary,
    OriginKind,
    OriginManifest,
    RepresentationEvaluator,
    RepresentationInvariantError,
    RepresentationVersion,
    SolveStatus,
    SolverOutcome,
    SourceComponentManifestEntry,
    TaskExpectation,
    TaskKind,
    TaskQuery,
    ValidationStatus,
)
from hive_reference.research import (
    EvidenceLevel,
    EvidenceRegistry,
    ExperimentEvidence,
    ImprovementCycle,
    MATCHED_RESOURCE_COST_FIELDS,
    MigrationDecision,
    RepresentationRegistry,
    RepresentationRepairGate,
    ResearchInvariantError,
)


ROOT = Path(__file__).resolve().parents[1]


def _task(query_id: str) -> TaskExpectation:
    return TaskExpectation(
        query=TaskQuery(query_id, TaskKind.VALUE_AT, (), 0, 0),
        expected_answer="pass",
    )


PROTECTED_TASKS = (_task("protected"),)
NEW_TASKS = (_task("new"),)
PROTOCOL_HASH = sha256_text("research-audit-protocol")


def _representation(
    representation_id: str,
    *,
    parent_id: str | None = None,
    version: int = 1,
    validation_status: ValidationStatus = ValidationStatus.DETERMINISTICALLY_VALIDATED,
) -> RepresentationVersion:
    manifest_hash = RepresentationVersion.compute_source_component_manifest_hash(())
    return RepresentationVersion(
        representation_id=representation_id,
        family_id="audit-family",
        version=version,
        parent_id=parent_id,
        source_ledger_hash="source-ledger",
        codec_id="codec-v1",
        schema_id="schema-v1",
        components=(),
        preservation_scope=(),
        known_failure_modes=(),
        origin=OriginManifest(OriginKind.HANDCRAFTED, discovery_automatic=False),
        validation_status=validation_status,
        cost=CostBreakdown(
            packet_bytes=RepresentationVersion.compute_packet_bytes(
                (), (), manifest_hash
            ),
        ),
        source_component_manifest_hash=manifest_hash,
    )


class _MarkerDecompressor:
    configuration_hash = sha256_text("research-audit-marker-decompressor-v1")

    def decompress(self, representation, query):
        return type("View", (), {"representation_id": representation.representation_id})()


class _ImprovementSolver:
    solver_id = "research-audit-solver"
    configuration_hash = sha256_text("research-audit-improvement-solver-v1")

    def solve(self, view, query):
        answer = (
            "pass"
            if query.query_id == "protected" or view.representation_id != "parent"
            else "fail"
        )
        return SolverOutcome(
            query_id=query.query_id,
            status=SolveStatus.COMPLETE,
            answer=answer,
            used_component_ids=(),
            evidence_observation_ids=(),
        )


class _MutableConfiguredSolver:
    solver_id = "research-audit-mutable-solver"

    def __init__(self) -> None:
        self.candidate_enabled = False

    @property
    def configuration_hash(self) -> str:
        return sha256_text(
            canonical_json({"candidate_enabled": self.candidate_enabled})
        )

    def solve(self, view, query):
        answer = (
            "pass"
            if query.query_id == "protected"
            or (view.representation_id != "parent" and self.candidate_enabled)
            else "fail"
        )
        return SolverOutcome(
            query_id=query.query_id,
            status=SolveStatus.COMPLETE,
            answer=answer,
            used_component_ids=(),
            evidence_observation_ids=(),
        )


def _gate(*, cost_ceiling: CostBreakdown | None = None) -> RepresentationRepairGate:
    evaluator = RepresentationEvaluator(_MarkerDecompressor(), _ImprovementSolver())
    return RepresentationRepairGate(evaluator, candidate_cost_ceiling=cost_ceiling)


def _registry(*, gate: RepresentationRepairGate | None = None) -> RepresentationRegistry:
    return RepresentationRegistry(
        gate=gate or _gate(),
        protected_tasks=PROTECTED_TASKS,
        new_tasks=NEW_TASKS,
        protocol_hash=PROTOCOL_HASH,
    )


def _forged_promotion(
    parent: RepresentationVersion,
    candidate: RepresentationVersion,
    *,
    candidate_outcome: str = "candidate-outcome",
) -> MigrationDecision:
    return MigrationDecision.from_content(
        parent_representation_id=parent.representation_id,
        candidate_representation_id=candidate.representation_id,
        parent_representation_hash=parent.content_hash,
        candidate_representation_hash=candidate.content_hash,
        protocol_hash=PROTOCOL_HASH,
        evaluator_hash=sha256_text("evaluator"),
        parent_outcome_hash=sha256_text("parent-outcome"),
        candidate_outcome_hash=sha256_text(candidate_outcome),
        status="promote",
        reason="caller says so",
        rollback_verified=True,
        gate_id=RepresentationRepairGate.gate_id,
        protected_task_manifest_hash=sha256_text("protected-manifest"),
        new_task_manifest_hash=sha256_text("new-manifest"),
        cost_ceiling_hash=sha256_text("cost-ceiling"),
    )


def _valid_cycle() -> ImprovementCycle:
    cost = CostBreakdown(packet_bytes=10)
    return ImprovementCycle(
        cycle_id="cycle-v1",
        protocol_hash=sha256_text("cycle-protocol-v1"),
        evaluator_hash="evaluator-v1",
        proposer_before_hash="proposer-before",
        proposer_after_hash="proposer-after",
        train_manifest_hash="train-manifest",
        selection_manifest_hash="selection-manifest",
        metaheldout_manifest_hash="metaheldout-manifest",
        control_arm="frozen",
        total_cost_before=cost,
        total_cost_after=cost,
        benchmark_changed=False,
        evaluator_changed=False,
        heldout_leakage_detected=False,
        compute_matched=True,
        human_input_matched=True,
        rollback_verified=True,
        metaheldout_episode_count=6,
        metaheldout_replication_count=3,
        proposer_before_success_count=2,
        proposer_after_success_count=4,
        meta_ablation_success_count=2,
        meta_ablation_control="shuffled_meta",
    )


def test_caller_forged_migration_decision_cannot_activate() -> None:
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    registry = _registry()
    registry.register(parent)
    registry.bootstrap(parent.representation_id)
    registry.register(candidate)

    forged = _forged_promotion(parent, candidate)
    assert forged.gate_id == RepresentationRepairGate.gate_id
    with pytest.raises(ResearchInvariantError, match="direct activation is forbidden"):
        registry.activate(candidate.representation_id, forged)
    assert registry.active is parent


def test_registry_owned_gate_attests_exact_decision_and_activates() -> None:
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    gate = _gate()
    registry = _registry(gate=gate)
    registry.register(parent)
    registry.bootstrap(parent.representation_id)
    registry.register(candidate)

    forged = _forged_promotion(parent, candidate)
    gate.evaluate = lambda *args, **kwargs: forged
    gate._issue_decision = lambda *args, **kwargs: forged
    decision, event = registry.evaluate_and_activate(candidate.representation_id)

    assert decision.status == "promote"
    assert decision.decision_id != forged.decision_id
    assert decision.gate_id == gate.gate_id
    assert event is not None
    assert registry.active is candidate
    assert not hasattr(registry, "_apply_activation")
    with pytest.raises(ResearchInvariantError, match="ID does not match"):
        replace(decision, reason="tampered")


def test_registry_configuration_is_frozen_and_activation_accepts_only_candidate_id() -> None:
    gate = _gate()
    registry = _registry(gate=gate)
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    registry.register(parent)
    registry.bootstrap("parent")
    registry.register(candidate)

    with pytest.raises(TypeError):
        registry.evaluate_and_activate(candidate.representation_id, protocol_hash=PROTOCOL_HASH)

    gate.evaluator = RepresentationEvaluator(_MarkerDecompressor(), _ImprovementSolver())
    with pytest.raises(ResearchInvariantError, match="configuration changed"):
        registry.evaluate_and_activate(candidate.representation_id)

    gate = _gate()
    registry = _registry(gate=gate)
    registry.register(parent)
    registry.bootstrap("parent")
    registry.register(candidate)
    gate.evaluator.solver.solver_id = "mutated-after-registry-construction"
    with pytest.raises(ResearchInvariantError, match="configuration changed"):
        registry.evaluate_and_activate(candidate.representation_id)


def test_mutated_behavior_configuration_cannot_reuse_frozen_evaluator_authority() -> None:
    solver = _MutableConfiguredSolver()
    gate = RepresentationRepairGate(
        RepresentationEvaluator(_MarkerDecompressor(), solver)
    )
    registry = _registry(gate=gate)
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    registry.register(parent)
    registry.bootstrap("parent")
    registry.register(candidate)

    frozen_hash = gate.evaluator_hash
    solver.candidate_enabled = True
    assert gate.evaluator_hash != frozen_hash
    with pytest.raises(ResearchInvariantError, match="configuration changed"):
        registry.evaluate_and_activate(candidate.representation_id)
    assert registry.active is parent


def test_evaluator_fails_closed_without_explicit_collaborator_configuration_hashes() -> None:
    class _UnfingerprintedDecompressor:
        def decompress(self, representation, query):
            raise AssertionError("must not run")

    class _UnfingerprintedSolver:
        solver_id = "unfingerprinted"

        def solve(self, view, query):
            raise AssertionError("must not run")

    with pytest.raises(RepresentationInvariantError, match="configuration hash"):
        RepresentationEvaluator(_UnfingerprintedDecompressor(), _ImprovementSolver())
    with pytest.raises(RepresentationInvariantError, match="configuration hash"):
        RepresentationEvaluator(_MarkerDecompressor(), _UnfingerprintedSolver())


def test_fake_evaluator_cannot_configure_repair_authority() -> None:
    class _FabricatingEvaluator:
        solver = type("Solver", (), {"solver_id": "fabricator"})()

        def evaluate(self, representation, tasks):
            return EvaluationSummary(
                representation_id=representation.representation_id,
                all_passed=True,
                passed=len(tasks),
                total=len(tasks),
                outcomes=(),
            )

    with pytest.raises(ResearchInvariantError, match="exact RepresentationEvaluator"):
        RepresentationRepairGate(_FabricatingEvaluator())


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        ("representation", "representation ID mismatch"),
        ("total", "total does not match task count"),
        ("outcome_count", "outcomes do not match task count"),
        ("outcome_type", "nonstandard outcome"),
        ("query_id", "outcome query ID mismatch"),
        ("passed", "passed count is inconsistent"),
        ("all_passed", "all_passed is inconsistent"),
    ],
)
def test_evaluation_summary_internal_fields_are_validated(
    monkeypatch,
    variant: str,
    message: str,
) -> None:
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    gate = _gate()

    def _fabricated_summary(self, representation, tasks):
        outcome = SolverOutcome(
            query_id=tasks[0].query.query_id,
            status=SolveStatus.COMPLETE,
            answer=tasks[0].expected_answer,
            used_component_ids=(),
            evidence_observation_ids=(),
        )
        summary = EvaluationSummary(
            representation_id=representation.representation_id,
            all_passed=True,
            passed=len(tasks),
            total=len(tasks),
            outcomes=(outcome,),
        )
        if variant == "representation":
            return replace(summary, representation_id="fabricated")
        if variant == "total":
            return replace(summary, total=len(tasks) + 1)
        if variant == "outcome_count":
            return replace(summary, outcomes=())
        if variant == "outcome_type":
            return replace(summary, outcomes=(object(),))
        if variant == "query_id":
            return replace(summary, outcomes=(replace(outcome, query_id="fabricated"),))
        if variant == "passed":
            return replace(summary, passed=0)
        return replace(summary, all_passed=False)

    monkeypatch.setattr(RepresentationEvaluator, "evaluate", _fabricated_summary)
    with pytest.raises(ResearchInvariantError, match=message):
        gate.evaluate(
            parent,
            candidate,
            protected_tasks=PROTECTED_TASKS,
            new_tasks=NEW_TASKS,
            protocol_hash=PROTOCOL_HASH,
        )


def test_candidate_cost_growth_is_rejected_by_frozen_ceiling() -> None:
    parent = _representation("parent")
    candidate_base = _representation("candidate", parent_id="parent", version=2)
    candidate = replace(
        candidate_base,
        cost=replace(candidate_base.cost, input_tokens=1_000_000_000),
    )
    registry = _registry()
    registry.register(parent)
    registry.bootstrap("parent")
    registry.register(candidate)

    decision, event = registry.evaluate_and_activate(candidate.representation_id)

    assert decision.status == "reject"
    assert decision.reason == "candidate_cost_ceiling_exceeded:input_tokens"
    assert event is None
    assert registry.active is parent


def test_cost_breakdown_rejects_non_integer_and_negative_values_in_every_field() -> None:
    for field_name in MATCHED_RESOURCE_COST_FIELDS:
        for invalid_value in (float("nan"), True, 1.0, "1", -1):
            with pytest.raises(RepresentationInvariantError):
                CostBreakdown(**{field_name: invalid_value})


def test_full_gate_revalidates_cost_integrity_and_blocks_nan_tampering() -> None:
    registry = _registry()
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    registry.register(parent)
    registry.bootstrap("parent")
    registry.register(candidate)

    object.__setattr__(candidate.cost, "input_tokens", float("nan"))
    with pytest.raises(ResearchInvariantError, match="cost accounting is invalid"):
        registry.evaluate_and_activate(candidate.representation_id)
    assert registry.active is parent


def test_representation_rejects_self_reported_packet_size() -> None:
    representation = _representation("packet-audit")
    assert representation.cost.packet_bytes == representation.computed_packet_bytes

    with pytest.raises(RepresentationInvariantError, match="computed_packet_bytes"):
        replace(
            representation,
            cost=replace(
                representation.cost,
                packet_bytes=representation.computed_packet_bytes - 1,
            ),
        )


def test_decision_and_activation_ids_bind_full_content_and_sequence() -> None:
    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    first_record = _forged_promotion(parent, candidate, candidate_outcome="first")
    second_record = _forged_promotion(parent, candidate, candidate_outcome="second")
    assert first_record.decision_id != second_record.decision_id
    assert first_record.decision_id == "migration_" + first_record.content_hash
    with pytest.raises(ResearchInvariantError, match="ID does not match"):
        replace(first_record, candidate_outcome_hash=second_record.candidate_outcome_hash)

    registry = _registry()
    registry.register(parent)
    registry.bootstrap("parent")
    registry.register(candidate)
    first_decision, first_activation = registry.evaluate_and_activate("candidate")
    assert first_activation is not None
    registry.rollback("parent", reason="repeat-evaluation")
    second_decision, second_activation = registry.evaluate_and_activate("candidate")
    assert second_activation is not None

    assert first_decision.decision_id == second_decision.decision_id
    assert first_activation.decision_content_hash == first_decision.content_hash
    assert second_activation.decision_content_hash == second_decision.content_hash
    assert first_activation.activation_sequence == 1
    assert second_activation.activation_sequence == 3
    assert first_activation.activation_id != second_activation.activation_id


def test_registry_content_commitments_block_alias_mutation_at_every_version_boundary() -> None:
    root = _representation("bootstrap-root")
    registry = _registry()
    registry.register(root)
    object.__setattr__(root, "known_failure_modes", ("mutated-before-bootstrap",))
    with pytest.raises(ResearchInvariantError, match="content changed after registration"):
        registry.bootstrap(root.representation_id)

    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    registry = _registry()
    registry.register(parent)
    registry.bootstrap(parent.representation_id)
    registry.register(candidate)
    object.__setattr__(candidate, "known_failure_modes", ("mutated-before-evaluation",))
    with pytest.raises(ResearchInvariantError, match="content changed after registration"):
        registry.get(candidate.representation_id)
    with pytest.raises(ResearchInvariantError, match="content changed after registration"):
        registry.evaluate_and_activate(candidate.representation_id)

    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    registry = _registry()
    registry.register(parent)
    registry.bootstrap(parent.representation_id)
    registry.register(candidate)
    decision, event = registry.evaluate_and_activate(candidate.representation_id)
    assert decision.status == "promote"
    assert event is not None
    object.__setattr__(candidate, "known_failure_modes", ("mutated-while-active",))
    with pytest.raises(ResearchInvariantError, match="content changed after registration"):
        _ = registry.active
    with pytest.raises(ResearchInvariantError, match="content changed after registration"):
        registry.rollback(parent.representation_id, reason="must-detect-active-mutation")
    assert registry.active_id == candidate.representation_id

    parent = _representation("parent")
    candidate = _representation("candidate", parent_id="parent", version=2)
    registry = _registry()
    registry.register(parent)
    registry.bootstrap(parent.representation_id)
    registry.register(candidate)
    decision, event = registry.evaluate_and_activate(candidate.representation_id)
    assert decision.status == "promote"
    assert event is not None
    registry.rollback(parent.representation_id, reason="valid-rollback")
    object.__setattr__(candidate, "known_failure_modes", ("mutated-while-inactive",))
    with pytest.raises(ResearchInvariantError, match="content changed after registration"):
        registry.rollback(candidate.representation_id, reason="must-not-restore-mutated-alias")
    assert registry.active is parent


@pytest.mark.parametrize(
    "status",
    [
        ValidationStatus.UNTESTED,
        ValidationStatus.SCHEMA_VALIDATED,
        ValidationStatus.REJECTED,
    ],
)
def test_registry_rejects_unvalidated_or_rejected_versions(status: ValidationStatus) -> None:
    registry = _registry()
    parent = _representation("parent")
    registry.register(parent)
    candidate = _representation(
        "candidate",
        parent_id="parent",
        version=2,
        validation_status=status,
    )

    with pytest.raises(ResearchInvariantError, match="requires deterministic"):
        registry.register(candidate)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"version": 3}, "version_mismatch"),
        ({"family_id": "foreign-family"}, "family_id_mismatch"),
        ({"schema_id": "foreign-schema"}, "schema_id_mismatch"),
        ({"codec_id": "foreign-codec"}, "codec_id_mismatch"),
        ({"source_ledger_hash": "foreign-source"}, "source_ledger_hash_mismatch"),
    ],
)
def test_registry_rejects_parent_incompatible_candidate(changes, reason: str) -> None:
    registry = _registry()
    parent = _representation("parent")
    registry.register(parent)
    candidate = replace(
        _representation("candidate", parent_id="parent", version=2),
        **changes,
    )

    with pytest.raises(ResearchInvariantError, match=reason):
        registry.register(candidate)


def test_registry_rejects_changed_full_source_manifest() -> None:
    registry = _registry()
    parent = _representation("parent")
    registry.register(parent)
    foreign_manifest = (
        SourceComponentManifestEntry(
            component_id="foreign-source-component",
            content_hash=sha256_text("foreign-source-component"),
            component_kind=ComponentKind.ATOM,
            available_from_record=0,
            effective_time=None,
            recorded_at=None,
            keys=(),
            produced_keys=(),
            source_event_ids=(),
            applicable_task_kinds=(),
        ),
    )
    candidate_base = _representation("candidate", parent_id="parent", version=2)
    foreign_manifest_hash = (
        RepresentationVersion.compute_source_component_manifest_hash(
            foreign_manifest
        )
    )
    candidate = replace(
        candidate_base,
        source_component_manifest=foreign_manifest,
        source_component_manifest_hash=foreign_manifest_hash,
        cost=replace(
            candidate_base.cost,
            packet_bytes=RepresentationVersion.compute_packet_bytes(
                (),
                foreign_manifest,
                foreign_manifest_hash,
            ),
        ),
    )

    with pytest.raises(ResearchInvariantError, match="source_component_manifest_hash_mismatch"):
        registry.register(candidate)


def test_repair_gate_rejects_unvalidated_and_incompatible_candidates() -> None:
    parent = _representation("parent")
    gate = _gate()
    untested = _representation(
        "untested",
        parent_id="parent",
        version=2,
        validation_status=ValidationStatus.UNTESTED,
    )
    schema_only = _representation(
        "schema-only",
        parent_id="parent",
        version=2,
        validation_status=ValidationStatus.SCHEMA_VALIDATED,
    )
    incompatible = replace(
        _representation("foreign", parent_id="parent", version=2),
        codec_id="foreign-codec",
    )

    untested_decision = gate.evaluate(
        parent,
        untested,
        protected_tasks=PROTECTED_TASKS,
        new_tasks=NEW_TASKS,
        protocol_hash=PROTOCOL_HASH,
    )
    incompatible_decision = gate.evaluate(
        parent,
        incompatible,
        protected_tasks=PROTECTED_TASKS,
        new_tasks=NEW_TASKS,
        protocol_hash=PROTOCOL_HASH,
    )
    schema_decision = gate.evaluate(
        parent,
        schema_only,
        protected_tasks=PROTECTED_TASKS,
        new_tasks=NEW_TASKS,
        protocol_hash=PROTOCOL_HASH,
    )

    assert (untested_decision.status, untested_decision.reason) == (
        "reject",
        "candidate_validation_untested",
    )
    assert incompatible_decision.status == "reject"
    assert incompatible_decision.reason == "candidate_codec_id_mismatch"
    assert (schema_decision.status, schema_decision.reason) == (
        "reject",
        "candidate_validation_schema_validated",
    )
    assert untested_decision.gate_id == gate.gate_id
    assert incompatible_decision.gate_id == gate.gate_id


def test_result_mapping_is_descriptive_and_cannot_self_authorize() -> None:
    caller_supplied = {
        "validity": "VALID",
        "condition_summaries": {"raw": {"exact_correct": 20, "total": 20}},
    }

    gate = capability_gate_from_result(caller_supplied, solver_id="claimed-solver")

    assert gate.threshold_met
    assert not gate.authoritative
    assert not gate.passed
    assert not gate.representation_interpretation_allowed


@pytest.mark.parametrize(
    "overrides",
    [
        {"experiment_id": ""},
        {"protocol_hash": " "},
        {"result": ""},
        {"artifact_hashes": ()},
        {"artifact_hashes": ("not-a-sha256",)},
        {"artifact_hashes": ("A" * 64,)},
    ],
)
def test_experiment_evidence_rejects_incomplete_or_unsealed_records(overrides) -> None:
    fields = {
        "experiment_id": "experiment-v1",
        "protocol_hash": PROTOCOL_HASH,
        "validity": "VALID",
        "result": "negative",
        "artifact_hashes": ("a" * 64,),
    }
    fields.update(overrides)

    with pytest.raises(ResearchInvariantError):
        ExperimentEvidence(**fields)


@pytest.mark.parametrize("validity", ["EXPLORATORY", "VALID"])
def test_syntactic_evidence_cannot_authorize_supported_claim(validity: str) -> None:
    evidence = ExperimentEvidence(
        experiment_id="evidence-v1",
        protocol_hash=PROTOCOL_HASH,
        validity=validity,
        result="favorable",
        artifact_hashes=("b" * 64,),
    )

    with pytest.raises(ResearchInvariantError, match="trusted artifact verifier"):
        EvidenceRegistry.validate_upgrade(evidence, EvidenceLevel.SUPPORTED)


def test_recursive_evidence_requires_real_replicated_gain_and_meta_ablation() -> None:
    cycle = _valid_cycle()
    assert cycle.admissible_recursive_evidence
    assert not replace(
        cycle,
        proposer_after_success_count=cycle.proposer_before_success_count,
    ).admissible_recursive_evidence
    assert not replace(cycle, metaheldout_replication_count=1).admissible_recursive_evidence
    assert not replace(
        cycle,
        meta_ablation_success_count=cycle.proposer_after_success_count,
    ).admissible_recursive_evidence
    assert not replace(cycle, meta_ablation_control="").admissible_recursive_evidence


def test_recursive_evidence_matches_every_declared_resource_field() -> None:
    cycle = _valid_cycle()
    assert MATCHED_RESOURCE_COST_FIELDS == (
        "packet_bytes",
        "schema_bytes",
        "ontology_bytes",
        "code_config_bytes",
        "lookup_bytes",
        "preprocessing_steps",
        "preprocessing_model_calls",
        "solver_model_calls",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "human_authored_domain_bytes",
    )
    for field_name in MATCHED_RESOURCE_COST_FIELDS:
        inflated = replace(
            cycle,
            compute_matched=True,
            total_cost_after=replace(
                cycle.total_cost_after,
                **{field_name: 1_000_000_000},
            ),
        )
        assert not inflated.matched_resource_costs
        assert not inflated.admissible_recursive_evidence


def test_recursive_cycle_rejects_empty_or_aliased_provenance() -> None:
    cycle = _valid_cycle()
    with pytest.raises(ResearchInvariantError, match="nonempty"):
        replace(cycle, proposer_before_hash="")
    with pytest.raises(ResearchInvariantError, match="proposer hashes must differ"):
        replace(cycle, proposer_after_hash=cycle.proposer_before_hash)
    with pytest.raises(ResearchInvariantError, match="manifests must differ"):
        replace(cycle, metaheldout_manifest_hash=cycle.train_manifest_hash)


def test_architecture_and_claim_registries_preserve_partial_evidence_boundary() -> None:
    architecture = json.loads(
        (ROOT / "hive_reference/spec/architecture.json").read_text(encoding="utf-8")
    )
    claims = json.loads(
        (ROOT / "hive_reference/spec/claims.json").read_text(encoding="utf-8")
    )
    by_claim = {item["claim_id"]: item for item in claims["claims"]}
    by_node = {item["id"]: item for item in architecture["nodes"]}
    evidence_edge = next(
        edge
        for edge in architecture["edges"]
        if edge["from"] == "evaluation" and edge["to"] == "evidence_registry"
    )
    human_registry = (ROOT / "HIVE_CLAIM_REGISTRY.md").read_text(encoding="utf-8")

    assert architecture["status"] == "PARTIAL"
    assert by_node["evidence_registry"]["status"] == "PARTIAL"
    assert evidence_edge["status"] == "PARTIAL"
    assert by_claim["HIVE-C003"]["evidence_level"] == "SUPPORTED"
    assert by_claim["HIVE-C004"]["evidence_level"] == "PLAUSIBLE"
    assert by_claim["HIVE-C018"]["evidence_level"] == "PLAUSIBLE"
    assert by_claim["HIVE-C019"]["evidence_level"] == "SUPPORTED"
    assert "| HIVE-C004 | PLAUSIBLE |" in human_registry
    assert "| HIVE-C018 | PLAUSIBLE |" in human_registry
    assert "| HIVE-C019 | SUPPORTED |" in human_registry
