from app.core.config import settings


def test_google_login_start_redirects_to_google(client):
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]


def test_google_login_start_redirects_to_login_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/login?error=not_configured" in r.headers["location"]


def test_google_connect_requires_auth(client):
    r = client.get("/auth/google", follow_redirects=False)
    assert r.status_code == 401


def test_google_connect_start_redirects_with_valid_token(client, auth_headers):
    token = auth_headers["Authorization"].split(" ")[1]
    r = client.get(f"/auth/google?token={token}", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]


def test_google_login_callback_rejects_bad_state(client):
    r = client.get("/auth/google/login/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "error=token_failed" in r.headers["location"]


def test_google_connect_callback_rejects_bad_state(client):
    r = client.get("/auth/google/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code in (302, 307)


def test_gmail_status_requires_auth(client):
    r = client.get("/api/gmail/status")
    assert r.status_code == 401


def test_gmail_status_empty_when_nothing_connected(client, auth_headers):
    r = client.get("/api/gmail/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"primary": None, "scan": None}


def test_gmail_disconnect_rejects_login_provider(client, auth_headers):
    r = client.post("/api/gmail/disconnect", headers=auth_headers, json={"provider": "google_login"})
    assert r.status_code == 400


def test_gmail_disconnect_scan_provider_succeeds(client, auth_headers):
    r = client.post("/api/gmail/disconnect", headers=auth_headers, json={"provider": "google_scan"})
    assert r.status_code == 200
