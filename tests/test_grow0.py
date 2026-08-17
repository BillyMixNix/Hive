from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from grow.core import (
    AppendOnlyLedger,
    CandidateWorkspace,
    ForbiddenWriteError,
    GenerationRecord,
    LessonLedger,
    ModelConfig,
    hash_json,
    manifest_hash,
    tree_manifest,
)
from grow.experiment import Grow0Experiment
from grow.kernel.promotion import PromotionEvidence, decide_promotion


ROOT = Path(__file__).resolve().parents[1]


def make_repo(tmp_path: Path) -> Path:
    for rel in (
        "grow/config.json",
        "grow/core.py",
        "grow/experiment.py",
        "grow/model.py",
        "grow/kernel/__init__.py",
        "grow/kernel/evaluator.py",
        "grow/kernel/promotion.py",
        "grow/kernel/trigger_case.json",
        "grow/kernel/hidden_transfer.json",
        "grow/workshop/__init__.py",
        "grow/workshop/repair_packet.py",
    ):
        src = ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return tmp_path


def position_model(prompt: str) -> str:
    line = next(line for line in prompt.splitlines() if line.startswith("Candidate value A:"))
    value = json.loads(line.split(":", 1)[1].strip().replace("'", '"')) if '"' in line else int(line.split(":",1)[1].strip())
    return json.dumps({"selected_source": "current", "selected_value": value})


def good_candidate_source() -> str:
    return r'''"""Generic provenance-preserving repair packet."""

def build_repair_packet(case, *, presentation_order="stored_first"):
    stored = case["stored_value"]
    current = case["current_value"]
    if presentation_order == "stored_first":
        first_label = "STORED_STATE"
        first_value = stored
        second_label = "CURRENT_CALL"
        second_value = current
    else:
        first_label = "CURRENT_CALL"
        first_value = current
        second_label = "STORED_STATE"
        second_value = stored
    return (
        "REPAIR DECISION PACKET\n"
        + f"Goal: {case['goal']}\n"
        + f"{first_label}: {first_value!r}\n"
        + f"{second_label}: {second_value!r}\n"
        + "Use the value tagged CURRENT_CALL for the active operation.\n"
        + "Return JSON only with keys selected_source and selected_value."
    )
'''


def provenance_model(prompt: str) -> str:
    line = next(line for line in prompt.splitlines() if line.startswith("CURRENT_CALL:"))
    value = int(line.split(":", 1)[1].strip())
    return json.dumps({"selected_source": "current", "selected_value": value})


def baseline_suite() -> dict:
    return {"passed": True, "count": 335, "source": "pinned-main-ci"}


