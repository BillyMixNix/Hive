import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.store import Store
from jarvis.supervisor import Supervisor
from hive_learning.adapter import Meter, OllamaHive
from hive_learning.demo import LESSON, ScriptedAdapter, seed_failure, suite
from hive_learning.evaluate import candidate_snapshot, read_suite, strict_json, write_files
from hive_learning.ledger import begin, bank, digest, retire
from hive_learning.loop import run


@pytest.fixture
def episode(tmp_path):
    store = Store(tmp_path / "state" / "jarvis.db")
    task = seed_failure(store, tmp_path / "failed")
    path = tmp_path / "suite.json"
    raw = json.dumps(suite()).encode()
    path.write_bytes(raw)
    return store, task, path, hashlib.sha256(raw).hexdigest()


def fast_grade(candidate, protected, timeout=30):
    # Gate fault injection only. Full evaluator is used by end-to-end test.
    text = "\n".join(candidate.values())
    return {"valid": True, "passed": " < " not in text and "BROKEN" not in text}


def test_complete_loop_runs_real_evaluators_and_quarantines_simulation(episode):
    report = run(*episode, ScriptedAdapter())
    assert report["verdict"] == "PROMOTED"
    assert report["transfer_passes"] == {"baseline": 0, "lesson": 1, "neutral": 0}
    assert report["scope"] == "development_simulated"
    store = Store(episode[0].path)
    assert store.verify_chain()[0]
    assert store.guidance() == []
    assert store.guidance(learning_scope="development_simulated")[0]["summary"] == LESSON["summary"]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='OUTCOME_RECORDED'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='LEARNING_CANDIDATE'").fetchone()[0] == 9


@pytest.mark.parametrize("failure", ["no_gain", "neutral_gain", "retention", "test_edit", "transport", "budget", "identity"])
def test_bad_episodes_cannot_guide_later_tasks(episode, failure):
    class Faulty(ScriptedAdapter):
        def __init__(self):
            self.identity = dict(ScriptedAdapter.identity)
        def repair(self, root, goal, lessons, calls):
            if failure == "transport":
                raise ConnectionError("simulated disconnect")
            if failure == "no_gain":
                return {"calls": 1, "prompt_tokens": 0, "output_tokens": 0}
            active = any(item.get("summary") == LESSON["summary"] for item in lessons)
            effective = [LESSON] if failure == "neutral_gain" and lessons else lessons
            usage = super().repair(root, goal, effective, calls)
            if failure == "retention" and active and (root / "arithmetic.py").exists():
                (root / "arithmetic.py").write_text("# BROKEN\ndef add(a,b): return 0\n")
            if failure == "test_edit":
                (root / "test_visible.py").write_text("def test_nothing(): pass\n")
            if failure == "budget": usage["calls"] = calls + 1
            if failure == "identity": self.identity["model"] = "changed"
            return usage
    with patch("hive_learning.loop.grade", fast_grade):
        report = run(*episode, Faulty())
    assert report["verdict"] in {"REJECTED", "INVALID"}
    assert episode[0].guidance(learning_scope="development_simulated") == []
    assert episode[0].verify_chain()[0]


def test_proposer_and_recipient_never_receive_protected_tests(episode):
    class Inspecting(ScriptedAdapter):
        def propose(self, packet):
            assert set(packet) == {"schema", "failure", "parent_lessons"}
            assert "protected_tests" not in json.dumps(packet)
            assert "deadline" not in json.dumps(packet)
            return super().propose(packet)
        def repair(self, root, goal, lessons, calls):
            assert not (root / "test_protected.py").exists()
            assert all("protected_tests" not in item for item in lessons)
            return super().repair(root, goal, lessons, calls)
    with patch("hive_learning.loop.grade", fast_grade):
        assert run(*episode, Inspecting())["verdict"] == "PROMOTED"


def test_restart_cannot_reconsume_suite_or_retry_interrupted_episode(episode):
    store, task, path, sha = episode
    config = {"adapter": ScriptedAdapter.identity}
    begin(store, task, sha, config, read_suite(path, sha))
    with pytest.raises(ValueError, match="consumed"):
        run(Store(store.path), task, path, sha, ScriptedAdapter())
    data = suite(); data["suite_id"] = "other"
    raw = json.dumps(data).encode(); path.write_bytes(raw)
    with pytest.raises(ValueError, match="unfinished"):
        run(Store(store.path), task, path, hashlib.sha256(raw).hexdigest(), ScriptedAdapter())


def test_invalid_proposal_is_recorded_and_consumed(episode):
    class Bad(ScriptedAdapter):
        def propose(self, packet): return {"summary": "missing fields"}, {}
    assert run(*episode, Bad())["verdict"] == "INVALID"
    with pytest.raises(ValueError, match="consumed"):
        run(*episode, ScriptedAdapter())


def test_second_generation_inherits_bank_and_every_previous_case(episode):
    store, task, path, sha = episode
    with patch("hive_learning.loop.grade", fast_grade):
        first = run(*episode, ScriptedAdapter())
    assert first["verdict"] == "PROMOTED"
    new = suite(); new["suite_id"] = "second-development-episode"
    for case in new["cases"]:
        case["id"] += "-new"
        case["files"] = {p: "# distinct development fixture\n" + text for p, text in case["files"].items()}
    raw = json.dumps(new).encode(); path.write_bytes(raw)
    class InspectParent(ScriptedAdapter):
        def propose(self, packet):
            assert packet["parent_lessons"][0]["summary"] == LESSON["summary"]
            return super().propose(packet)
    with patch("hive_learning.loop.grade", fast_grade):
        report = run(store, task, path, hashlib.sha256(raw).hexdigest(), InspectParent())
    assert report["inherited_retention_cases"] == 3
    assert report["verdict"] == "REJECTED"  # Existing lesson already solves the transfer.
    assert len(store.guidance(learning_scope="development_simulated")) == 1


