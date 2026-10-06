
from fastapi.testclient import TestClient
import app
from workshop import db, router

client = TestClient(app.app)

def test_cloud_gate_does_not_persist_user_message(monkeypatch):
    chat = db.create_chat("cloud gate")

    async def fake_status():
        return (False, [])
    monkeypatch.setattr(app.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app.providers, "openai_key", lambda: "fake")
    monkeypatch.setattr(
        app.router,
        "choose",
        lambda *a, **k: router.Route("openai","gpt-5.6-luna","test")
    )

    old = app.ASK_BEFORE_CLOUD
    app.ASK_BEFORE_CLOUD = True
    try:
        r = client.post("/api/chat", json={
            "chat_id":chat["id"],
            "text":"do not persist",
            "mode":"auto",
            "model":"gpt-5.6-luna",
            "local_model":"qwen3.5:9b",
            "effort":"medium",
            "web":False,
            "allow_cloud":False
        })
        assert r.status_code == 409
        assert db.get_messages(chat["id"], 10) == []
    finally:
        app.ASK_BEFORE_CLOUD = old

def test_local_failure_fallback_requires_cloud_approval(monkeypatch):
    chat = db.create_chat("fallback gate")

    async def fake_status():
        return (True, ["qwen3.5:9b"])
    async def fail_local(*a, **k):
        raise RuntimeError("local failed")

    monkeypatch.setattr(app.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app.providers, "ollama_chat", fail_local)
    monkeypatch.setattr(app.providers, "openai_key", lambda: "fake")
    monkeypatch.setattr(
        app.router,
        "choose",
        lambda *a, **k: router.Route("ollama","qwen3.5:9b","test local")
    )

    old = app.ASK_BEFORE_CLOUD
    app.ASK_BEFORE_CLOUD = True
    try:
        r = client.post("/api/chat", json={
            "chat_id":chat["id"],
            "text":"fallback test",
            "mode":"auto",
            "model":"gpt-5.6-luna",
            "local_model":"qwen3.5:9b",
            "effort":"medium",
            "web":False,
            "allow_cloud":False
        })
        assert r.status_code == 409
        assert "Cloud escalation requires approval" in r.json()["detail"]
    finally:
        app.ASK_BEFORE_CLOUD = old
