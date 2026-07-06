import base64

from app.services import gmail_service


def test_extract_body_from_direct_body():
    data = base64.urlsafe_b64encode(b"hello world").decode()
    payload = {"body": {"data": data}}
    assert gmail_service.extract_body(payload) == "hello world"


def test_extract_body_from_plain_text_part():
    data = base64.urlsafe_b64encode(b"part body").decode()
    payload = {"parts": [{"mimeType": "text/plain", "body": {"data": data}}]}
    assert gmail_service.extract_body(payload) == "part body"


def test_extract_body_returns_empty_when_nothing_found():
    assert gmail_service.extract_body({}) == ""


def test_pkce_pair_produces_distinct_verifier_and_challenge():
    verifier, challenge = gmail_service.pkce_pair()
    assert verifier != challenge
    assert len(verifier) > 20
    assert len(challenge) > 20


def test_oauth_client_config_shape():
    cfg = gmail_service.oauth_client_config("http://localhost/cb")
    assert cfg["web"]["redirect_uris"] == ["http://localhost/cb"]


def test_normalize_company_strips_legal_suffixes():
    assert gmail_service._normalize_company("Acme Inc.") == "acme"
    assert gmail_service._normalize_company("Acme Ltd") == "acme"
    assert gmail_service._normalize_company("Widgets Group") == "widgets"
