from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/")
def index(request: Request):
    # Auth is enforced client-side (JWT in localStorage) since there's no server session;
    # the page JS redirects to /login if it has no valid token.
    return templates.TemplateResponse(
        request, "index.html", {"google_site_verification": settings.GOOGLE_SITE_VERIFICATION}
    )


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    has_users = db.query(User).first() is not None
    return templates.TemplateResponse(
        request, "login.html", {"mode": "login", "can_register": not has_users}
    )


@router.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    has_users = db.query(User).first() is not None
    if has_users:
        return templates.TemplateResponse(request, "login.html", {"mode": "login", "can_register": False})
    return templates.TemplateResponse(request, "login.html", {"mode": "register", "can_register": True})


@router.get("/privacy")
def privacy_page(request: Request):
    return templates.TemplateResponse(
        request, "privacy.html", {"app_name": settings.APP_NAME, "support_email": settings.SUPPORT_EMAIL}
    )


@router.get("/terms")
def terms_page(request: Request):
    return templates.TemplateResponse(
        request, "terms.html", {"app_name": settings.APP_NAME, "support_email": settings.SUPPORT_EMAIL}
    )
