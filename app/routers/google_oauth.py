import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_oauth_state_token,
    create_refresh_token,
    decode_token,
    get_current_user_flexible,
    hash_password,
)
from app.models.oauth_token import OAuthToken
from app.models.user import User
from app.schemas.gmail import GmailDisconnectRequest, GmailStatus
from app.services.gmail_service import GMAIL_SCOPES, GOOGLE_LOGIN_SCOPES, oauth_client_config, pkce_pair

router = APIRouter(tags=["google-oauth"])


def _not_configured():
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                             detail="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set in .env")


# ── Google sign-in (creates/authenticates a user, no prior auth required) ───

@router.get("/auth/google/login")
def google_login_start():
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=not_configured")

    verifier, challenge = pkce_pair()
    state = create_oauth_state_token(user_id=None, purpose="login")

    flow = Flow.from_client_config(oauth_client_config(settings.REDIRECT_URI_LOGIN), scopes=GOOGLE_LOGIN_SCOPES)
    flow.redirect_uri = settings.REDIRECT_URI_LOGIN
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", state=f"{state}.{verifier}",
        code_challenge=challenge, code_challenge_method="S256",
    )
    return RedirectResponse(auth_url)


@router.get("/auth/google/login/callback")
def google_login_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                           db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error={error}")
    if not state or "." not in state:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=token_failed")

    signed_state, verifier = state.rsplit(".", 1)
    try:
        payload = decode_token(signed_state, "oauth_state")
    except HTTPException:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=token_failed")
    if payload.get("purpose") != "login":
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=token_failed")

    flow = Flow.from_client_config(oauth_client_config(settings.REDIRECT_URI_LOGIN), scopes=GOOGLE_LOGIN_SCOPES)
    flow.redirect_uri = settings.REDIRECT_URI_LOGIN
    try:
        flow.fetch_token(code=code, code_verifier=verifier)
    except Exception:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=token_failed")

    creds = flow.credentials
    try:
        from googleapiclient.discovery import build

        info = build("oauth2", "v2", credentials=creds).userinfo().get().execute()
        email = (info.get("email") or "").lower().strip()
        name = info.get("name", "")
    except Exception:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=profile_failed")

    if not email:
        return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=no_email")

    user = db.query(User).filter_by(email=email).first()
    if user:
        if not user.name and name:
            user.name = name
    else:
        user = User(email=email, password_hash=hash_password(secrets.token_hex(32)), name=name)
        db.add(user)
        db.flush()

    token_row = db.query(OAuthToken).filter_by(user_id=user.id, provider="google_login").first()
    if token_row:
        token_row.token_json = creds.to_json()
        token_row.email = email
    else:
        db.add(OAuthToken(user_id=user.id, provider="google_login", token_json=creds.to_json(), email=email))
    db.commit()

    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return RedirectResponse(f"{settings.FRONTEND_URL}/?access_token={access}&refresh_token={refresh}")


# ── Connect Gmail for scanning (requires an already-authenticated user) ─────

@router.get("/auth/google")
def google_connect_start(user: User = Depends(get_current_user_flexible)):
    _not_configured()
    verifier, challenge = pkce_pair()
    state = create_oauth_state_token(user_id=user.id, purpose="connect_gmail")

    flow = Flow.from_client_config(oauth_client_config(settings.REDIRECT_URI), scopes=GMAIL_SCOPES)
    flow.redirect_uri = settings.REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", state=f"{state}.{verifier}",
        code_challenge=challenge, code_challenge_method="S256",
    )
    return RedirectResponse(auth_url)


@router.get("/auth/google/callback")
def google_connect_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                             db: Session = Depends(get_db)):
    if error or not state or "." not in state:
        return RedirectResponse(settings.FRONTEND_URL + "/")

    signed_state, verifier = state.rsplit(".", 1)
    try:
        payload = decode_token(signed_state, "oauth_state")
    except HTTPException:
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error=oauth_state_mismatch")
    if payload.get("purpose") != "connect_gmail":
        return RedirectResponse(f"{settings.FRONTEND_URL}/?error=oauth_state_mismatch")
    user_id = int(payload["sub"])

    flow = Flow.from_client_config(oauth_client_config(settings.REDIRECT_URI), scopes=GMAIL_SCOPES)
    flow.redirect_uri = settings.REDIRECT_URI
    flow.fetch_token(code=code, code_verifier=verifier)
    creds = flow.credentials

    try:
        from googleapiclient.discovery import build

        email = build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute().get("emailAddress", "")
    except Exception:
        email = ""

    token_row = db.query(OAuthToken).filter_by(user_id=user_id, provider="google_scan").first()
    if token_row:
        token_row.token_json = creds.to_json()
        token_row.email = email
    else:
        db.add(OAuthToken(user_id=user_id, provider="google_scan", token_json=creds.to_json(), email=email))
    db.commit()

    return RedirectResponse(settings.FRONTEND_URL + "/")


# ── Gmail connection status / disconnect ─────────────────────────────────────

@router.get("/api/gmail/status", response_model=GmailStatus)
def gmail_status(user: User = Depends(get_current_user_flexible), db: Session = Depends(get_db)):
    rows = (
        db.query(OAuthToken)
        .filter(OAuthToken.user_id == user.id, OAuthToken.provider.in_(["google_login", "google_scan", "google"]))
        .all()
    )
    primary = next((r.email for r in rows if r.provider == "google_login"), None)
    scan = next((r.email for r in rows if r.provider in ("google_scan", "google")), None)
    return GmailStatus(primary=primary, scan=scan)


@router.post("/api/gmail/disconnect")
def gmail_disconnect(payload: GmailDisconnectRequest, user: User = Depends(get_current_user_flexible), db: Session = Depends(get_db)):
    if payload.provider not in ("google_scan", "google"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                             detail="Cannot disconnect login account here — use Sign Out instead")
    db.query(OAuthToken).filter_by(user_id=user.id, provider=payload.provider).delete()
    db.commit()
    return {"success": True}
