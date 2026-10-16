from __future__ import annotations

import json
import shutil
from pathlib import Path

from grow.core import CandidateWorkspace
from grow.experiment import Grow0Experiment


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


def baseline_suite() -> dict:
    return {"passed": True, "count": 335, "source": "pinned-main-ci"}


def position_model(prompt: str) -> str:
    line = next(line for line in prompt.splitlines() if line.startswith("Candidate value A:"))
    value = int(line.split(":", 1)[1].strip())
    return json.dumps({"selected_source": "current", "selected_value": value})


def test_candidate_cannot_read_oracle_fields_dynamically(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    oracle_reader = '''def build_repair_packet(case, *, presentation_order="stored_first"):\n    answer = case["expected_value"]\n    return f"answer={answer}"\n'''
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, oracle_reader)
        _, snap = exp.freeze_g0(baseline_ref="abc", prior_suite=baseline_suite())
        integrity = exp.evaluate_candidate_integrity(ws, snap)
        result = exp.evaluate_workshop_case(ws.root / exp.workshop_path, exp.trigger, position_model)
    assert integrity["passed"] is False
    assert any("oracle field access forbidden" in error for error in integrity["structure"]["errors"])
    assert result["passed"] is False
    assert "unsafe candidate workshop" in result["error"]


def test_candidate_cannot_mutate_case_input(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    mutator = '''def build_repair_packet(case, *, presentation_order="stored_first"):\n    case["current_value"] = case["stored_value"]\n    return "mutated"\n'''
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, mutator)
        _, snap = exp.freeze_g0(baseline_ref="abc", prior_suite=baseline_suite())
        integrity = exp.evaluate_candidate_integrity(ws, snap)
        result = exp.evaluate_workshop_case(ws.root / exp.workshop_path, exp.trigger, position_model)
    assert integrity["passed"] is False
    assert any("candidate input mutation is forbidden" in error for error in integrity["structure"]["errors"])
    assert result["passed"] is False
