import app
from fastapi.testclient import TestClient

def test_code_agent_repairs_and_runs(monkeypatch):
    calls=[]
    async def fake_chat(*args, **kwargs):
        calls.append(1)
        text='not json' if len(calls)==1 else '{"path":"hello_workshop.py","content":"print(\\"hello workshop\\")","run":true}'
        return {"text":text,"input_tokens":0,"output_tokens":0}
    monkeypatch.setattr(app.providers,"ollama_chat",fake_chat)
    monkeypatch.setattr(app,"require_mode_for_code",lambda:None)
    with TestClient(app.app) as client:
        response=client.post('/api/code/agent',json={"request":"Create hello_workshop.py","path":"hello_workshop.py"})
    assert response.status_code==200, response.text
    assert response.json()["repaired"] is True
    assert "hello workshop" in response.json()["stdout"]
