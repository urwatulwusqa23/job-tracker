import json

from fastapi import HTTPException, status
from openai import OpenAI

from app.core.config import settings


def get_ai_client() -> OpenAI | None:
    if not settings.XAI_API_KEY:
        return None
    return OpenAI(api_key=settings.XAI_API_KEY, base_url=settings.AI_BASE_URL)


def require_ai() -> OpenAI:
    client = get_ai_client()
    if not client:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No XAI_API_KEY set in .env")
    return client


def grok(client: OpenAI, prompt: str, max_tokens: int = 1500) -> str:
    resp = client.chat.completions.create(
        model=settings.GROK_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content


def _strip_json_fences(raw: str) -> str:
    return raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()


EXTRACT_PROMPT = """Extract job application details from the text below.
Return ONLY valid JSON – no markdown, no explanation:
{{
  "company":         "company name or null",
  "role":            "job title or null",
  "location":        "city/remote or null",
  "salary":          "salary info or null",
  "job_url":         "URL if present or null",
  "job_description": "key requirements & responsibilities, max 250 words",
  "source":          "Email or WhatsApp or Other",
  "notes":           "any other important detail"
}}

TEXT:
{text}"""


def ai_extract_job(client: OpenAI, text: str) -> dict:
    try:
        raw = grok(client, EXTRACT_PROMPT.format(text=text[:3500]), max_tokens=900)
        return json.loads(_strip_json_fences(raw))
    except Exception:
        return {}


def build_interview_prep_prompt(role: str, company: str, location: str | None, salary: str | None,
                                  job_description: str | None, cv_text: str) -> str:
    return f"""You are a world-class interview coach. Prepare this candidate for their interview.

ROLE: {role} at {company}
LOCATION: {location or 'Not specified'}
SALARY: {salary or 'Not specified'}

JOB DESCRIPTION:
{(job_description or 'Not provided')[:2000]}

CANDIDATE CV:
{cv_text[:2500]}

Return ONLY valid JSON – no markdown fences, no preamble, start directly with {{:
{{
  "technical_questions":    [{{"question":"...","ideal_answer":"...","tip":"..."}}],
  "behavioral_questions":   [{{"question":"...","ideal_answer":"...","tip":"..."}}],
  "company_research":       ["point 1","point 2","point 3"],
  "strengths_to_highlight": ["..."],
  "gaps_to_address":        [{{"gap":"...","how_to_handle":"..."}}],
  "questions_to_ask":       ["..."],
  "salary_negotiation":     "advice string",
  "dress_code_tip":         "...",
  "overall_tip":            "..."
}}

Generate exactly 5 technical questions and 5 behavioral questions."""


def build_skills_gap_prompt(cv_text: str, jd_ctx: str) -> str:
    return f"""You are a top career coach with deep knowledge of the 2025 global job market.

CANDIDATE CV:
{cv_text[:3000]}

JOBS THEY HAVE APPLIED FOR:
{jd_ctx or '(none recorded)'}

Analyse their profile against the CURRENT 2025 market. Return ONLY valid JSON, no markdown fences:
{{
  "profile_summary":        "2-3 sentence honest summary",
  "current_strengths":      ["strength 1","strength 2","strength 3"],
  "skill_gaps": [
    {{"skill":"...","why_important":"...","demand":"High/Medium"}}
  ],
  "courses": [
    {{
      "title":    "exact course name",
      "platform": "Coursera/Udemy/YouTube/LinkedIn Learning/freeCodeCamp/etc",
      "url":      "real URL or null",
      "duration": "e.g. 10 hours",
      "why":      "why this helps",
      "priority": "High/Medium/Low",
      "free":     true
    }}
  ],
  "projects_to_build": [
    {{
      "title":         "project name",
      "description":   "what to build",
      "technologies":  ["tech1","tech2"],
      "resume_impact": "how to write it on CV",
      "difficulty":    "Beginner/Intermediate/Advanced",
      "time_estimate": "e.g. 2 weekends"
    }}
  ],
  "certifications": [
    {{"name":"...","provider":"...","cost":"...","why":"..."}}
  ],
  "market_insights":      ["2025 trend 1","trend 2","trend 3"],
  "job_titles_to_target": ["title 1","title 2","title 3"]
}}

Be specific to 2025. Give exactly 5 courses, 3 projects, 2 certifications, 4 skill gaps."""


def build_job_keywords_prompt(cv_text: str) -> str:
    return f"""Based on this CV give 3 job-search keywords (job titles) that best match the
profile for the 2025 market. Return ONLY a JSON array: ["keyword1","keyword2","keyword3"]

CV:
{cv_text[:2000]}"""


def parse_json_response(raw: str) -> dict | list:
    return json.loads(_strip_json_fences(raw))
