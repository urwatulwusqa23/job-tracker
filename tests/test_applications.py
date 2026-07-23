def test_list_applications_requires_auth(client):
    r = client.get("/api/applications")
    assert r.status_code == 401


def test_create_and_list_application(client, auth_headers):
    r = client.post("/api/applications", headers=auth_headers, json={
        "company": "Acme Corp", "role": "Backend Engineer",
    })
    assert r.status_code == 201
    assert r.json()["success"] is True

    r2 = client.get("/api/applications", headers=auth_headers)
    assert r2.status_code == 200
    apps = r2.json()
    assert len(apps) == 1
    assert apps[0]["company"] == "Acme Corp"
    assert apps[0]["role"] == "Backend Engineer"
    assert apps[0]["status"] == "Applied"
    assert apps[0]["source"] == "Manual"


def test_create_application_with_full_wire_fields(client, auth_headers):
    r = client.post("/api/applications", headers=auth_headers, json={
        "company": "Globex", "role": "Data Engineer", "status": "Screening",
        "applied_date": "2026-01-15", "salary": "120k", "job_url": "https://x.co/1",
        "notes": "referred by a friend", "job_description": "ETL pipelines", "source": "Referral",
        "location": "Remote",
    })
    assert r.status_code == 201
    app_id = r.json()["id"]

    apps = client.get("/api/applications", headers=auth_headers).json()
    app = next(a for a in apps if a["id"] == app_id)
    assert app["salary"] == "120k"
    assert app["applied_date"] == "2026-01-15"
    assert app["source"] == "Referral"
    assert app["location"] == "Remote"


def test_update_application(client, auth_headers):
    created = client.post("/api/applications", headers=auth_headers, json={"company": "Acme", "role": "Eng"})
    app_id = created.json()["id"]

    r = client.put(f"/api/applications/{app_id}", headers=auth_headers, json={"status": "Interview", "salary": "150k"})
    assert r.status_code == 200

    apps = client.get("/api/applications", headers=auth_headers).json()
    app = next(a for a in apps if a["id"] == app_id)
    assert app["status"] == "Interview"
    assert app["salary"] == "150k"


def test_update_nonexistent_application_404(client, auth_headers):
    r = client.put("/api/applications/999", headers=auth_headers, json={"status": "Offer"})
    assert r.status_code == 404


def test_delete_application(client, auth_headers):
    created = client.post("/api/applications", headers=auth_headers, json={"company": "Acme", "role": "Eng"})
    app_id = created.json()["id"]

    r = client.delete(f"/api/applications/{app_id}", headers=auth_headers)
    assert r.status_code == 200

    apps = client.get("/api/applications", headers=auth_headers).json()
    assert apps == []


def test_delete_nonexistent_application_404(client, auth_headers):
    r = client.delete("/api/applications/999", headers=auth_headers)
    assert r.status_code == 404


def test_applications_are_isolated_per_user(client, db_session):
    from app.core.security import hash_password
    from app.models.user import User

    u1 = User(email="u1@example.com", password_hash=hash_password("password123"))
    u2 = User(email="u2@example.com", password_hash=hash_password("password123"))
    db_session.add_all([u1, u2])
    db_session.commit()

    login1 = client.post("/api/auth/login", json={"email": "u1@example.com", "password": "password123"})
    login2 = client.post("/api/auth/login", json={"email": "u2@example.com", "password": "password123"})
    h1 = {"Authorization": f"Bearer {login1.json()['access_token']}"}
    h2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    client.post("/api/applications", headers=h1, json={"company": "OnlyU1", "role": "Eng"})

    apps_u1 = client.get("/api/applications", headers=h1).json()
    apps_u2 = client.get("/api/applications", headers=h2).json()
    assert len(apps_u1) == 1
    assert apps_u2 == []


def test_new_application_auto_links_active_cv(client, auth_headers):
    import io

    pdf_bytes = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )
    client.post("/api/cv", headers=auth_headers, files={"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")})

    created = client.post("/api/applications", headers=auth_headers, json={"company": "Acme", "role": "Eng"})
    app_id = created.json()["id"]
    apps = client.get("/api/applications", headers=auth_headers).json()
    app = next(a for a in apps if a["id"] == app_id)
    assert app["cv_filename"] == "resume.pdf"


def test_create_application_empty_company_422(client, auth_headers):
    r = client.post("/api/applications", headers=auth_headers, json={"company": "   ", "role": "Engineer"})
    assert r.status_code == 422


def test_create_application_empty_role_422(client, auth_headers):
    r = client.post("/api/applications", headers=auth_headers, json={"company": "Acme", "role": ""})
    assert r.status_code == 422


def test_create_application_invalid_status_422(client, auth_headers):
    r = client.post("/api/applications", headers=auth_headers, json={"company": "Acme", "role": "Eng", "status": "Pending"})
    assert r.status_code == 422


def test_create_duplicate_application_409(client, auth_headers):
    payload = {"company": "Acme", "role": "Engineer"}
    r1 = client.post("/api/applications", headers=auth_headers, json=payload)
    assert r1.status_code == 201
    r2 = client.post("/api/applications", headers=auth_headers, json=payload)
    assert r2.status_code == 409


def test_create_duplicate_application_case_insensitive_409(client, auth_headers):
    client.post("/api/applications", headers=auth_headers, json={"company": "Acme Corp", "role": "Engineer"})
    r = client.post("/api/applications", headers=auth_headers, json={"company": "acme corp", "role": "ENGINEER"})
    assert r.status_code == 409
