
from fastapi.testclient import TestClient
import app

client = TestClient(app.app)

def test_hive_capabilities_lists_bounded_agents(monkeypatch):
    async def fake_status():
        return True, ["qwen2.5-coder:14b"]
    monkeypatch.setattr(app.providers, "ollama_status", fake_status)
    r = client.get("/api/hive/capabilities")
    assert r.status_code == 200
    j = r.json()
    assert j["preferred_model"] == "qwen2.5-coder:14b"
    agents = {a["id"]:a for a in j["agents"]}
    assert agents["reviewer"]["write_scope"] == []
    assert "static/index.html" in agents["ui"]["write_scope"]

def test_hive_apply_requires_approval():
    r = client.post("/api/hive/apply", json={"run_id":"aaaaaaaaaaaa","approved":False})
    assert r.status_code == 409
