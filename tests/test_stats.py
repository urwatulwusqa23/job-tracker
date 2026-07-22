def test_stats_empty_state(client, auth_headers):
    r = client.get("/api/stats", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["active"] == 0
    assert body["followup_needed"] == []
    assert body["recent_activity"] == []


def test_stats_counts_by_status(client, auth_headers):
    for company, status in [("A", "Applied"), ("B", "Applied"), ("C", "Interview"), ("D", "Offer"), ("E", "Rejected")]:
        created = client.post("/api/applications", headers=auth_headers, json={"company": company, "role": "Eng"})
        app_id = created.json()["id"]
        if status != "Applied":
            client.put(f"/api/applications/{app_id}", headers=auth_headers, json={"status": status})

    r = client.get("/api/stats", headers=auth_headers)
    body = r.json()
    assert body["applied"] == 2
    assert body["interview"] == 1
    assert body["offer"] == 1
    assert body["rejected"] == 1
    assert body["total"] == 5
    assert body["active"] == 3  # applied(2) + screening(0) + interview(1)


def test_stats_recent_activity_reflects_add_and_status_change(client, auth_headers):
    created = client.post("/api/applications", headers=auth_headers, json={"company": "Acme", "role": "Eng"})
    app_id = created.json()["id"]
    client.put(f"/api/applications/{app_id}", headers=auth_headers, json={"status": "Interview"})

    r = client.get("/api/stats", headers=auth_headers)
    activity = r.json()["recent_activity"]
    actions = [a["action"] for a in activity]
    assert any("Added" in a for a in actions)
    assert any("Status" in a for a in actions)


def test_stats_requires_auth(client):
    r = client.get("/api/stats")
    assert r.status_code == 401


def test_stats_flags_stale_applications_as_followup_needed(client, auth_headers, db_session):
    from datetime import datetime, timedelta, timezone

    from app.models.application import Application

    created = client.post("/api/applications", headers=auth_headers, json={"company": "StaleCo", "role": "Eng"})
    app_id = created.json()["id"]

    app = db_session.get(Application, app_id)
    app.updated_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.commit()

    r = client.get("/api/stats", headers=auth_headers)
    followup = r.json()["followup_needed"]
    assert len(followup) == 1
    assert followup[0]["company"] == "StaleCo"
    assert followup[0]["days_stale"] >= 10
