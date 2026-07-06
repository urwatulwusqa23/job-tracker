import io
import json
from unittest.mock import MagicMock

from app.routers import ai as ai_router

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 44>>stream\nBT /F1 12 Tf 10 100 Td (Some CV Text) Tj ET\nendstream\nendobj\n"
    b"xref\n0 6\ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n0\n%%EOF"
)


def _mock_chat_response(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content=content))]
    return client


def test_extract_job_requires_auth(client):
    r = client.post("/api/extract_job", json={"text": "some job posting"})
    assert r.status_code == 401


def test_extract_job_success(client, auth_headers, monkeypatch):
    fake_client = _mock_chat_response(json.dumps({"company": "Acme", "role": "Engineer"}))
    monkeypatch.setattr(ai_router, "require_ai", lambda: fake_client)

    r = client.post("/api/extract_job", headers=auth_headers, json={"text": "We are hiring an engineer at Acme"})
    assert r.status_code == 200
    assert r.json()["company"] == "Acme"


def test_extract_job_empty_text_400(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ai_router, "require_ai", lambda: MagicMock())
    r = client.post("/api/extract_job", headers=auth_headers, json={"text": ""})
    assert r.status_code == 400


def test_extract_job_ai_parse_failure_500(client, auth_headers, monkeypatch):
    fake_client = _mock_chat_response("not valid json")
    monkeypatch.setattr(ai_router, "require_ai", lambda: fake_client)
    r = client.post("/api/extract_job", headers=auth_headers, json={"text": "some text"})
    assert r.status_code == 500


PREP_JSON = json.dumps({
    "technical_questions": [{"question": "What is a hash map?", "ideal_answer": "...", "tip": "..."}],
    "behavioral_questions": [{"question": "Tell me about a conflict", "ideal_answer": "...", "tip": "..."}],
    "company_research": ["Point 1"],
    "strengths_to_highlight": ["Python"],
    "gaps_to_address": [{"gap": "Kubernetes", "how_to_handle": "Study it"}],
    "questions_to_ask": ["What's the team size?"],
    "salary_negotiation": "Negotiate confidently",
    "dress_code_tip": "Business casual",
    "overall_tip": "Be yourself",
})


def test_interview_prep_get_404_when_not_generated(client, auth_headers):
    created = client.post("/api/applications", headers=auth_headers, json={"company": "Acme", "role": "Eng"})
    app_id = created.json()["id"]
    r = client.get(f"/api/interview_prep/{app_id}", headers=auth_headers)
    assert r.status_code == 404


def test_interview_prep_generate_and_get(client, auth_headers, monkeypatch):
    fake_client = _mock_chat_response(PREP_JSON)
    monkeypatch.setattr(ai_router, "require_ai", lambda: fake_client)

    created = client.post("/api/applications", headers=auth_headers, json={
        "company": "Acme", "role": "Engineer", "job_description": "Build things",
    })
    app_id = created.json()["id"]

    r = client.post(f"/api/interview_prep/{app_id}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["technical_questions"]) == 1
    assert len(body["behavioral_questions"]) == 1
    assert body["salary_negotiation"] == "Negotiate confidently"
    assert body["dress_code_tip"] == "Business casual"

    r2 = client.get(f"/api/interview_prep/{app_id}", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["overall_tip"] == "Be yourself"


def test_interview_prep_for_missing_application_404(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ai_router, "require_ai", lambda: _mock_chat_response(PREP_JSON))
    r = client.post("/api/interview_prep/999", headers=auth_headers)
    assert r.status_code == 404


SKILLS_GAP_JSON = json.dumps({
    "profile_summary": "Solid backend engineer",
    "current_strengths": ["Python", "SQL"],
    "skill_gaps": [{"skill": "Kubernetes", "why_important": "scale", "demand": "High"}],
    "courses": [{"title": "K8s 101", "platform": "Udemy", "url": None, "duration": "5h",
                 "why": "learn k8s", "priority": "High", "free": True}],
    "projects_to_build": [{"title": "Deploy a cluster", "description": "...", "technologies": ["k8s"],
                            "resume_impact": "...", "difficulty": "Intermediate", "time_estimate": "1 weekend"}],
    "certifications": [{"name": "CKA", "provider": "CNCF", "cost": "$300", "why": "credibility"}],
    "market_insights": ["AI adoption rising"],
    "job_titles_to_target": ["Platform Engineer"],
})


def test_skills_gap_requires_active_cv(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ai_router, "require_ai", lambda: _mock_chat_response(SKILLS_GAP_JSON))
    r = client.post("/api/skills_gap", headers=auth_headers)
    assert r.status_code == 400


def test_skills_gap_success(client, auth_headers, monkeypatch):
    client.post("/api/cv", headers=auth_headers, files={"file": ("cv.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")})
    monkeypatch.setattr(ai_router, "require_ai", lambda: _mock_chat_response(SKILLS_GAP_JSON))

    r = client.post("/api/skills_gap", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["profile_summary"] == "Solid backend engineer"


def test_job_recommendations_requires_active_cv(client, auth_headers):
    r = client.post("/api/job_recommendations", headers=auth_headers)
    assert r.status_code == 400


def test_job_recommendations_success(client, auth_headers, monkeypatch):
    client.post("/api/cv", headers=auth_headers, files={"file": ("cv.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")})
    monkeypatch.setattr(ai_router, "require_ai", lambda: _mock_chat_response(json.dumps(["backend engineer"])))

    fake_jobs_resp = MagicMock()
    fake_jobs_resp.ok = True
    fake_jobs_resp.json.return_value = {"jobs": [{
        "title": "Backend Engineer", "company_name": "Acme", "candidate_required_location": "Remote",
        "salary": "", "url": "https://x.co/1", "tags": [], "publication_date": "2026-01-01", "company_logo": "",
    }]}
    monkeypatch.setattr("app.services.job_board_service.requests.get", lambda *a, **k: fake_jobs_resp)

    r = client.post("/api/job_recommendations", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["keywords"] == ["backend engineer"]
    assert len(body["jobs"]) == 1


def test_job_recommendations_falls_back_on_bad_keywords(client, auth_headers, monkeypatch):
    client.post("/api/cv", headers=auth_headers, files={"file": ("cv.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")})
    monkeypatch.setattr(ai_router, "require_ai", lambda: _mock_chat_response("not json"))
    monkeypatch.setattr("app.services.job_board_service.requests.get", lambda *a, **k: MagicMock(ok=False))

    r = client.post("/api/job_recommendations", headers=auth_headers)
    assert r.status_code == 200
    assert "software developer" in r.json()["keywords"]
