
from fastapi.testclient import TestClient
import app
from workshop import db, router

client = TestClient(app.app)

def test_openai_missing_key_does_not_persist(monkeypatch):
    chat = db.create_chat("missing key")

    async def fake_status():
        return (False, [])
    monkeypatch.setattr(app.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app.providers, "openai_key", lambda: "")
    monkeypatch.setattr(
        app.router,
        "choose",
        lambda *a, **k: router.Route("openai","gpt-5.6-luna","test")
    )

    r = client.post("/api/chat", json={
        "chat_id":chat["id"],
        "text":"should remain ephemeral",
        "mode":"manual",
        "model":"gpt-5.6-luna",
        "local_model":"qwen3.5:9b",
        "effort":"medium",
        "web":False,
        "allow_cloud":True
    })
    assert r.status_code == 412
    assert db.get_messages(chat["id"], 10) == []

def test_estimated_budget_cap_blocks_before_persist(monkeypatch):
    chat = db.create_chat("budget cap")

    async def fake_status():
        return (False, [])
    monkeypatch.setattr(app.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app.providers, "openai_key", lambda: "fake")
    monkeypatch.setattr(
        app.router,
        "choose",
        lambda *a, **k: router.Route("openai","gpt-6-astra","test")
    )

    old_cost = app.BUDGET_MAX_TASK_COST
    old_out = app.BUDGET_MAX_OUTPUT_TOKENS
    app.BUDGET_MAX_TASK_COST = 0.000001
    app.BUDGET_MAX_OUTPUT_TOKENS = 4000
    try:
        r = client.post("/api/chat", json={
            "chat_id":chat["id"],
            "text":"this should be blocked by estimate",
            "mode":"manual",
            "model":"gpt-6-astra",
            "local_model":"qwen3.5:9b",
            "effort":"medium",
            "web":False,
            "allow_cloud":True
        })
        assert r.status_code == 402
        assert db.get_messages(chat["id"], 10) == []
    finally:
        app.BUDGET_MAX_TASK_COST = old_cost
        app.BUDGET_MAX_OUTPUT_TOKENS = old_out
