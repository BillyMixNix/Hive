"""Offline transport tests. Every provider response below is a fixture."""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from hive_learning import __main__ as cli, hive_agent
from hive_learning.demo import LESSON, seed_failure, suite
from hive_learning.loop import run
from hive_learning.openai_adapter import ENDPOINT, NoRedirect, OpenAIHive, load_api_key
from jarvis.store import Store


MODEL = "fixture-2026-01-01"
KEY = "test_credential_not_a_real_api_key"
MESSAGES = [{"role": "system", "content": "Return JSON."}, {"role": "user", "content": "public task"}]


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("this test must not perform network I/O")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)


def reply(text="{}"):
    return {"model": MODEL, "status": "completed", "error": None,
            "usage": {"input_tokens": 10, "output_tokens": 3},
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}]}


def transport(monkeypatch, responses):
    seen = []
    def opened(self, request, **kwargs):
        seen.append(request)
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opened)
    return seen


def test_proposal_and_worker_judge_use_stateless_responses_with_shared_accounting(monkeypatch, tmp_path):
    from hive_orchestrator import ContinuationDecision, TaskState
    seen = transport(monkeypatch, [reply(json.dumps(LESSON)), reply(), reply()])
    class Executive:
        def __init__(self, root, goal, criteria, worker, judge, config):
            self.worker, self.judge = worker, judge
            self.objective = SimpleNamespace(objective_id="fixture", task_state=TaskState())
        def add_atomic_cycle(self, **kwargs): pass
        def run_until_stable(self):
            self.worker(copy.deepcopy(MESSAGES))
            self.judge(copy.deepcopy(MESSAGES))
            return ContinuationDecision.SATISFIED
    monkeypatch.setattr("hive_learning.adapter.HiveExecutive", Executive)
    adapter = OpenAIHive(MODEL, KEY, max_requests=3, max_output_tokens=512)
    lesson, usage = adapter.propose({"failure": "public failure", "parent_lessons": []})
    assert lesson == LESSON and usage == {"calls": 1, "prompt_tokens": 10, "output_tokens": 3}
    usage = adapter.repair(tmp_path, "public goal", [lesson], 36)
    assert usage == {"calls": 2, "prompt_tokens": 20, "output_tokens": 6}
    bodies = [json.loads(request.data) for request in seen]
    assert bodies[0]["text"]["format"]["type"] == "json_schema"
    assert bodies[0]["text"]["format"]["strict"] is True
    assert bodies[1]["text"]["format"] == {"type": "json_object"}
    assert LESSON["summary"] in json.dumps(bodies[1])
    assert LESSON["summary"] not in json.dumps(bodies[2])
    assert all(body["store"] is False and body["model"] == MODEL for body in bodies)
    assert all(body["max_output_tokens"] == 512 for body in bodies)
    assert all(not {"previous_response_id", "tools", "temperature", "seed"} & body.keys() for body in bodies)
    assert all(request.full_url == ENDPOINT for request in seen)
    assert all(request.get_header("Authorization") == "Bearer " + KEY for request in seen)
    assert KEY not in json.dumps(bodies) + json.dumps(adapter.identity) + json.dumps(adapter.observed_usage())
    assert adapter.budget.calls == 3 and all(item["complete"] for item in adapter.observed_usage())


@pytest.mark.parametrize("fault", ["incomplete", "refusal", "multiple_messages", "tool_call", "model_drift",
                                  "missing_usage", "boolean_usage", "array", "duplicate_json", "two_objects",
                                  "invalid_json", "output_limit", "message_incomplete", "bad_envelope"])
