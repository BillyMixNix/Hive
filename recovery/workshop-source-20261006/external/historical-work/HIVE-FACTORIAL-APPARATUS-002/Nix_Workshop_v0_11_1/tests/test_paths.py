
from fastapi.testclient import TestClient
import app

client=TestClient(app.app)

def test_empty_path_400():
    r=client.post("/api/file",json={"path":"","content":"x"})
    assert r.status_code==400

def test_absolute_path_400():
    p=str((app.WORKSPACE/"absolute.py").resolve())
    r=client.post("/api/file",json={"path":p,"content":"x"})
    assert r.status_code==400

def test_dotfiles_hidden_from_list():
    (app.WORKSPACE/".keep").write_text("",encoding="utf-8")
    r=client.get("/api/files")
    assert r.status_code==200
    assert all(not item["path"].startswith(".") for item in r.json())

def test_fake_chat_404():
    r=client.post("/api/chat",json={"chat_id":"fake","text":"hello"})
    assert r.status_code==404
