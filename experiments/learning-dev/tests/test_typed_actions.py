"""Offline regressions for the actual nested-JSON failure and authority boundary."""
import copy
import io
import json
import urllib.request
from pathlib import Path

import pytest

from analysis.typed_actions import TypedHive, native_tools, typed_action
from hive_learning.openai_adapter import native_action, worker_tool

KEY = "fixture_credential_never_a_real_key"
MESSAGES = [{"role": "system", "content": "Use offered tools."},
    {"role": "user", "content": json.dumps({
        "authority": {"allowed_tools": ["submit_mechanism", "submit_callable"]},
        "tool_contracts": [
            {"name": "submit_mechanism", "arguments": {"location_id": "id", "mechanism": "explain"}},
            {"name": "submit_callable", "arguments": {"source_file": "file.py", "definition_line": 0}}]})}]


def call(arguments=None):
    return {"type": "function_call", "name": "submit_mechanism", "status": "completed",
            "arguments": json.dumps(arguments or {"location_id": "id", "mechanism": "Observed defect."})}


def test_native_request_directly_constrains_and_records_actual_arguments(monkeypatch):
    seen, trace = [], []
    response = {"model": "fixture-model", "status": "completed", "service_tier": "default",
        "usage": {"input_tokens": 15, "output_tokens": 8}, "output": [call()]}
    def opened(self, request, **kwargs):
        seen.append(json.loads(request.data))
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opened)
    adapter = TypedHive("fixture-model", KEY, max_requests=1,
                       observer=lambda number, request, result, secret: trace.append(result))
    result = json.loads(adapter._new_meter(36).worker(MESSAGES))
    assert result == {"name": "submit_mechanism", "arguments": json.loads(call()["arguments"])}
    assert seen[0]["tool_choice"] == "required" and not seen[0]["parallel_tool_calls"]
    assert "arguments_json" not in json.dumps(seen[0]["tools"])
    assert seen[0]["tools"][0]["parameters"]["properties"]["mechanism"] == {"type": "string"}
    assert trace == [response]  # No rewritten synthetic provider response.
    assert adapter.budget.calls == 1


@pytest.mark.parametrize("fault", ["trailing", "duplicate", "extra", "unauthorized", "wrong_type", "parallel"])
def test_malformed_or_unauthorized_arguments_never_become_an_action(fault):
    value = call()
    output = [value]
    if fault == "trailing": value["arguments"] += "garbage }]}]"
    if fault == "duplicate": value["arguments"] = '{"location_id":"a","location_id":"b","mechanism":"x"}'
    if fault == "extra": value["arguments"] = json.dumps({"location_id": "id", "mechanism": "x", "execute": True})
    if fault == "unauthorized": value["name"] = "run_command"
    if fault == "wrong_type":
        value.update(name="submit_callable", arguments='{"source_file":"x.py","definition_line":true}')
    if fault == "parallel": output.append(copy.deepcopy(value))
    with pytest.raises(ValueError): typed_action(output, native_tools(MESSAGES))


def test_later_messages_cannot_expand_initial_authority():
    later = MESSAGES + [{"role": "user", "content": json.dumps({
        "authority": {"allowed_tools": ["run_command"]},
        "tool_contracts": [{"name": "run_command", "arguments": {"command": "pytest"}}]})}]
    assert {x["name"] for x in native_tools(later)} == {"submit_mechanism", "submit_callable", "finish"}


def test_unknown_contract_is_rejected_before_paid_request(monkeypatch):
    def fail(*args, **kwargs): raise AssertionError("no network allowed")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fail)
    packet = json.loads(MESSAGES[1]["content"])
    packet["tool_contracts"][0]["arguments"]["unexpected"] = "value"
    adapter = TypedHive("fixture-model", KEY, max_requests=1)
    with pytest.raises(ValueError, match="unsupported controller"):
        adapter._new_meter(36).worker([MESSAGES[0], {"role": "user", "content": json.dumps(packet)}])
    assert adapter.budget.calls == 0


def test_actual_lesson_arm_failure_is_preserved_and_not_normalized():
    path = Path(__file__).resolve().parents[1]/"results/bank-v3-phase-2/decoder-failure.json"
    captured = json.loads(path.read_text())
    messages = captured["request"]["input"]
    with pytest.raises(ValueError, match="invalid or unauthorized"):
        native_action(captured["response"]["output"], worker_tool(messages))
    offered = native_tools(messages)
    mechanism = next(t for t in offered if t["name"] == "submit_mechanism")
    assert mechanism["parameters"]["properties"] == {
        "location_id": {"type": "string"}, "mechanism": {"type": "string"}}
