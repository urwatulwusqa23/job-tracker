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
