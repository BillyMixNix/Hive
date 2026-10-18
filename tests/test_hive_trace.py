import json

from hive_trace import record_model_call, trace_enabled


def test_trace_disabled_without_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("HIVE_TRACE_DIR", raising=False)
    monkeypatch.delenv("HIVE_TRACE_RUN_ID", raising=False)
    assert trace_enabled() is False

    record_model_call(
        provider="ollama",
        model="test-model",
        role="coder",
        prompt="exact prompt",
        response="exact response",
        success=True,
        started_at=1.0,
        elapsed_seconds=0.5,
    )
    assert list(tmp_path.iterdir()) == []


def test_trace_preserves_exact_prompt_and_response(monkeypatch, tmp_path):
    monkeypatch.setenv("HIVE_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("HIVE_TRACE_RUN_ID", "real-run-001")
    assert trace_enabled() is True

    prompt = "Human wording stays EXACT.\nTool output: {\"x\": 1}"
    response = "model response\nunchanged"
    record_model_call(
        provider="ollama",
        model="qwen-test",
        role="coder",
        prompt=prompt,
        response=response,
        success=True,
        started_at=10.0,
        elapsed_seconds=2.5,
        timeout_seconds=120,
        usage={"prompt_eval_count": 321, "eval_count": 12},
        attempt=1,
    )

    path = tmp_path / "real-run-001.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["prompt"] == prompt
    assert row["response"] == response
    assert row["provider"] == "ollama"
    assert row["role"] == "coder"
    assert row["usage"]["prompt_eval_count"] == 321
    assert row["success"] is True
