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


def test_google_login_callback_rejects_bad_state(client):
    r = client.get("/auth/google/login/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "error=token_failed" in r.headers["location"]
