import io

MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 44>>stream\n"
    b"BT /F1 12 Tf 10 100 Td (Hello CV Test) Tj ET\n"
    b"endstream\nendobj\n"
    b"xref\n0 6\ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n0\n%%EOF"
)


def _upload(client, headers, filename="resume.pdf"):
    return client.post(
        "/api/cv", headers=headers,
        files={"file": (filename, io.BytesIO(MINIMAL_PDF), "application/pdf")},
    )


def test_upload_cv_extracts_text(client, auth_headers):
    r = _upload(client, auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "Hello CV Test" in body["preview"]


def test_upload_rejects_non_pdf(client, auth_headers):
    r = client.post(
        "/api/cv", headers=auth_headers,
        files={"file": ("resume.txt", io.BytesIO(b"plain text"), "text/plain")},
    )
    assert r.status_code == 400


def test_list_cvs(client, auth_headers):
    _upload(client, auth_headers)
    r = client.get("/api/cv", headers=auth_headers)
    assert r.status_code == 200
    cvs = r.json()
    assert len(cvs) == 1
    assert cvs[0]["filename"] == "resume.pdf"
    assert cvs[0]["is_active"] is True


def test_second_upload_deactivates_first(client, auth_headers):
    _upload(client, auth_headers, "a.pdf")
    _upload(client, auth_headers, "b.pdf")
    cvs = client.get("/api/cv", headers=auth_headers).json()
    active = [c for c in cvs if c["is_active"]]
    assert len(active) == 1
    assert active[0]["filename"] == "b.pdf"


def test_activate_cv_switches_active_flag(client, auth_headers):
    r1 = _upload(client, auth_headers, "a.pdf")
    _upload(client, auth_headers, "b.pdf")
    a_id = r1.json()["id"]

    r = client.post(f"/api/cv/{a_id}/activate", headers=auth_headers)
    assert r.status_code == 200

    cvs = client.get("/api/cv", headers=auth_headers).json()
    active = [c for c in cvs if c["is_active"]]
    assert len(active) == 1
    assert active[0]["filename"] == "a.pdf"


def test_activate_nonexistent_cv_404(client, auth_headers):
    r = client.post("/api/cv/999/activate", headers=auth_headers)
    assert r.status_code == 404


def test_active_text_returns_extracted_text(client, auth_headers):
    _upload(client, auth_headers)
    r = client.get("/api/cv/active_text", headers=auth_headers)
    assert r.status_code == 200
    assert "Hello CV Test" in r.json()["text"]


def test_active_text_404_when_no_cv(client, auth_headers):
    r = client.get("/api/cv/active_text", headers=auth_headers)
    assert r.status_code == 404


def test_download_cv_via_header_auth(client, auth_headers):
    up = _upload(client, auth_headers)
    cv_id = up.json()["id"]
    r = client.get(f"/api/cv/{cv_id}/download", headers=auth_headers)
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert "resume.pdf" in r.headers["content-disposition"]


def test_download_cv_via_query_token(client, auth_headers):
    up = _upload(client, auth_headers)
    cv_id = up.json()["id"]
    token = auth_headers["Authorization"].split(" ")[1]
    r = client.get(f"/api/cv/{cv_id}/download?token={token}")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_download_cv_without_any_auth_401(client, auth_headers):
    up = _upload(client, auth_headers)
    cv_id = up.json()["id"]
    r = client.get(f"/api/cv/{cv_id}/download")
    assert r.status_code == 401


def test_download_other_users_cv_404(client, auth_headers, db_session):
    from app.core.security import hash_password
    from app.models.user import User

    up = _upload(client, auth_headers)
    cv_id = up.json()["id"]

    other = User(email="other@example.com", password_hash=hash_password("password123"))
    db_session.add(other)
    db_session.commit()
    login = client.post("/api/auth/login", json={"email": "other@example.com", "password": "password123"})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = client.get(f"/api/cv/{cv_id}/download", headers=other_headers)
    assert r.status_code == 404
