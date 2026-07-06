import base64
from unittest.mock import MagicMock

from app.routers import gmail as gmail_router


def test_gmail_scan_requires_auth(client):
    r = client.post("/api/gmail_scan")
    assert r.status_code == 401


def test_gmail_scan_not_connected_401(client, auth_headers, monkeypatch):
    monkeypatch.setattr(gmail_router, "get_gmail_service", lambda db, uid: None)
    r = client.post("/api/gmail_scan", headers=auth_headers)
    assert r.status_code == 401


def _fake_gmail_service(messages):
    svc = MagicMock()
    svc.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": m["id"]} for m in messages]
    }

    def get_side_effect(userId, id, format):
        msg = next(m for m in messages if m["id"] == id)
        return MagicMock(execute=MagicMock(return_value=msg["full"]))

    svc.users.return_value.messages.return_value.get.side_effect = get_side_effect
    return svc


def _encoded_body(text: str) -> dict:
    return {"data": base64.urlsafe_b64encode(text.encode()).decode()}


def test_gmail_scan_returns_matching_emails(client, auth_headers, monkeypatch):
    messages = [{
        "id": "1",
        "full": {
            "payload": {
                "headers": [{"name": "Subject", "value": "Your application"}, {"name": "From", "value": "hr@acme.com"}, {"name": "Date", "value": "Mon"}],
                "body": _encoded_body("Thanks for applying"),
            }
        },
    }]
    monkeypatch.setattr(gmail_router, "get_gmail_service", lambda db, uid: _fake_gmail_service(messages))

    r = client.post("/api/gmail_scan", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["emails"][0]["subject"] == "Your application"


def test_gmail_scan_handles_exceptions_as_500(client, auth_headers, monkeypatch):
    svc = MagicMock()
    svc.users.return_value.messages.return_value.list.side_effect = RuntimeError("boom")
    monkeypatch.setattr(gmail_router, "get_gmail_service", lambda db, uid: svc)
    r = client.post("/api/gmail_scan", headers=auth_headers)
    assert r.status_code == 500


def test_gmail_sync_not_connected_401(client, auth_headers, monkeypatch):
    monkeypatch.setattr(gmail_router, "get_gmail_service", lambda db, uid: None)
    r = client.post("/api/gmail/sync", headers=auth_headers)
    assert r.status_code == 401


def test_gmail_sync_updates_last_sync_and_returns_results(client, auth_headers, monkeypatch):
    messages = [{
        "id": "1",
        "full": {
            "payload": {
                "headers": [{"name": "Subject", "value": "Application received"}],
                "body": _encoded_body("we regret to inform you, unfortunately not selected"),
            }
        },
    }]
    monkeypatch.setattr(gmail_router, "get_gmail_service", lambda db, uid: _fake_gmail_service(messages))
    monkeypatch.setattr(gmail_router, "get_ai_client", lambda: None)

    client.post("/api/applications", headers=auth_headers, json={"company": "Application", "role": "Eng"})

    r = client.post("/api/gmail/sync", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "auto_rejected" in body and "auto_added" in body and "skipped" in body

    stats = client.get("/api/stats", headers=auth_headers).json()
    assert stats["last_gmail_sync"] is not None
