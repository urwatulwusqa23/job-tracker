from app.services import gmail_service


def test_pkce_pair_produces_distinct_verifier_and_challenge():
    verifier, challenge = gmail_service.pkce_pair()
    assert verifier != challenge
    assert len(verifier) > 20
    assert len(challenge) > 20


def test_oauth_client_config_shape():
    cfg = gmail_service.oauth_client_config("http://localhost/cb")
    assert cfg["web"]["redirect_uris"] == ["http://localhost/cb"]