def test_bad_provider_responses_invalidate_and_cannot_be_retried(monkeypatch, fault):
    value = reply()
    if fault == "incomplete": value["status"] = "incomplete"
    elif fault == "refusal": value["output"][1]["content"] = [{"type": "refusal", "refusal": "fixture"}]
    elif fault == "multiple_messages": value["output"].append(copy.deepcopy(value["output"][1]))
    elif fault == "tool_call": value["output"].append({"type": "function_call"})
    elif fault == "model_drift": value["model"] = "different-model"
    elif fault == "missing_usage": del value["usage"]
    elif fault == "boolean_usage": value["usage"]["input_tokens"] = True
    elif fault == "array": value = reply("[]")
    elif fault == "duplicate_json": value = reply('{"a":1,"a":2}')
    elif fault == "two_objects": value = reply('{} {}')
    elif fault == "invalid_json": value = reply('{"value":NaN}')
    elif fault == "output_limit": value["usage"]["output_tokens"] = 513
    elif fault == "message_incomplete": value["output"][1]["status"] = "incomplete"
    elif fault == "bad_envelope": value = b"not JSON"
    seen = transport(monkeypatch, [value])
    adapter = OpenAIHive(MODEL, KEY, max_requests=3, max_output_tokens=512)
    meter = adapter._new_meter(36)
    with pytest.raises(ValueError): meter(MESSAGES)
    with pytest.raises(RuntimeError): meter(MESSAGES)
    with pytest.raises(RuntimeError): adapter._new_meter(36)(MESSAGES)
    assert len(seen) == adapter.budget.calls == meter.usage["calls"] == 1
    assert meter.failed and adapter.budget.failed
    if fault not in {"missing_usage", "boolean_usage", "bad_envelope"}:
        assert meter.usage["prompt_tokens"] == 10


@pytest.mark.parametrize("failure", ["http", "network"])
def test_transport_errors_are_redacted_and_counted_without_retry(monkeypatch, failure):
    error = (urllib.error.HTTPError(ENDPOINT, 401, KEY, {}, io.BytesIO(KEY.encode()))
             if failure == "http" else urllib.error.URLError(KEY))
    seen = transport(monkeypatch, [error])
    adapter = OpenAIHive(MODEL, KEY, max_requests=2)
    meter = adapter._new_meter(36)
    with pytest.raises(RuntimeError) as caught: meter(MESSAGES)
    assert KEY not in str(caught.value)
    if failure == "http": assert "401" in str(caught.value)
    with pytest.raises(RuntimeError): meter(MESSAGES)
    assert len(seen) == 1 and adapter.observed_usage()[0] == {
        "calls": 1, "prompt_tokens": 0, "output_tokens": 0, "complete": False,
        "failure_code": "http_error" if failure == "http" else "network_failure"}


def test_first_validation_failure_survives_controller_retry_and_report_export(monkeypatch, tmp_path):
    store = Store(tmp_path / "jarvis.db")
    task = seed_failure(store, tmp_path / "failed-work")
    path = tmp_path / "suite.json"
    raw = json.dumps(suite()).encode(); path.write_bytes(raw)
    value = reply()
    value["status"] = "incomplete"
    seen = transport(monkeypatch, [value])
    adapter = OpenAIHive(MODEL, KEY, max_requests=325)
    report = run(store, task, path, hashlib.sha256(raw).hexdigest(), adapter)
    assert report["verdict"] == "INVALID"
    assert report["transport_usage"][0]["failure_code"] == "response_incomplete"
    with pytest.raises(RuntimeError): adapter.meters[0](MESSAGES)
    assert adapter.observed_usage()[0]["failure_code"] == "response_incomplete"
    assert len(seen) == 1 and KEY not in json.dumps(report)


def test_shared_budget_cannot_reset_at_trial_boundaries(monkeypatch):
    seen = transport(monkeypatch, [reply(), reply()])
    adapter = OpenAIHive(MODEL, KEY, max_requests=2)
    adapter._new_meter(1)(MESSAGES)
    adapter._new_meter(36)(MESSAGES)
    with pytest.raises(RuntimeError, match="episode request limit"):
        adapter._new_meter(36)(MESSAGES)
    assert len(seen) == adapter.budget.calls == 2