def test_retiring_parent_during_episode_invalidates_promotion(episode):
    store, task, path, sha = episode
    with patch("hive_learning.loop.grade", fast_grade):
        first = run(*episode, ScriptedAdapter())
    new = suite()
    for case in new["cases"]:
        case["files"] = {p: "# next episode\n" + text for p, text in case["files"].items()}
    raw = json.dumps(new).encode(); path.write_bytes(raw)
    class Retiring(ScriptedAdapter):
        def propose(self, packet):
            retire(store, first["episode_id"], "retired while evaluation was active")
            return super().propose(packet)
    with patch("hive_learning.loop.grade", fast_grade):
        report = run(store, task, path, hashlib.sha256(raw).hexdigest(), Retiring())
    assert report["verdict"] == "INVALID"
    assert report["reason"] == "parent bank changed during episode"


def test_promoted_production_scope_reaches_actual_supervisor_handoff(episode, tmp_path):
    # Test double for a real transport: proves routing only, not model capability.
    adapter = ScriptedAdapter()
    adapter.identity = dict(adapter.identity, scope="development_real_model")
    with patch("hive_learning.loop.grade", fast_grade):
        assert run(*episode, adapter)["verdict"] == "PROMOTED"
    store = Store(episode[0].path)
    workspace = tmp_path / "next-task"; workspace.mkdir()
    task = store.create(kind="agent", goal="Inspect an inclusive deadline boundary", workspace=str(workspace),
                        payload={}, mutating=False)
    seen = []
    with patch("jarvis.supervisor.execute", side_effect=lambda task: seen.append(copy.deepcopy(task)) or {"ok": True}):
        Supervisor(store).run_once()
    assert seen[0]["payload"]["lessons"][0]["summary"] == LESSON["summary"]
    assert store.get(task["id"])["status"] == "SUCCEEDED"
    assert store.lessons()[0]["status"] == "EXPERIMENT_VERIFIED"
    retire(store, store.lessons()[0]["id"], "Development rollback check")
    assert store.guidance() == [] and store.lessons() == []
    assert store.verify_chain()[0]


def test_ledger_tampering_blocks_learned_guidance(episode):
    with patch("hive_learning.loop.grade", fast_grade):
        run(*episode, ScriptedAdapter())
    store = episode[0]
    with store.connect() as db:
        db.execute("UPDATE events SET data='{}' WHERE type='LEARNING_FINISHED'")
    with pytest.raises(RuntimeError, match="verification"):
        store.guidance(learning_scope="development_simulated")


def test_suite_hash_paths_duplicates_and_symlinks_fail_closed(episode, tmp_path):
    with pytest.raises(ValueError, match="commitment"):
        read_suite(episode[2], "0" * 64)
    with pytest.raises(ValueError, match="duplicate"):
        strict_json('{"x":1,"x":2}')
    with pytest.raises(ValueError, match="nonfinite"):
        strict_json('{"x":NaN}')
    root = tmp_path / "recipient"; root.mkdir()
    target = tmp_path / "outside.py"; target.write_text("secret")
    (root / "code.py").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        candidate_snapshot(root, {"code.py": "original"})


def test_meter_counts_failed_requests_and_never_retries():
    meter = Meter("fixture-model", "http://localhost:11434/api/chat", 1, 42)
    with patch("urllib.request.urlopen", side_effect=ConnectionError("offline")) as transport:
        with pytest.raises(ConnectionError): meter([])
        with pytest.raises(RuntimeError, match="budget"): meter([])
    assert transport.call_count == 1
    assert meter.usage["calls"] == 1 and meter.failed


def test_recovered_controller_bytes_unchanged():
    root = Path(__file__).resolve().parent.parent
    assert hashlib.sha256((root / "hive_orchestrator.py").read_bytes()).hexdigest() == (
        "c879b5f236b321f03660c21c466530156ba6cc53e8bca488342737ab8b7031e8")


def test_real_adapter_injects_guidance_only_into_workers_and_meters_every_call(tmp_path):
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, limit):
            return json.dumps({"message": {"content": "fixture response"},
                               "prompt_eval_count": 10, "eval_count": 3}).encode()
    def transport(request, **kwargs):
        seen.append(json.loads(request.data))
        return Response()
    class Executive:
        def __init__(self, root, goal, criteria, worker, judge, config):
            self.worker, self.judge = worker, judge
            from types import SimpleNamespace
            from hive_orchestrator import TaskState
            self.objective = SimpleNamespace(objective_id="fixture", task_state=TaskState())
        def add_atomic_cycle(self, **kwargs): pass
        def run_until_stable(self):
            from hive_orchestrator import ContinuationDecision
            messages = [{"role": "system", "content": "worker contract"}, {"role": "user", "content": "public task"}]
            self.worker(messages)
            self.judge(messages)
            return ContinuationDecision.SATISFIED
    adapter = OllamaHive("pinned-test-model")
    with patch("hive_learning.adapter.HiveExecutive", Executive), patch("urllib.request.urlopen", transport):
        usage = adapter.repair(tmp_path, "goal", [LESSON], 36)
    assert usage == {"calls": 2, "prompt_tokens": 20, "output_tokens": 6}
    assert LESSON["summary"] in json.dumps(seen[0])
    assert LESSON["summary"] not in json.dumps(seen[1])
    assert all(item["model"] == "pinned-test-model" for item in seen)
