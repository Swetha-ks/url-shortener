from app.config import get_settings


def test_register_and_login(client):
    response = client.post("/auth/register", json={"email": "Ann@Example.com", "password": "password123"})
    assert response.status_code == 201
    assert response.json()["email"] == "ann@example.com"  # emails are normalised
    assert "password" not in response.text

    login = client.post("/auth/login", data={"username": "ann@example.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"


def test_duplicate_email_is_rejected(client):
    body = {"email": "ann@example.com", "password": "password123"}
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409


def test_short_password_is_rejected(client):
    response = client.post("/auth/register", json={"email": "ann@example.com", "password": "short"})
    assert response.status_code == 422


def test_wrong_password_returns_401(client):
    client.post("/auth/register", json={"email": "ann@example.com", "password": "password123"})
    response = client.post("/auth/login", data={"username": "ann@example.com", "password": "wrong-password"})
    assert response.status_code == 401


def test_me_requires_a_valid_token(client, auth_headers):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401

    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


def test_login_is_rate_limited(client):
    get_settings().login_limit_per_minute = 3
    for _ in range(3):
        response = client.post("/auth/login", data={"username": "x@example.com", "password": "whatever123"})
        assert response.status_code == 401
    blocked = client.post("/auth/login", data={"username": "x@example.com", "password": "whatever123"})
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers
