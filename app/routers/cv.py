import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, get_current_user_flexible
from app.models.cv import CV
from app.models.user import User
from app.schemas.cv import ActiveCVText, CVOut, CVUploadResponse
from app.services.cv_service import extract_pdf_text

router = APIRouter(prefix="/api/cv", tags=["cv"])


def _to_out(cv: CV) -> CVOut:
    return CVOut(id=cv.id, filename=cv.filename, is_active=cv.is_active, uploaded_at=cv.created_at)


@router.get("", response_model=list[CVOut])
def list_cvs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cvs = db.query(CV).filter_by(user_id=user.id).order_by(CV.created_at.desc()).all()
    return [_to_out(c) for c in cvs]


@router.post("", response_model=CVUploadResponse)
async def upload_cv(file: UploadFile, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    raw = await file.read()
    text = extract_pdf_text(raw)

    db.query(CV).filter_by(user_id=user.id).update({"is_active": False})
    cv = CV(user_id=user.id, filename=file.filename, extracted_text=text, file_data=raw, is_active=True)
    db.add(cv)
    db.commit()
    db.refresh(cv)
    return CVUploadResponse(id=cv.id, preview=text[:600])


@router.post("/{cv_id}/activate")
def activate_cv(cv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cv = db.query(CV).filter_by(id=cv_id, user_id=user.id).first()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.query(CV).filter_by(user_id=user.id).update({"is_active": False})
    cv.is_active = True
    db.commit()
    return {"success": True}


@router.get("/active_text", response_model=ActiveCVText)
def active_cv_text(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cv = db.query(CV).filter_by(user_id=user.id, is_active=True).first()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active CV")
    return ActiveCVText(text=cv.extracted_text)


@router.get("/{cv_id}/download")
def download_cv(cv_id: int, user: User = Depends(get_current_user_flexible), db: Session = Depends(get_db)):
    # Uses the flexible auth dependency (Authorization header OR ?token=) because this
    # endpoint is reached via a plain <a href> browser navigation, not a fetch() call.
    cv = db.query(CV).filter_by(id=cv_id, user_id=user.id).first()
    if not cv or not cv.file_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return StreamingResponse(
        io.BytesIO(cv.file_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{cv.filename}"'},
    )
