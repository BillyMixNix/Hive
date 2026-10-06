
from fastapi.testclient import TestClient
import app
from workshop import db, router

client = TestClient(app.app)

def test_app_forwards_configured_output_cap(monkeypatch):
    chat = db.create_chat("cap forwarding")
    seen = {}

    async def fake_status():
        return (False, [])
    async def fake_openai_chat(model, messages, instructions, effort="medium", web=False,
                               image_data_url=None, max_output_tokens=None):
        seen["max_output_tokens"] = max_output_tokens
        return {
            "text":"ok",
            "input_tokens":10,
            "output_tokens":5,
            "raw_id":"fake"
        }

    monkeypatch.setattr(app.providers, "ollama_status", fake_status)
    monkeypatch.setattr(app.providers, "openai_key", lambda: "fake")
    monkeypatch.setattr(app.providers, "openai_chat", fake_openai_chat)
    monkeypatch.setattr(
        app.router,
        "choose",
        lambda *a, **k: router.Route("openai","gpt-5.6-luna","test")
    )

    old_ask = app.ASK_BEFORE_CLOUD
    old_cap = app.BUDGET_MAX_OUTPUT_TOKENS
    old_cost = app.BUDGET_MAX_TASK_COST
    app.ASK_BEFORE_CLOUD = False
    app.BUDGET_MAX_OUTPUT_TOKENS = 2048
    app.BUDGET_MAX_TASK_COST = 1.0
    try:
        r = client.post("/api/chat", json={
            "chat_id": chat["id"],
            "text":"hello",
            "mode":"manual",
            "model":"gpt-5.6-luna",
            "local_model":"qwen3.5:9b",
            "effort":"medium",
            "web":False,
            "allow_cloud":True
        })
        assert r.status_code == 200
        assert seen["max_output_tokens"] == 2048
    finally:
        app.ASK_BEFORE_CLOUD = old_ask
        app.BUDGET_MAX_OUTPUT_TOKENS = old_cap
        app.BUDGET_MAX_TASK_COST = old_cost
