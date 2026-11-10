from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from grow.core import CandidateWorkspace, ExperimentInvalid, GenerationRecord
from grow.experiment import Grow0Experiment

ROOT = Path(__file__).resolve().parents[1]


def make_repo(tmp_path: Path) -> Path:
    for path in (ROOT / "grow").rglob("*"):
        if not path.is_file() or "state" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
    return tmp_path


def test_baseline_failure_stops_freeze(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with pytest.raises(ExperimentInvalid):
        exp.freeze_g0(baseline_ref="bad", prior_suite={"passed": False})


def test_candidate_workspace_contains_no_kernel(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        assert (ws.root / exp.workshop_path).is_file()
        assert not (ws.root / exp.evaluator_path).exists()
        assert not (ws.root / exp.transfer_path).exists()
        assert not (ws.root / exp.promotion_path).exists()


def test_hidden_transfer_bundle_hash_is_pinned_by_integrity_snapshot(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    _, snap = exp.freeze_g0(baseline_ref="abc", prior_suite={"passed": True})
    before = snap.transfer_hash
    assert before
    (repo / exp.transfer_path).write_text("{}")
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        ws.write_text(exp.workshop_path, ws.read_text(exp.workshop_path) + "\n# candidate\n")
        integrity = exp.evaluate_candidate_integrity(ws, snap)
    assert integrity["checks"]["hidden_transfer_unchanged"] is False


def test_lineage_ledger_is_not_in_candidate_workspace(tmp_path):
    repo = make_repo(tmp_path)
    exp = Grow0Experiment(repo)
    with CandidateWorkspace(repo, exp.mutable_paths) as ws:
        assert not (ws.root / exp.config["lineage"]["ledger_path"]).exists()


def test_repeated_candidates_get_distinct_generation_ids(tmp_path):
    root = make_repo(tmp_path)
    exp = Grow0Experiment(root)
    exp.ledger.append({"record_type": "generation", "generation_id": "G0", "parent_id": None, "disposition": "PROMOTED"})
    exp.ledger.append({"record_type": "generation", "generation_id": "G1-A", "parent_id": "G0", "disposition": "REJECTED"})
    assert exp._next_candidate_id("G0") == "G1-B"


def test_generation_snapshot_archives_rejected_candidate_workshop(tmp_path):
    root = make_repo(tmp_path)
    exp = Grow0Experiment(root)
    with CandidateWorkspace(root, exp.mutable_paths) as workspace:
        workspace.write_text(exp.workshop_path, "def build_repair_packet(case, presentation_order='stored_first'):\n    return 'generic descendant'\n")
        record = GenerationRecord(
            generation_id="G1-A",
            parent_id="G0",
            source_workshop_snapshot_hash="before",
            model_configuration_hash=exp.model_config.config_hash,
            benchmark_bundle_id=exp.config["benchmark_bundle_id"],
            creation_timestamp="now",
            disposition="REJECTED",
        )
        path = exp._archive_generation(record, workspace=workspace)
    assert (path / "generation.json").is_file()
    archived = path / "workshop" / exp.workshop_path
    assert archived.is_file()
    assert "generic descendant" in archived.read_text(encoding="utf-8")
