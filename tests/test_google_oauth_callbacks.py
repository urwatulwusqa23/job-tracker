from unittest.mock import MagicMock

from app.core.security import create_oauth_state_token
from app.models.oauth_token import OAuthToken
from app.models.user import User
from app.routers import google_oauth as google_oauth_router


class FakeCreds:
    def to_json(self):
        return '{"token": "fake-token-json"}'


class FakeFlow:
    def __init__(self, *a, **k):
        self.credentials = FakeCreds()
        self.redirect_uri = None

    @classmethod
    def from_client_config(cls, *a, **k):
        return cls()

    def authorization_url(self, **k):
        return "https://accounts.google.com/fake-auth-url", "fake-state"

    def fetch_token(self, **k):
        pass


def _state(purpose: str, user_id: int | None = None) -> str:
    return f"{create_oauth_state_token(user_id=user_id, purpose=purpose)}.fake-verifier"


def test_login_callback_creates_new_user_and_redirects_with_tokens(client, monkeypatch, db_session):
    monkeypatch.setattr(google_oauth_router, "Flow", FakeFlow)
    fake_build = MagicMock()
    fake_build.return_value.userinfo.return_value.get.return_value.execute.return_value = {
        "email": "GOOGLE.USER@EXAMPLE.COM", "name": "Google User",
    }
    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)

    state = _state("login")
    r = client.get(f"/auth/google/login/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert "access_token=" in location and "refresh_token=" in location

    user = db_session.query(User).filter_by(email="google.user@example.com").first()
    assert user is not None
    assert user.name == "Google User"
    token_row = db_session.query(OAuthToken).filter_by(user_id=user.id, provider="google_login").first()
    assert token_row is not None


def test_login_callback_reuses_existing_user(client, monkeypatch, db_session, test_user):
    monkeypatch.setattr(google_oauth_router, "Flow", FakeFlow)
    fake_build = MagicMock()
    fake_build.return_value.userinfo.return_value.get.return_value.execute.return_value = {
        "email": "test@example.com", "name": "",
    }
    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)

    state = _state("login")
    r = client.get(f"/auth/google/login/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307)

    users = db_session.query(User).filter_by(email="test@example.com").all()
    assert len(users) == 1  # no duplicate user created


def test_login_callback_profile_fetch_failure_redirects_with_error(client, monkeypatch):
    monkeypatch.setattr(google_oauth_router, "Flow", FakeFlow)
    monkeypatch.setattr("googleapiclient.discovery.build", MagicMock(side_effect=RuntimeError("boom")))

    state = _state("login")
    r = client.get(f"/auth/google/login/callback?code=abc&state={state}", follow_redirects=False)
    assert "error=profile_failed" in r.headers["location"]


def test_login_callback_no_email_redirects_with_error(client, monkeypatch):
    monkeypatch.setattr(google_oauth_router, "Flow", FakeFlow)
    fake_build = MagicMock()
    fake_build.return_value.userinfo.return_value.get.return_value.execute.return_value = {"email": "", "name": ""}
    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)

    state = _state("login")
    r = client.get(f"/auth/google/login/callback?code=abc&state={state}", follow_redirects=False)
    assert "error=no_email" in r.headers["location"]


def test_login_callback_wrong_purpose_rejected(client):
    state = _state("connect_gmail")
    r = client.get(f"/auth/google/login/callback?code=abc&state={state}", follow_redirects=False)
    assert "error=token_failed" in r.headers["location"]


def test_login_callback_error_param_redirects(client):
    r = client.get("/auth/google/login/callback?error=access_denied", follow_redirects=False)
    assert "error=access_denied" in r.headers["location"]


def test_login_callback_fetch_token_failure_redirects(client, monkeypatch):
    class FailingFlow(FakeFlow):
        def fetch_token(self, **k):
            raise RuntimeError("token exchange failed")

    monkeypatch.setattr(google_oauth_router, "Flow", FailingFlow)
    state = _state("login")
    r = client.get(f"/auth/google/login/callback?code=abc&state={state}", follow_redirects=False)
    assert "error=token_failed" in r.headers["location"]


def test_connect_callback_stores_scan_token(client, monkeypatch, auth_headers, db_session, test_user):
    monkeypatch.setattr(google_oauth_router, "Flow", FakeFlow)
    fake_build = MagicMock()
    fake_build.return_value.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": "scan@example.com",
    }
    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)

    state = _state("connect_gmail", user_id=test_user.id)
    r = client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307)

    token_row = db_session.query(OAuthToken).filter_by(user_id=test_user.id, provider="google_scan").first()
    assert token_row is not None
    assert token_row.email == "scan@example.com"

    status_resp = client.get("/api/gmail/status", headers=auth_headers)
    assert status_resp.json()["scan"] == "scan@example.com"


def test_connect_callback_updates_existing_scan_token(client, monkeypatch, db_session, test_user):
    db_session.add(OAuthToken(user_id=test_user.id, provider="google_scan", token_json="{}", email="old@example.com"))
    db_session.commit()

    monkeypatch.setattr(google_oauth_router, "Flow", FakeFlow)
    fake_build = MagicMock()
    fake_build.return_value.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": "new@example.com",
    }
    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)

    state = _state("connect_gmail", user_id=test_user.id)
    client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)

    rows = db_session.query(OAuthToken).filter_by(user_id=test_user.id, provider="google_scan").all()
    assert len(rows) == 1
    assert rows[0].email == "new@example.com"


def test_connect_callback_wrong_purpose_rejected(client, test_user):
    state = _state("login", user_id=test_user.id)
    r = client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert "error=oauth_state_mismatch" in r.headers["location"]


def test_connect_callback_error_param_redirects_home(client):
    r = client.get("/auth/google/callback?error=access_denied", follow_redirects=False)
    assert r.headers["location"] == "http://localhost:8080/"


def test_google_connect_start_missing_credentials_500(client, auth_headers, monkeypatch):
    monkeypatch.setattr(google_oauth_router.settings, "GOOGLE_CLIENT_ID", "")
    r = client.get("/auth/google", headers=auth_headers)
    assert r.status_code == 500
