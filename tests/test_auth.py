def test_register_creates_user_and_returns_tokens(client):
    r = client.post("/api/auth/register", json={"name": "Jane", "email": "jane@example.com", "password": "password123"})
    assert r.status_code == 201
    body = r.json()
    assert "access_token" in body and "refresh_token" in body


def test_register_rejects_short_password(client):
    r = client.post("/api/auth/register", json={"name": "Jane", "email": "jane@example.com", "password": "short"})
    assert r.status_code == 422


def test_register_closed_after_first_user(client):
    r1 = client.post("/api/auth/register", json={"name": "Jane", "email": "jane@example.com", "password": "password123"})
    assert r1.status_code == 201
    r2 = client.post("/api/auth/register", json={"name": "Bob", "email": "bob@example.com", "password": "password123"})
    assert r2.status_code == 403
    assert r2.json()["error"] == "Registration is closed"


def test_login_success(client, test_user):
    r = client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_password(client, test_user):
    r = client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrongpass"})
    assert r.status_code == 401
    assert r.json()["error"] == "Invalid email or password"


def test_login_unknown_email(client):
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "password123"})
    assert r.status_code == 401


def test_refresh_returns_new_tokens(client, test_user):
    login = client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
    refresh_token = login.json()["refresh_token"]
    r = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_refresh_rejects_access_token(client, test_user):
    login = client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
    access_token = login.json()["access_token"]
    r = client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert r.status_code == 401


def test_get_me_requires_auth(client):
    r = client.get("/api/me")
    assert r.status_code == 401


def test_get_me_returns_profile(client, auth_headers):
    r = client.get("/api/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "test@example.com"


def test_update_me_updates_fields(client, auth_headers):
    r = client.put("/api/me", headers=auth_headers, json={"headline": "Senior Dev", "location": "London"})
    assert r.status_code == 200
    body = r.json()
    assert body["headline"] == "Senior Dev"
    assert body["location"] == "London"


def test_update_me_rejects_empty_payload(client, auth_headers):
    r = client.put("/api/me", headers=auth_headers, json={})
    assert r.status_code == 400


def test_change_password_success(client, auth_headers):
    r = client.put("/api/me/password", headers=auth_headers, json={
        "current_password": "password123", "new_password": "newpassword456",
    })
    assert r.status_code == 200

    # old password no longer works, new one does
    stale = client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
    assert stale.status_code == 401
    fresh = client.post("/api/auth/login", json={"email": "test@example.com", "password": "newpassword456"})
    assert fresh.status_code == 200


def test_change_password_rejects_wrong_current(client, auth_headers):
    r = client.put("/api/me/password", headers=auth_headers, json={
        "current_password": "wrongpass", "new_password": "newpassword456",
    })
    assert r.status_code == 400


def test_bad_bearer_token_rejected(client):
    r = client.get("/api/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
