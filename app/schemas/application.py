from datetime import datetime

from pydantic import BaseModel

# NOTE: wire field names intentionally match the original Flask API / existing frontend JS
# (company, salary, applied_date) even though the DB columns are named per the new spec
# (company_name, salary_expected, date_applied). Routers translate between the two.


class ApplicationCreate(BaseModel):
    company: str
    role: str
    status: str = "Applied"
    applied_date: str | None = None
    salary: str | None = None
    job_url: str | None = None
    notes: str | None = None
    job_description: str | None = None
    source: str = "Manual"
    location: str | None = None
    cv_id: int | None = None


class ApplicationUpdate(BaseModel):
    company: str | None = None
    role: str | None = None
    status: str | None = None
    applied_date: str | None = None
    salary: str | None = None
    job_url: str | None = None
    notes: str | None = None
    job_description: str | None = None
    location: str | None = None
    cv_id: int | None = None


class ApplicationOut(BaseModel):
    id: int
    company: str
    role: str
    status: str
    applied_date: str | None
    salary: str | None
    job_url: str | None
    notes: str | None
    job_description: str | None
    source: str
    location: str | None
    cv_id: int | None
    cv_filename: str | None = None
    created_at: datetime
    updated_at: datetime
