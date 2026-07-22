from pydantic import BaseModel


class FollowupItem(BaseModel):
    id: int
    company: str
    role: str
    applied_date: str | None
    days_stale: int


class ActivityItem(BaseModel):
    action: str
    note: str | None
    timestamp: str
    company: str | None
    role: str | None


class StatsOut(BaseModel):
    applied: int
    screening: int
    interview: int
    offer: int
    rejected: int
    withdrawn: int
    total: int
    active: int
    followup_needed: list[FollowupItem]
    recent_activity: list[ActivityItem]
