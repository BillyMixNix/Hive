import json

import pytest

from workshop import hive


def ready_run(source, runs, run_id, staged_text, base_state=None):
    stage = runs / run_id / "stage"
    stage.mkdir(parents=True)
    (stage / "app.py").write_text(staged_text, encoding="utf-8")
    run = {
        "id": run_id,
        "status": "ready",
        "verification": {"passed": True},
        "review": {"approve": True},
        "applied": False,
        "changed_files": ["app.py"],
        "base_manifest": {"app.py": base_state or hive._path_state(source / "app.py")},
        "staged_manifest": {"app.py": hive._path_state(stage / "app.py")},
    }
    hive.save_run(runs, run)
    return run


def test_stale_source_is_rejected_before_write_or_backup(tmp_path, monkeypatch):
    source, runs, snapshots = tmp_path / "source", tmp_path / "runs", tmp_path / "snapshots"
    source.mkdir()
    (source / "app.py").write_text("base\n", encoding="utf-8")
    ready_run(source, runs, "a" * 12, "candidate\n")
    (source / "app.py").write_text("manual\n", encoding="utf-8")
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    with pytest.raises(hive.StaleBaseError):
        hive.apply_run(source, runs, snapshots, "a" * 12)

    assert (source / "app.py").read_text(encoding="utf-8") == "manual\n"
    assert not (snapshots / ("a" * 12)).exists()


def test_stage_tampering_is_rejected(tmp_path, monkeypatch):
    source, runs, snapshots = tmp_path / "source", tmp_path / "runs", tmp_path / "snapshots"
    source.mkdir()
    (source / "app.py").write_text("base\n", encoding="utf-8")
    ready_run(source, runs, "b" * 12, "candidate\n")
    (runs / ("b" * 12) / "stage" / "app.py").write_text("tampered\n", encoding="utf-8")
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    with pytest.raises(hive.StaleBaseError):
        hive.apply_run(source, runs, snapshots, "b" * 12)
    assert (source / "app.py").read_text(encoding="utf-8") == "base\n"


def test_reverse_order_apply_rejects_older_candidate(tmp_path, monkeypatch):
    source, runs, snapshots = tmp_path / "source", tmp_path / "runs", tmp_path / "snapshots"
    source.mkdir()
    (source / "app.py").write_text("base\n", encoding="utf-8")
    base = hive._path_state(source / "app.py")
    ready_run(source, runs, "c" * 12, "older\n", base)
    ready_run(source, runs, "d" * 12, "newer\n", base)
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    hive.apply_run(source, runs, snapshots, "d" * 12)
    with pytest.raises(hive.StaleBaseError):
        hive.apply_run(source, runs, snapshots, "c" * 12)

    assert (source / "app.py").read_text(encoding="utf-8") == "newer\n"


def test_legacy_ready_run_without_manifests_fails_closed(tmp_path):
    source, runs, snapshots = tmp_path / "source", tmp_path / "runs", tmp_path / "snapshots"
    source.mkdir()
    run_dir = runs / ("e" * 12)
    (run_dir / "stage").mkdir(parents=True)
    (run_dir / "stage" / "app.py").write_text("candidate\n", encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({
        "id": "e" * 12, "status": "ready", "verification": {"passed": True},
        "review": {"approve": True}, "applied": False, "changed_files": ["app.py"],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="stale-base protection"):
        hive.apply_run(source, runs, snapshots, "e" * 12)