@pytest.mark.parametrize("fault", ["deadline", "input_limit", "recipient_limit"])
def test_local_limits_prevent_extra_requests(monkeypatch, fault):
    seen = transport(monkeypatch, [])
    adapter = OpenAIHive(MODEL, KEY, max_requests=3)
    meter = adapter._new_meter(36, deadline=-1 if fault == "deadline" else 900)
    messages = copy.deepcopy(MESSAGES)
    if fault == "input_limit": messages[1]["content"] = "x" * 250_001
    if fault == "recipient_limit": meter.cap = 0
    with pytest.raises((ValueError, RuntimeError)): meter(messages)
    assert not seen and adapter.budget.calls == 0


def test_redirect_handler_refuses_to_forward_authorization():
    request = urllib.request.Request(ENDPOINT, headers={"Authorization": "Bearer " + KEY})
    handler = NoRedirect()
    # Returning None declines the redirect; urllib's default error handler then
    # raises HTTPError. No parent opener is attached, so a follow would fail.
    assert handler.http_error_302(request, io.BytesIO(), 302, "Moved",
                                 {"location": "https://example.invalid/receive"}) is None


def test_private_env_loading_does_not_inherit_key_into_repository_children(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    assert load_api_key() == KEY
    result = subprocess.run([sys.executable, "-c",
                             "import os; print('present' if 'OPENAI_API_KEY' in os.environ else 'absent')"],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "absent"
    env = tmp_path / ".env.local"
    env.write_text('OPENAI_API_KEY="' + KEY + '"\n')
    assert load_api_key(env) == KEY and "OPENAI_API_KEY" not in os.environ
    env.write_text("OPENAI_API_KEY=" + KEY + "\nOPENAI_API_KEY=" + KEY)
    with pytest.raises(ValueError) as caught: load_api_key(env)
    assert KEY not in str(caught.value)


def test_cli_requires_explicit_openai_request_limit_before_starting_episode(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hive-learning", "run", "--data", "unused", "--task", "unused",
                                     "--suite", "unused", "--suite-sha256", "unused", "--model", MODEL,
                                     "--provider", "openai"])
    with pytest.raises(SystemExit) as caught: cli.main()
    assert caught.value.code == 2
    assert "requires --max-requests" in capsys.readouterr().err


def test_jarvis_hosted_connector_removes_key_before_controller_executes(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HIVE_PROVIDER", "openai")
    monkeypatch.setenv("HIVE_MODEL", MODEL)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    request = {"contract_version": 1, "mutating": True, "approval": "APPROVED",
               "workspace": str(tmp_path), "goal": "public goal", "lessons": [LESSON]}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
    class Adapter:
        def __init__(self, model, key, **kwargs):
            assert model == MODEL and key == KEY and kwargs["max_requests"] == 36
        def work(self, root, goal, lessons, calls):
            assert "OPENAI_API_KEY" not in os.environ and lessons == [LESSON] and calls == 36
            return {"calls": 1, "prompt_tokens": 10, "output_tokens": 3}, {"decision": "SATISFIED"}
    monkeypatch.setattr("hive_learning.openai_adapter.OpenAIHive", Adapter)
    assert hive_agent.main() == 0
    output = capsys.readouterr().out
    assert KEY not in output and json.loads(output)["usage"]["calls"] == 1


def test_openai_failure_is_consumed_with_incomplete_usage_and_no_lesson(monkeypatch, tmp_path):
    store = Store(tmp_path / "jarvis.db")
    task = seed_failure(store, tmp_path / "failed-work")
    path = tmp_path / "suite.json"
    raw = json.dumps(suite()).encode(); path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    transport(monkeypatch, [urllib.error.URLError(KEY)])
    adapter = OpenAIHive(MODEL, KEY, max_requests=325)
    report = run(store, task, path, sha, adapter)
    assert report["verdict"] == "INVALID" and report["completed_trials"] == 0
    assert report["transport_usage"][0]["calls"] == 1
    assert report["transport_usage"][0]["complete"] is False
    assert KEY not in json.dumps(report)
    assert store.guidance() == [] and store.verify_chain()[0]
    with pytest.raises(ValueError, match="consumed"):
        run(store, task, path, sha, adapter)
