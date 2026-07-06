from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services import ai_service


def test_get_ai_client_none_without_key(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "XAI_API_KEY", "")
    assert ai_service.get_ai_client() is None


def test_get_ai_client_returns_client_with_key(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "XAI_API_KEY", "fake-key")
    client = ai_service.get_ai_client()
    assert client is not None


def test_require_ai_raises_without_key(monkeypatch):
    monkeypatch.setattr(ai_service.settings, "XAI_API_KEY", "")
    with pytest.raises(HTTPException) as exc_info:
        ai_service.require_ai()
    assert exc_info.value.status_code == 400


def test_grok_calls_chat_completions():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="hello"))
    ]
    result = ai_service.grok(fake_client, "prompt text")
    assert result == "hello"
    fake_client.chat.completions.create.assert_called_once()


def test_ai_extract_job_parses_fenced_json():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content='```json\n{"company": "Acme", "role": "Engineer"}\n```'))
    ]
    result = ai_service.ai_extract_job(fake_client, "some job posting text")
    assert result == {"company": "Acme", "role": "Engineer"}


def test_ai_extract_job_returns_empty_dict_on_bad_json():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="not json at all"))
    ]
    assert ai_service.ai_extract_job(fake_client, "text") == {}


def test_parse_json_response_strips_fences():
    assert ai_service.parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai_service.parse_json_response('{"a": 1}') == {"a": 1}


def test_build_interview_prep_prompt_includes_role_and_company():
    prompt = ai_service.build_interview_prep_prompt(
        role="Backend Engineer", company="Acme", location="Remote",
        salary="100k", job_description="Build APIs", cv_text="Experienced dev",
    )
    assert "Backend Engineer" in prompt
    assert "Acme" in prompt
    assert "Build APIs" in prompt


def test_build_skills_gap_prompt_includes_cv_and_jobs():
    prompt = ai_service.build_skills_gap_prompt("My CV text", "- Engineer: some JD")
    assert "My CV text" in prompt
    assert "some JD" in prompt


def test_build_job_keywords_prompt_includes_cv():
    prompt = ai_service.build_job_keywords_prompt("My CV text")
    assert "My CV text" in prompt
