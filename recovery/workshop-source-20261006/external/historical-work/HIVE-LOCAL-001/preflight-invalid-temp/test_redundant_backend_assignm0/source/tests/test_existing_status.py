from fastapi.testclient import TestClient
import app

client = TestClient(app.app)

def test_existing_status_contract():
    response = client.get('/api/status')
    assert response.status_code == 200
    assert response.json()['ollama'] is True
