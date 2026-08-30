import json
from pathlib import Path

import hive.watcher as watcher
from hive.watcher import Resolution


class ResolvedAdapter:
    def __init__(self, token=None): pass
    def check(self, dependency):
        return Resolution(True, "success", {"run_id": dependency["run_id"]})


class WaitingAdapter:
    def __init__(self, token=None): pass
    def check(self, dependency):
        return Resolution(False, evidence={"status": "in_progress"})


def write_state(tmp_path, dependency):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"waiting_on": dependency}))
    return p


def test_resolved_dependency_enqueues_resume_event(tmp_path, monkeypatch):
    monkeypatch.setitem(watcher.ADAPTERS, "fake", ResolvedAdapter)
    state = write_state(tmp_path, {"kind": "fake", "run_id": 42})
    queue = tmp_path / "events.jsonl"
    assert watcher.watch_once(state, queue) == 1
    event = json.loads(queue.read_text().strip())
    assert event["kind"] == "dependency_resolved"
    assert event["result"] == "success"
    assert event["evidence"]["run_id"] == 42


def test_unresolved_dependency_does_not_emit_event(tmp_path, monkeypatch):
    monkeypatch.setitem(watcher.ADAPTERS, "fake", WaitingAdapter)
    state = write_state(tmp_path, {"kind": "fake", "run_id": 42})
    queue = tmp_path / "events.jsonl"
    assert watcher.watch_once(state, queue) == 0
    assert not queue.exists()


def test_no_dependency_is_idle(tmp_path):
    state = write_state(tmp_path, None)
    queue = tmp_path / "events.jsonl"
    assert watcher.watch_once(state, queue) == 0
    assert not queue.exists()
