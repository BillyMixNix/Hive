from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get('/health')
    assert response.json()['ok'] is True
