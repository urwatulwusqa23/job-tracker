from unittest.mock import MagicMock

from app.services import job_board_service


def _fake_response(jobs):
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = {"jobs": jobs}
    return resp


def test_fetch_remotive_jobs_maps_fields(monkeypatch):
    fake_jobs = [{
        "title": "Backend Engineer", "company_name": "Acme",
        "candidate_required_location": "Worldwide", "salary": "$100k",
        "url": "https://example.com/job/1", "tags": ["python", "fastapi", "sql", "aws", "docker", "k8s", "extra"],
        "publication_date": "2026-01-01T00:00:00", "company_logo": "https://example.com/logo.png",
    }]
    monkeypatch.setattr(job_board_service.requests, "get", lambda *a, **k: _fake_response(fake_jobs))

    jobs = job_board_service.fetch_remotive_jobs(["backend"])
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Backend Engineer"
    assert jobs[0]["company"] == "Acme"
    assert len(jobs[0]["tags"]) == 6
    assert jobs[0]["posted"] == "2026-01-01"


def test_fetch_remotive_jobs_dedupes_by_title_and_company(monkeypatch):
    fake_jobs = [
        {"title": "Engineer", "company_name": "Acme"},
        {"title": "Engineer", "company_name": "Acme"},
    ]
    monkeypatch.setattr(job_board_service.requests, "get", lambda *a, **k: _fake_response(fake_jobs))
    jobs = job_board_service.fetch_remotive_jobs(["engineer"])
    assert len(jobs) == 1


def test_fetch_remotive_jobs_handles_request_exception(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(job_board_service.requests, "get", _raise)
    jobs = job_board_service.fetch_remotive_jobs(["engineer"])
    assert jobs == []


def test_fetch_remotive_jobs_handles_non_ok_response(monkeypatch):
    resp = MagicMock()
    resp.ok = False
    monkeypatch.setattr(job_board_service.requests, "get", lambda *a, **k: resp)
    jobs = job_board_service.fetch_remotive_jobs(["engineer"])
    assert jobs == []
