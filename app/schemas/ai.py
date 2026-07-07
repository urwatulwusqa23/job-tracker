from pydantic import BaseModel


class ExtractJobRequest(BaseModel):
    text: str | None = None
    url: str | None = None


class ExtractJobResponse(BaseModel):
    company: str | None = None
    role: str | None = None
    location: str | None = None
    salary: str | None = None
    job_url: str | None = None
    job_description: str | None = None
    source: str | None = None
    notes: str | None = None


class SkillsGapResponse(BaseModel):
    profile_summary: str
    current_strengths: list[str]
    skill_gaps: list[dict]
    courses: list[dict]
    projects_to_build: list[dict]
    certifications: list[dict]
    market_insights: list[str]
    job_titles_to_target: list[str]


class JobRecommendation(BaseModel):
    title: str | None
    company: str | None
    location: str | None
    salary: str | None
    url: str | None
    tags: list[str]
    posted: str | None
    logo: str | None


class JobRecommendationsResponse(BaseModel):
    keywords: list[str]
    jobs: list[JobRecommendation]
