from fastapi.testclient import TestClient
client = TestClient(app.app)
def test_health():
    assert client.get('/api/health').status_code == 200
