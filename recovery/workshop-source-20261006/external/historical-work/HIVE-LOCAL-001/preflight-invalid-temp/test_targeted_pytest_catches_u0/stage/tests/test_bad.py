def test_health_version():
    response = api('/api/health')
    assert response['version'] == app.version
