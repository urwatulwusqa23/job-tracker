def test_index_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Hired" in r.text


def test_login_page_offers_registration_when_no_users(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Create one" in r.text


def test_login_page_hides_registration_once_a_user_exists(client, test_user):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Create one" not in r.text


def test_register_page_available_when_no_users(client):
    r = client.get("/register")
    assert r.status_code == 200
    assert "Create Account" in r.text


def test_register_page_falls_back_to_login_when_user_exists(client, test_user):
    r = client.get("/register")
    assert r.status_code == 200
    assert "Welcome back" in r.text


def test_health_endpoint_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] is True


def test_privacy_page_renders(client):
    r = client.get("/privacy")
    assert r.status_code == 200
    assert "Privacy Policy" in r.text
    assert "Limited Use" in r.text  # required Google API Services disclosure


def test_privacy_page_shows_support_email(client, monkeypatch):
    from app.routers import pages

    monkeypatch.setattr(pages.settings, "SUPPORT_EMAIL", "support@example.com")
    r = client.get("/privacy")
    assert "support@example.com" in r.text


def test_terms_page_renders(client):
    r = client.get("/terms")
    assert r.status_code == 200
    assert "Terms of Service" in r.text


def test_index_page_includes_site_verification_meta_when_configured(client, monkeypatch):
    from app.routers import pages

    monkeypatch.setattr(pages.settings, "GOOGLE_SITE_VERIFICATION", "abc123token")
    r = client.get("/")
    assert 'name="google-site-verification"' in r.text
    assert "abc123token" in r.text


def test_index_page_omits_site_verification_meta_by_default(client):
    r = client.get("/")
    assert 'name="google-site-verification"' not in r.text
