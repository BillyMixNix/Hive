import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from analysis.packet_adapter import PacketContractHive, PacketIteratorHive, recipient_adapter
from analysis.indexed_checkpoint import IndexedCheckpointHive, indexed_tools
from analysis.public_contracts import InputPreservation
from hive_learning.evaluate import write_files


MESSAGES = [{"role": "system", "content": "Use offered tools."},
    {"role": "user", "content": json.dumps({"authority": {"allowed_tools": ["submit_mechanism"]},
     "tool_contracts": [{"name": "submit_mechanism", "arguments": {"location_id": "id", "mechanism": "text"}}]})}]


@pytest.fixture
def adapter(tmp_path):
    a = PacketIteratorHive("offline", "fixture_not_a_real_key", condition="packet", max_requests=36)
    a._packet_root = tmp_path
    a._packet_goal = "Repair public function"
    a._packet_baseline = {"source.py": "x = 1\n"}
    write_files(tmp_path, a._packet_baseline)
    return a


def test_same_state_and_tools_across_conditions(adapter):
    original = deepcopy(MESSAGES)
    states = []
    for arm in ("raw", "lessons", "packet"):
        adapter.condition = arm
        messages = adapter._prepare_packet_messages(MESSAGES)
        assert indexed_tools(messages) == indexed_tools(MESSAGES)
        states.append(json.loads(json.loads(messages[1]["content"])["hive_state_context"]))
    assert states[0] == states[1] == states[2]
    assert MESSAGES == original


def test_current_bytes_and_claim_status(adapter):
    one = adapter._prepare_packet_messages(MESSAGES)
    write_files(adapter._packet_root, {"source.py": "x = 2\n"})
    two = adapter._prepare_packet_messages(MESSAGES + [{"role": "assistant", "content": "Tests pass"}])
    first = json.loads(json.loads(one[1]["content"])["hive_state_context"])
    second = json.loads(json.loads(two[1]["content"])["hive_state_context"])
    assert first["snapshot_sha256"] != second["snapshot_sha256"]
    assert second["state"]["events"][0]["status"] == "unverified"


def test_worker_wrapper_is_on_request_path(adapter, monkeypatch):
    seen = []
    fake = SimpleNamespace(worker=lambda messages: seen.append(messages) or "action")
    monkeypatch.setattr(IndexedCheckpointHive, "_new_meter", lambda *a, **k: fake)
    meter = adapter._new_meter(36)
    assert meter.worker(MESSAGES) == "action"
    assert "hive_state_context" in json.loads(seen[0][1]["content"])
    assert len(adapter.packet_records) == 1


def test_nonlesson_guidance_and_reuse_rejected(adapter):
    with pytest.raises(ValueError): adapter.work(adapter._packet_root, "goal", ["advice"], 36)
    adapter._packet_started = True
    with pytest.raises(ValueError): adapter.work(adapter._packet_root, "goal", [], 36)


def test_factory_keeps_contract_and_iterator_paths():
    assert isinstance(recipient_adapter("offline", "fixture_not_a_real_key", condition="raw", max_requests=36), PacketIteratorHive)
    assert isinstance(recipient_adapter("offline", "fixture_not_a_real_key", condition="packet", max_requests=36,
        contracts=[InputPreservation("source.py", "f", ("x",))]), PacketContractHive)


@pytest.mark.parametrize("condition", ["raw", "lessons", "packet"])
def test_recorded_repair_through_real_controller(tmp_path, monkeypatch, condition):
    from analysis.indexed_checkpoint import IndexedCheckpointMeter
    from hive_learning.repair_probe import run_probe
    root = Path(__file__).resolve().parents[1]
    actions = []
    for path in sorted((root/"results/2026-09-08-cont5/responses").glob("*.json")):
        for item in json.loads(path.read_text())["response"]["output"]:
            if item["type"] == "function_call":
                action = json.loads(item["arguments"])
                actions.append({"name": action["name"], "arguments": json.loads(action["arguments_json"])})
    assert len(actions) == 9
    seen = []
    def replay(self, messages):
        packet = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
        assert "hive_state_context" in packet
        seen.append(packet)
        action = deepcopy(actions[self.usage["calls"]])
        if action["name"] == "submit_location":
            action["arguments"] = {"callable_id": packet["locked_callable_id"], "choice_id": packet["source_line_choices"][0]["choice_id"]}
        elif action["name"] in {"confirm_candidate", "submit_mechanism"}:
            key = "candidate_location_id" if action["name"] == "confirm_candidate" else "location_id"
            location = packet["candidate_source_location"] if key == "candidate_location_id" else packet["accepted_source_location"]
            action["arguments"][key] = location["location_id"]
        self.usage["calls"] += 1
        return json.dumps(action)
    monkeypatch.setattr(IndexedCheckpointMeter, "worker", replay)
    # Any accidental provider request is a test failure.
    import urllib.request
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *a, **k: pytest.fail("network forbidden"))
    a = PacketContractHive("offline", "fixture_not_a_real_key", condition=condition, max_requests=36,
        contracts=[InputPreservation("capacity.py", "admit", ("quantity", "capacity"))])
    report = run_probe(a, tmp_path/"work", root/"examples/repair-probe.json")
    assert report["verdict"] == "REPAIR_VERIFIED", report
    assert len(seen) == len(a.packet_records) == report["usage"]["calls"] == 9
