import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from workshop import chat_agent, db

client = TestClient(app_module.app)


def test_read_only_repository_observation(tmp_path):
    (tmp_path / "sample.py").write_text("def alpha():\n    return 42\n", encoding="utf-8")
    result = chat_agent.execute(tmp_path, tmp_path / "runs", "search_text", {"query": "alpha"})
    assert result["ok"] is True
    assert "sample.py:1" in result["result"]


def test_inspect_run_is_bounded_and_diagnostic(tmp_path):
    runs = tmp_path / "runs"
    rd = runs / "abc123"
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(json.dumps({
        "id":"abc123", "request":"demo", "status":"rejected", "applied":False,
        "errors":[{"role":"planner","stage":"plan_validation","exception_message":"bad contract"}],
        "huge_unrelated_field":"x" * 20000,
    }), encoding="utf-8")
    result = chat_agent.execute(tmp_path, runs, "inspect_run", {"run_id":"abc123"})
    assert "bad contract" in result["result"]
    assert "huge_unrelated_field" not in result["result"]
    assert len(result["result"]) <= chat_agent.MAX_RUN_RESULT_CHARS + 30


def test_inspect_run_rejects_traversal(tmp_path):
    try:
        chat_agent.execute(tmp_path, tmp_path / "runs", "inspect_run", {"run_id":"../secret"})
    except ValueError as exc:
        assert "simple run_id" in str(exc)
    else:
        raise AssertionError("traversal run id was accepted")


def test_local_chat_can_observe_then_answer(monkeypatch):
    chat = db.create_chat("observation loop")
    calls=[]

    async def fake_status():
        return True, ["qwen2.5-coder:14b"]

    async def fake_chat(model, messages, instructions, image_data_url=None, **kwargs):
        calls.append((messages, instructions, kwargs))
        if len(calls) == 1:
            return {
                "text": json.dumps({"status":"observe","operation":"search_text","arguments":{"query":"FastAPI","path":"app.py"},"reason":"Locate app framework."}),
                "input_tokens":10, "output_tokens":5,
            }
        assert "READ-ONLY WORKSHOP OBSERVATION 1/6" in messages[-1]["content"]
        assert "FastAPI" in messages[-1]["content"]
        return {"text":json.dumps({"status":"answer","text":"Workshop uses FastAPI."}), "input_tokens":12, "output_tokens":6}

    monkeypatch.setattr(app_module.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app_module.providers, "ollama_chat", fake_chat)
    response=client.post("/api/chat", json={
        "chat_id":chat["id"], "text":"What framework does Workshop use?",
        "mode":"local", "local_model":"qwen2.5-coder:14b",
    })
    assert response.status_code == 200
    body=response.json()
    assert body["text"] == "Workshop uses FastAPI."
    assert body["observations"] == 1
    assert body["input_tokens"] == 22
    assert body["output_tokens"] == 11
    assert len(calls) == 2
    assert calls[0][2].get("response_format") == chat_agent.response_schema()
    persisted=db.get_messages(chat["id"], 10)
    assert [m["role"] for m in persisted] == ["user", "assistant"]
    assert persisted[-1]["content"] == "Workshop uses FastAPI."


def test_cloud_chat_remains_single_call_without_observation_protocol(monkeypatch):
    chat = db.create_chat("cloud unchanged")
    captured={}
    async def fake_status(): return False, []
    async def fake_openai(model, messages, instructions, *args, **kwargs):
        captured["instructions"] = instructions
        return {"text":"cloud answer", "input_tokens":4, "output_tokens":2}
    monkeypatch.setattr(app_module.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app_module.providers, "openai_key", lambda: "fake")
    monkeypatch.setattr(app_module.providers, "openai_chat", fake_openai)
    old=app_module.ASK_BEFORE_CLOUD
    app_module.ASK_BEFORE_CLOUD=False
    try:
        response=client.post("/api/chat", json={
            "chat_id":chat["id"], "text":"hello", "mode":"cloud", "model":"gpt-5.6-luna", "allow_cloud":True,
        })
    finally:
        app_module.ASK_BEFORE_CLOUD=old
    assert response.status_code == 200
    assert response.json()["text"] == "cloud answer"
    assert response.json()["observations"] == 0
    assert "For each investigation turn, return ONLY one JSON object" not in captured["instructions"]


def test_schema_exposes_read_only_run_tools():
    schema=json.dumps(chat_agent.response_schema())
    assert "inspect_recent_runs" in schema
    assert "inspect_run" in schema
    assert "search_text" in schema
    assert "status" in schema
