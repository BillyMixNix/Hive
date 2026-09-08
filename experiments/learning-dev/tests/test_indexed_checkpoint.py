import io
import json
import urllib.request

import pytest

from analysis.indexed_checkpoint import IndexedCheckpointHive, indexed_tools
from analysis.typed_actions import typed_action
from tests.test_typed_actions import MESSAGES, KEY


def test_actual_hash_copy_failure_cannot_be_generated_as_a_valid_indexed_choice():
    offered = indexed_tools(MESSAGES)
    for tool in offered:
        schema = tool["parameters"]["properties"]["memory_check"]["properties"]["memory_id"]
        assert schema == {"type": "string", "enum": ["none", "memory_1", "memory_2", "memory_3"]}
    action = {"type": "function_call", "name": "submit_mechanism", "status": "completed",
        "arguments": json.dumps({"location_id": "id", "mechanism": "Observed defect", "memory_check": {
            "memory_id": "8d744424340beca9a4a8d78d2b4b05dd07c67d106b5ad8e68535cc16d3abf90",
            "applicability": "applies", "public_evidence": "stream consumed", "expected_effect": "retain items"}})}
    with pytest.raises(ValueError, match="invalid or unauthorized"):
        typed_action([action], offered)


@pytest.mark.parametrize("with_memory", [True, False])
def test_short_handle_resolves_only_to_current_supplied_memory(monkeypatch, with_memory):
    adapter = IndexedCheckpointHive("fixture-model", KEY, max_requests=1)
    adapter.memory = [{"id": "provenance_hash", "summary": "Retain the snapshot"}] if with_memory else []
    meter = adapter._new_meter(36)
    action = {"type": "function_call", "name": "submit_mechanism", "status": "completed",
        "arguments": json.dumps({"location_id": "id", "mechanism": "Input consumed", "memory_check": {
            "memory_id": "memory_1", "applicability": "applies", "public_evidence": "stream consumed",
            "expected_effect": "retain items"}})}
    response = {"model": "fixture-model", "status": "completed", "service_tier": "default",
        "usage": {"input_tokens": 15, "output_tokens": 8}, "output": [action]}
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda self, request, **kwargs: io.BytesIO(json.dumps(response).encode()))
    if with_memory:
        result = json.loads(meter.worker(MESSAGES))
        assert result["arguments"] == {"location_id": "id", "mechanism": "Input consumed"}
        assert meter.checkpoints[0]["memory_id"] == "memory_1"
        assert adapter.memory == [{"id": "memory_1", "summary": "Retain the snapshot"}]
    else:
        with pytest.raises(ValueError, match="invalid or unauthorized"):
            meter.worker(MESSAGES)
        assert meter.failed
