from __future__ import annotations

import shutil
from pathlib import Path

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


def test_g0_snapshot_archives_workshop_and_integrity_hashes(tmp_path):
    root = make_repo(tmp_path)
    exp = Grow0Experiment(root)
    record, snapshot = exp.freeze_g0(baseline_ref="abc", prior_suite={"passed": True})
    snapshot_dir = root / exp.config["lineage"]["snapshot_dir"] / "G0"
    archived = snapshot_dir / "workshop" / exp.workshop_path
    assert archived.is_file()
    assert archived.read_bytes() == (root / exp.workshop_path).read_bytes()
    assert record.validation_results["integrity_snapshot"]["evaluator_hash"] == snapshot.evaluator_hash
    assert record.validation_results["integrity_snapshot"]["transfer_hash"] == snapshot.transfer_hash
