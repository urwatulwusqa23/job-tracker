from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

VALID_STATUSES = ["Applied", "Screening", "Interview", "Offer", "Rejected", "Withdrawn"]


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

    @field_validator("company", "role")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("cannot be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"must be one of {VALID_STATUSES}")
        return v


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

    @field_validator("company", "role")
    @classmethod
    def not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("cannot be empty")
        return v.strip() if v else v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"must be one of {VALID_STATUSES}")
        return v


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
