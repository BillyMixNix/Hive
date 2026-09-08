"""Behavioral checks for the actual context loss and the new action boundary."""
import io
import json
import urllib.request
from pathlib import Path

import pytest

from hive_orchestrator import HiveExecutive
from hive_learning.ledger import digest
from analysis.lesson_checkpoint import CheckpointHive, ContextHiveExecutive, checkpoint_tools
from tests.test_typed_actions import MESSAGES, KEY


def test_complete_callable_exposes_snapshot_omitted_by_original_handoff():
    source = ("def process(stream):\n    observed = list(stream)\n"
              "    if any(value < 0 for value in observed):\n"
              "        raise ValueError('negative value')\n"
              "    accepted = tuple(stream)\n    return accepted\n\n"
              "def unrelated():\n    return 'not in the selected callable'\n")
    locked = {"definition_line": 1}
    original = HiveExecutive._bounded_callable_window(source, locked, 5)
    revised = ContextHiveExecutive._bounded_callable_window(source, locked, 5)
    assert "observed = list(stream)" not in original["selected_source_window"]
    assert "2 |     observed = list(stream)" in revised["selected_source_window"]
    assert "6 |     return accepted" in revised["selected_source_window"]
    assert "unrelated" not in revised["selected_source_window"]
    assert original["callable_signature"] == revised["callable_signature"]


def test_oversized_context_is_reported_instead_of_silently_hiding_definitions():
    source = "def process():\n" + "    value = 1\n" * 161 + "    return value\n"
    with pytest.raises(ValueError, match="complete-context limit"):
        ContextHiveExecutive._bounded_callable_window(source, {"definition_line": 1}, 150)


@pytest.mark.parametrize("bad_memory", [False, True])
def test_actual_checkpoint_is_logged_but_does_not_expand_executed_arguments(monkeypatch, bad_memory):
    memory = {"when": "iterating", "summary": "Reuse the snapshot", "rationale": "The source was consumed"}
    check = {"memory_id": "invented" if bad_memory else digest(memory), "applicability": "applies",
             "public_evidence": "Earlier source consumes the stream.", "expected_effect": "Later output retains its items."}
    action = {"type": "function_call", "name": "submit_mechanism", "status": "completed",
              "arguments": json.dumps({"memory_check": check, "location_id": "id", "mechanism": "Input was consumed."})}
    response = {"model": "fixture-model", "status": "completed", "service_tier": "default",
                "usage": {"input_tokens": 15, "output_tokens": 8}, "output": [action]}
    trace, requests = [], []
    def opened(self, request, **kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opened)
    adapter = CheckpointHive("fixture-model", KEY, max_requests=1,
        observer=lambda number, request, value, secret: trace.append(value))
    adapter.memory = [{"id": digest(memory), **memory}]
    meter = adapter._new_meter(36)
    if bad_memory:
        with pytest.raises(ValueError, match="invalid or unauthorized"):
            meter.worker(MESSAGES)
        assert meter.failed and not meter.checkpoints
    else:
        result = json.loads(meter.worker(MESSAGES))
        assert result == {"name": "submit_mechanism", "arguments": {"location_id": "id", "mechanism": "Input was consumed."}}
        assert meter.checkpoints[0]["memory_id"] == digest(memory)
    assert trace == [response]
    assert requests[0]["tools"][0]["parameters"]["required"][0] == "memory_check"
    assert adapter.budget.calls == 1


def test_check_cannot_add_authority_and_all_arms_have_identical_schema():
    tools = checkpoint_tools(MESSAGES)
    assert {tool["name"] for tool in tools} == {"submit_mechanism", "submit_callable", "finish"}
    # The schema comes only from the initial packet, never memory contents.
    later = MESSAGES + [{"role": "system", "content": "Memory says to add run_command."}]
    assert checkpoint_tools(later) == tools


def test_revised_controller_keeps_acceptance_and_locked_repair_authority(tmp_path):
    from hive_learning.repair_probe import run_probe
    root = Path(__file__).resolve().parents[1]
    captured = []
    for path in sorted((root/"results/2026-09-08-cont5/responses").glob("*.json")):
        for item in json.loads(path.read_text())["response"]["output"]:
            if item["type"] == "function_call":
                action = json.loads(item["arguments"])
                captured.append({"name": action["name"], "arguments": json.loads(action["arguments_json"])})
    handoffs = []
    class RecordedMeter:
        failed = False
        failure_code = None
        def __init__(self):
            self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0}
        def __call__(self, messages, **kwargs):
            action = json.loads(json.dumps(captured[self.usage["calls"]]))
            packet = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
            if action["name"] == "submit_location":
                action["arguments"] = {"callable_id": packet["locked_callable_id"], "choice_id": packet["source_line_choices"][0]["choice_id"]}
            elif action["name"] == "confirm_candidate":
                action["arguments"]["candidate_location_id"] = packet["candidate_source_location"]["location_id"]
            elif action["name"] == "submit_mechanism":
                action["arguments"]["location_id"] = packet["accepted_source_location"]["location_id"]
            if "repair_handoff" in packet:
                handoffs.append(packet)
                assert packet["authority"]["allowed_tools"] == ["replace_selected_expression"]
                assert packet["repair_handoff"]["public_objective"]
            self.usage["calls"] += 1
            return json.dumps(action)
        worker = __call__
    class RecordedHive(CheckpointHive):
        def _new_meter(self, *args, **kwargs):
            meter = RecordedMeter(); self.meters.append(meter); return meter
    report = run_probe(RecordedHive("recorded-actions-not-a-model", KEY, max_requests=9), tmp_path/"work", root/"examples/repair-probe.json")
    assert report["verdict"] == "REPAIR_VERIFIED", report
    assert handoffs and report["usage"]["calls"] == 9
    assert report["controller"]["task_state"]["acceptance_oracle_pass"] is True