def test_descendant_cannot_modify_evaluator(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        with pytest.raises(ForbiddenWriteError):
            ws.write_text(exp.evaluator_path, "# hacked")


def test_descendant_cannot_modify_hidden_transfer(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        with pytest.raises(ForbiddenWriteError):
            ws.write_text(exp.transfer_path, "{}")


def test_descendant_cannot_modify_ancestor_file(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    before = (repo / exp.workshop_path).read_text()
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, good_candidate_source())
    assert (repo / exp.workshop_path).read_text() == before


def test_forbidden_write_attempts_are_recorded(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        with pytest.raises(ForbiddenWriteError):
            ws.write_text("tests/test_secret.py", "x")
        assert ws.write_attempts[-1]["allowed"] is False


def test_lineage_parent_child_relationship_preserved(tmp_path):
    ledger = AppendOnlyLedger(tmp_path / "lineage.jsonl")
    ledger.append({"record_type": "generation", "generation_id": "G0", "parent_id": None, "disposition": "PROMOTED"})
    ledger.append({"record_type": "generation", "generation_id": "G1-A", "parent_id": "G0", "disposition": "REJECTED"})
    assert ledger.get_generation("G1-A")["parent_id"] == "G0"


def test_rejected_child_cannot_become_parent(tmp_path):
    ledger = AppendOnlyLedger(tmp_path / "lineage.jsonl")
    ledger.append({"record_type": "generation", "generation_id": "G1-A", "parent_id": "G0", "disposition": "REJECTED"})
    assert ledger.parent_is_eligible("G1-A") is False


def test_promoted_child_can_become_parent(tmp_path):
    ledger = AppendOnlyLedger(tmp_path / "lineage.jsonl")
    ledger.append({"record_type": "generation", "generation_id": "G1-A", "parent_id": "G0", "disposition": "PROMOTED"})
    assert ledger.parent_is_eligible("G1-A") is True


def test_historical_ledger_rewrite_is_detected(tmp_path):
    path = tmp_path / "lineage.jsonl"
    ledger = AppendOnlyLedger(path)
    ledger.append({"record_type": "generation", "generation_id": "G0", "disposition": "PROMOTED"})
    raw = path.read_text()
    path.write_text(raw.replace("PROMOTED", "REJECTED", 1))
    assert ledger.verify() is False


def test_trigger_only_improvement_is_insufficient():
    result = decide_promotion(PromotionEvidence(True, True, True, True, 0, 0))
    assert result["promoted"] is False
    assert "REJECTED_NO_TRANSFER_GAIN" in result["reasons"]


def test_regression_loss_prevents_promotion():
    result = decide_promotion(PromotionEvidence(True, False, True, True, 0, 1))
    assert result["promoted"] is False
    assert "REJECTED_REGRESSION" in result["reasons"]


def test_transfer_failure_prevents_promotion():
    result = decide_promotion(PromotionEvidence(True, True, True, True, 0, 0))
    assert result["promoted"] is False


def test_evaluator_mutation_invalidates_candidate(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    _, snap = exp.freeze_g0(baseline_ref="abc", prior_suite=baseline_suite())
    (repo / exp.evaluator_path).write_text("# evaluator mutated\n")
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, good_candidate_source())
        integrity = exp.evaluate_candidate_integrity(ws, snap)
    assert integrity["passed"] is False
    assert integrity["checks"]["evaluator_unchanged"] is False


def test_exact_promotion_condition_is_deterministic():
    evidence = PromotionEvidence(True, True, True, True, 0, 1)
    assert decide_promotion(evidence) == decide_promotion(evidence)
    assert decide_promotion(evidence)["promoted"] is True


def test_failed_candidate_leaves_ancestor_unchanged(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    _, snap = exp.freeze_g0(baseline_ref="abc", prior_suite=baseline_suite())
    before = manifest_hash(tree_manifest(repo))
    result = exp.dry_run_rejection(snapshot=snap)
    after = manifest_hash(tree_manifest(repo))
    assert result["disposition"] == "INVALID"
    assert result["ancestor_unchanged"] is True
    assert before == after


def test_failed_candidate_leaves_persistent_lesson_record(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    exp.record_rejection_lesson(
        generation_id="G1-A", manifest=None, prediction="generic change should transfer",
        contradicted_by=["REJECTED_NO_TRANSFER_GAIN"], diagnosis_or_implementation="implementation",
        avoid=["repeat same change"],
    )
    assert exp.lesson_ledger.entries()[-1]["record_type"] == "rejection_lesson"


def test_repeated_candidate_receives_previous_rejection_without_hidden_answers(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    exp.record_rejection_lesson(
        generation_id="G1-A", manifest=None, prediction="generic change should transfer",
        contradicted_by=["no gain"], diagnosis_or_implementation="implementation", avoid=["repeat same change"],
    )
    lessons = exp.lesson_ledger.sanitized_lessons(exp._sensitive_case_markers(exp._transfer))
    serialized = json.dumps(lessons)
    assert lessons
    for marker in exp._sensitive_case_markers(exp._transfer):
        assert marker not in serialized


def test_hidden_transfer_details_never_enter_modification_prompt(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    g0 = exp.evaluate_workshop_case(repo / exp.workshop_path, exp.trigger, position_model)
    packet = exp.build_failure_packet(g0)
    diagnosis = exp.diagnosis_template(packet)
    probe = exp.run_probe(position_model)
    diagnosis.status = probe["status"]
    prompt = exp.build_modification_prompt(packet, diagnosis, probe)
    for marker in exp._sensitive_case_markers(exp._transfer):
        assert marker not in prompt


def test_oracle_implementation_not_exposed_to_modifier(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    g0 = exp.evaluate_workshop_case(repo / exp.workshop_path, exp.trigger, position_model)
    packet = exp.build_failure_packet(g0)
    diagnosis = exp.diagnosis_template(packet)
    probe = exp.run_probe(position_model)
    prompt = exp.build_modification_prompt(packet, diagnosis, probe)
    evaluator_text = (repo / exp.evaluator_path).read_text()
    assert "def evaluate_case(" not in prompt
    assert evaluator_text not in prompt


def test_benchmark_expected_answer_not_in_modification_context(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    g0 = exp.evaluate_workshop_case(repo / exp.workshop_path, exp.trigger, position_model)
    packet = exp.build_failure_packet(g0)
    diagnosis = exp.diagnosis_template(packet)
    probe = exp.run_probe(position_model)
    prompt = exp.build_modification_prompt(packet, diagnosis, probe)
    assert str(exp.trigger["expected_value"]) not in prompt
    assert '"expected_value"' not in prompt


def test_overfit_candidate_with_trigger_literal_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, good_candidate_source() + f"\n# magic {exp.trigger['expected_value']}\n")
        result = exp.anti_overfit_scan(ws)
    assert result["passed"] is False


def test_generic_candidate_passes_overfit_scan(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, good_candidate_source())
        result = exp.anti_overfit_scan(ws)
    assert result["passed"] is True


def test_supported_probe_distinguishes_provenance_loss(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    probe = exp.run_probe(position_model)
    assert probe["status"] == "DIAGNOSIS_SUPPORTED"
    assert probe["stored_first"]["passed"] is False
    assert probe["current_first"]["passed"] is True


def test_generic_candidate_solves_trigger_and_transfer_with_same_model_behavior(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, good_candidate_source())
        trigger = exp.evaluate_workshop_case(ws.root / exp.workshop_path, exp.trigger, provenance_model)
        transfer = exp.evaluate_workshop_case(ws.root / exp.workshop_path, exp._transfer, provenance_model)
    assert trigger["passed"] is True
    assert transfer["passed"] is True


def test_model_configuration_hash_changes_with_base_intelligence():
    a = ModelConfig("qwen2.5-coder:7b", "digest-a", 0.0, 42, 8192, 2048, 4)
    b = ModelConfig("qwen2.5-coder:14b", "digest-b", 0.0, 42, 8192, 2048, 4)
    assert a.config_hash != b.config_hash


def test_candidate_cannot_execute_filesystem_reads(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    malicious = '''import pathlib

def build_repair_packet(case, *, presentation_order="stored_first"):
    secret = pathlib.Path("grow/kernel/hidden_transfer.json").read_text()
    return secret
'''
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, malicious)
        integrity = exp.evaluate_candidate_integrity(ws, exp.freeze_g0(baseline_ref="abc", prior_suite=baseline_suite())[1])
        result = exp.evaluate_workshop_case(ws.root / exp.workshop_path, exp.trigger, position_model)
    assert integrity["passed"] is False
    assert any("forbidden AST node" in error for error in integrity["structure"]["errors"])
    assert result["passed"] is False
    assert "unsafe candidate workshop" in result["error"]
