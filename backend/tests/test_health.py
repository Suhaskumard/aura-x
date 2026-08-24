def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "AURA-X"


def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "github_token_configured" in body


def test_health_check_never_leaks_token_value(client):
    response = client.get("/api/v1/health")
    body = response.json()
    assert isinstance(body["github_token_configured"], bool)
    assert "github_token" not in body
