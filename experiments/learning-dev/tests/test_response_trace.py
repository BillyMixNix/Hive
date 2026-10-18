"""Reproduce rejected envelopes offline while preserving private boundaries."""
import io
import json
from pathlib import Path
import urllib.request

import pytest

from hive_learning.cloud_continue import read_plan
from hive_learning.openai_adapter import OpenAIHive
from hive_learning.response_trace import ResponseTrace


def test_trace_preserves_rejected_native_action_without_credentials_or_reasoning(monkeypatch, tmp_path):
    key = "test_credential_not_a_real_api_key"
    model = "fixture"
    response = {"model": model, "status": "completed", "error": None,
                "usage": {"input_tokens": 20, "output_tokens": 10},
                "output": [{"type": "reasoning", "encrypted_content": "private-encrypted",
                            "summary": [{"type": "summary_text", "text": "private-reasoning"}]},
                           {"type": "function_call", "name": "run_command", "call_id": "private-id",
                            "arguments": json.dumps({"command": "python -m pytest", "extra": key})}]}
    seen = []
    def opened(self, req, **kwargs):
        seen.append(req)
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opened)
    adapter = OpenAIHive(model, key, max_requests=2, observer=ResponseTrace(tmp_path / "responses"))
    with pytest.raises(ValueError, match="one assistant message"):
        adapter._new_meter(36)([{"role": "user", "content": "Return JSON."}])
    raw = (tmp_path / "responses/response-0001.json").read_text()
    for private in (key, "private-reasoning", "private-encrypted", "private-id"):
        assert private not in raw
    trace = json.loads(raw)
    assert trace["response"]["output"][1]["name"] == "run_command"
    assert "python -m pytest" in trace["response"]["output"][1]["arguments"]
    assert trace["response"]["output"][0] == {"type": "reasoning"}
    assert len(seen) == 1 and adapter.observed_usage()[0]["failure_code"] == "unexpected_output_items"


def test_committed_continuation_carries_both_previous_attempts():
    root = Path(__file__).resolve().parents[1]
    plan, prior = read_plan(root)
    assert plan["max_requests"] in {2, 36, 325}
    assert prior["spending"]["total_upper_nano_usd"] >= 1868900
