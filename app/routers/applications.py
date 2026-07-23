from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import ActivityLog
from app.models.application import Application
from app.models.cv import CV
from app.models.user import User
from app.schemas.application import ApplicationCreate, ApplicationOut, ApplicationUpdate

router = APIRouter(prefix="/api/applications", tags=["applications"])

# Wire (JSON) field name -> ORM column name. The DB schema uses the new spec's naming
# (company_name, date_applied, salary_expected); the JSON API keeps the original field
# names so the existing frontend JS needs no changes.
WIRE_TO_MODEL = {"company": "company_name", "applied_date": "date_applied", "salary": "salary_expected"}


def _to_model_kwargs(data: dict) -> dict:
    return {WIRE_TO_MODEL.get(k, k): v for k, v in data.items()}


def _to_out(app: Application) -> ApplicationOut:
    return ApplicationOut(
        id=app.id,
        company=app.company_name,
        role=app.role,
        status=app.status,
        applied_date=app.date_applied,
        salary=app.salary_expected,
        job_url=app.job_url,
        notes=app.notes,
        job_description=app.job_description,
        source=app.source,
        location=app.location,
        cv_id=app.cv_id,
        cv_filename=app.cv.filename if app.cv else None,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.get("", response_model=list[ApplicationOut])
def list_applications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # joinedload avoids one extra query per row for cv_filename (N+1)
    apps = (
        db.query(Application)
        .options(joinedload(Application.cv))
        .filter_by(user_id=user.id)
        .order_by(Application.created_at.desc())
        .all()
    )
    return [_to_out(a) for a in apps]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_application(payload: ApplicationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = _to_model_kwargs(payload.model_dump())

    # Duplicate check (same company + role, case-insensitive)
    existing = (
        db.query(Application)
        .filter(
            Application.user_id == user.id,
            Application.company_name.ilike(payload.company.strip()),
            Application.role.ilike(payload.role.strip()),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have an application for {payload.role} at {payload.company}",
        )

    if not data.get("cv_id"):
        active_cv = db.query(CV).filter_by(user_id=user.id, is_active=True).first()
        data["cv_id"] = active_cv.id if active_cv else None

    app = Application(user_id=user.id, **data)
    db.add(app)
    db.flush()
    db.add(ActivityLog(application_id=app.id, action=f"Added – {app.role} at {app.company_name}"))
    db.commit()
    return {"success": True, "id": app.id}


@router.put("/{app_id}")
def update_application(app_id: int, payload: ApplicationUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = db.query(Application).filter_by(id=app_id, user_id=user.id).first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    updates = _to_model_kwargs(payload.model_dump(exclude_unset=True))
    for field, value in updates.items():
        setattr(app, field, value)
    if "status" in updates:
        db.add(ActivityLog(application_id=app.id, action=f"Status → {updates['status']}"))
    db.commit()
    return {"success": True}


@router.delete("/{app_id}")
def delete_application(app_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = db.query(Application).filter_by(id=app_id, user_id=user.id).first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(app)
    db.commit()
    return {"success": True}
