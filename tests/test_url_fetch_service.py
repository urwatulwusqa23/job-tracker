from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services import url_fetch_service as svc


def _fake_getaddrinfo_public(*a, **k):
    return [(None, None, None, None, ("93.184.216.34", 0))]  # example.com's public IP


def _fake_getaddrinfo_private(*a, **k):
    return [(None, None, None, None, ("10.0.0.5", 0))]


def _fake_getaddrinfo_loopback(*a, **k):
    return [(None, None, None, None, ("127.0.0.1", 0))]


def _fake_getaddrinfo_metadata(*a, **k):
    return [(None, None, None, None, ("169.254.169.254", 0))]  # cloud metadata endpoint


def test_validate_url_rejects_non_http_scheme():
    with pytest.raises(HTTPException) as exc_info:
        svc._validate_url("ftp://example.com/file")
    assert exc_info.value.status_code == 400


def test_validate_url_rejects_missing_hostname():
    with pytest.raises(HTTPException):
        svc._validate_url("http://")


def test_validate_url_allows_public_host(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_public)
    svc._validate_url("https://example.com/jobs/1")  # should not raise


def test_validate_url_blocks_private_ip(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_private)
    with pytest.raises(HTTPException) as exc_info:
        svc._validate_url("http://internal.example.com/")
    assert exc_info.value.status_code == 400


def test_validate_url_blocks_loopback(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_loopback)
    with pytest.raises(HTTPException):
        svc._validate_url("http://localhost:8080/admin")


def test_validate_url_blocks_cloud_metadata_endpoint(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_metadata)
    with pytest.raises(HTTPException):
        svc._validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_blocks_unresolvable_host(monkeypatch):
    import socket as real_socket

    def _raise(*a, **k):
        raise real_socket.gaierror("no such host")

    monkeypatch.setattr(svc.socket, "getaddrinfo", _raise)
    with pytest.raises(HTTPException):
        svc._validate_url("http://does-not-resolve.invalid/")


def test_fetch_job_posting_text_strips_scripts_and_styles(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_public)

    html = """
    <html><head><style>body{color:red}</style></head>
    <body>
      <script>alert('x')</script>
      <h1>Backend Engineer</h1>
      <p>Join Acme Corp as a Backend Engineer.</p>
    </body></html>
    """
    fake_resp = MagicMock()
    fake_resp.is_redirect = False
    fake_resp.is_permanent_redirect = False
    fake_resp.status_code = 200
    fake_resp.encoding = "utf-8"
    fake_resp.iter_content.return_value = [html.encode()]
    monkeypatch.setattr(svc.requests, "get", lambda *a, **k: fake_resp)

    text = svc.fetch_job_posting_text("https://example.com/jobs/1")
    assert "Backend Engineer" in text
    assert "Acme Corp" in text
    assert "alert" not in text
    assert "color:red" not in text


def test_fetch_raw_html_follows_validated_redirect(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_public)

    redirect_resp = MagicMock()
    redirect_resp.is_redirect = True
    redirect_resp.is_permanent_redirect = False
    redirect_resp.headers = {"Location": "https://example.com/final"}

    final_resp = MagicMock()
    final_resp.is_redirect = False
    final_resp.is_permanent_redirect = False
    final_resp.status_code = 200
    final_resp.encoding = "utf-8"
    final_resp.iter_content.return_value = [b"<html><body>Final page</body></html>"]

    responses = [redirect_resp, final_resp]
    monkeypatch.setattr(svc.requests, "get", lambda *a, **k: responses.pop(0))

    html = svc._fetch_raw_html("https://example.com/start")
    assert "Final page" in html


def test_fetch_raw_html_gives_up_after_max_redirects(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_public)

    redirect_resp = MagicMock()
    redirect_resp.is_redirect = True
    redirect_resp.is_permanent_redirect = False
    redirect_resp.headers = {"Location": "https://example.com/loop"}
    monkeypatch.setattr(svc.requests, "get", lambda *a, **k: redirect_resp)

    with pytest.raises(HTTPException) as exc_info:
        svc._fetch_raw_html("https://example.com/loop")
    assert exc_info.value.status_code == 400


def test_fetch_raw_html_raises_on_non_200(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_public)

    resp = MagicMock()
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.status_code = 404
    monkeypatch.setattr(svc.requests, "get", lambda *a, **k: resp)

    with pytest.raises(HTTPException) as exc_info:
        svc._fetch_raw_html("https://example.com/missing")
    assert exc_info.value.status_code == 400


def test_fetch_raw_html_handles_connection_error(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _fake_getaddrinfo_public)

    def _raise(*a, **k):
        raise svc.requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(svc.requests, "get", _raise)
    with pytest.raises(HTTPException):
        svc._fetch_raw_html("https://example.com/down")
