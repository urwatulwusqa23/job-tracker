from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import ActivityLog
from app.models.application import Application
from app.models.user import User
from app.schemas.stats import ActivityItem, FollowupItem, StatsOut

router = APIRouter(prefix="/api/stats", tags=["stats"])

STATUSES = ["Applied", "Screening", "Interview", "Offer", "Rejected", "Withdrawn"]


@router.get("", response_model=StatsOut)
def get_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = {
        s.lower(): db.query(Application).filter_by(user_id=user.id, status=s).count()
        for s in STATUSES
    }
    total = db.query(Application).filter_by(user_id=user.id).count()
    active = counts["applied"] + counts["screening"] + counts["interview"]

    now = datetime.now(timezone.utc)
    stale_candidates = (
        db.query(Application)
        .filter(Application.user_id == user.id, Application.status.in_(["Applied", "Screening"]))
        .all()
    )
    followup = []
    for a in stale_candidates:
        ref = a.updated_at or a.created_at
        ref_naive = ref if ref.tzinfo else ref.replace(tzinfo=timezone.utc)
        days_stale = (now - ref_naive).days
        if days_stale >= 7:
            followup.append(FollowupItem(
                id=a.id, company=a.company_name, role=a.role,
                applied_date=a.date_applied, days_stale=days_stale,
            ))
    followup.sort(key=lambda f: f.days_stale, reverse=True)
    followup = followup[:8]

    recent_rows = (
        db.query(ActivityLog, Application)
        .outerjoin(Application, ActivityLog.application_id == Application.id)
        .filter(Application.user_id == user.id)
        .order_by(ActivityLog.timestamp.desc())
        .limit(12)
        .all()
    )
    recent_activity = [
        ActivityItem(
            action=log.action, note=log.note,
            timestamp=log.timestamp.isoformat(), company=app.company_name, role=app.role,
        )
        for log, app in recent_rows
    ]

    return StatsOut(
        **counts, total=total, active=active,
        followup_needed=followup,
        recent_activity=recent_activity,
    )
