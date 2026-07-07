import base64
import hashlib
import re
import secrets
from datetime import datetime

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.activity_log import ActivityLog
from app.models.application import Application
from app.models.oauth_token import OAuthToken
from app.services.ai_service import ai_extract_job

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# Deliberately non-sensitive scopes only — Google never shows the "unverified app" warning
# for these, unlike gmail.readonly (a restricted scope). Gmail access is requested
# separately, only when a user explicitly clicks "Connect Gmail" (see GMAIL_SCOPES / the
# /auth/google connect flow), so most users never see that warning at all.
GOOGLE_LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GMAIL_QUERY = (
    'subject:(application OR interview OR "offer letter" OR position '
    "OR vacancy OR hiring OR recruitment OR shortlisted OR assessment)"
)

REJECTION_WORDS = [
    "unfortunately", "regret to inform", "not moving forward",
    "decided not to proceed", "not selected", "other candidates",
    "position has been filled", "will not be moving forward",
    "not been selected", "unsuccessful", "not proceed with your application",
    "not be taking your application further", "chosen not to proceed",
]


def oauth_client_config(redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
    return ""


def get_gmail_service(db: Session, user_id: int):
    """Returns an authenticated Gmail service from a "Connect Gmail" token.

    Only google_scan/google tokens are checked — google_login tokens never carry the
    gmail.readonly scope (see GOOGLE_LOGIN_SCOPES), so they can't build a working service.
    """
    for provider in ("google_scan", "google"):
        row = db.query(OAuthToken).filter_by(user_id=user_id, provider=provider).first()
        if row:
            import json as _json

            creds = Credentials.from_authorized_user_info(_json.loads(row.token_json), GMAIL_SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(GoogleRequest())
                row.token_json = creds.to_json()
                db.commit()
            return build("gmail", "v1", credentials=creds)
    return None


def _normalize_company(name: str) -> str:
    return re.sub(
        r"\b(inc|ltd|llc|corp|co|limited|plc|group|technologies|solutions)\b\.?", "", name.lower()
    ).strip()


def sync_gmail_applications(db: Session, user_id: int, svc, ai_client) -> dict:
    apps = db.query(Application).filter_by(user_id=user_id).all()
    company_map = {_normalize_company(a.company_name): a for a in apps if a.company_name}
    existing_keys = {(a.company_name.lower(), (a.role or "").lower()) for a in apps if a.company_name}

    results = svc.users().messages().list(userId="me", q=GMAIL_QUERY, maxResults=50).execute()
    messages = results.get("messages", [])

    auto_rejected, auto_added, skipped = [], [], []

    for meta in messages:
        msg = svc.users().messages().get(userId="me", id=meta["id"], format="full").execute()
        hdrs = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        subject = hdrs.get("Subject", "")
        body = extract_body(msg["payload"])
        full = (subject + " " + body[:1200]).lower()

        matched = next((a for key, a in company_map.items() if key and key in full), None)
        is_rejection = any(kw in full for kw in REJECTION_WORDS)

        if is_rejection and matched and matched.status not in ("Rejected", "Withdrawn", "Offer"):
            matched.status = "Rejected"
            db.add(ActivityLog(application_id=matched.id, action="Auto-rejected via Gmail sync"))
            auto_rejected.append({"company": matched.company_name, "subject": subject})

        elif not is_rejection and ai_client and not matched:
            extracted = ai_extract_job(ai_client, subject + "\n" + body)
            company = (extracted.get("company") or "").strip()
            role = (extracted.get("role") or "").strip()
            if company and role:
                dedup_key = (company.lower(), role.lower())
                if dedup_key in existing_keys:
                    skipped.append({"company": company, "role": role})
                else:
                    from app.models.cv import CV

                    cv_row = db.query(CV).filter_by(user_id=user_id, is_active=True).first()
                    new_app = Application(
                        user_id=user_id,
                        company_name=company,
                        role=role,
                        job_description=extracted.get("job_description"),
                        status="Applied",
                        date_applied=datetime.now().strftime("%Y-%m-%d"),
                        source="Email",
                        salary_expected=extracted.get("salary"),
                        location=extracted.get("location"),
                        job_url=extracted.get("job_url"),
                        notes=extracted.get("notes"),
                        cv_id=cv_row.id if cv_row else None,
                    )
                    db.add(new_app)
                    db.flush()
                    db.add(ActivityLog(application_id=new_app.id, action="Auto-added via Gmail sync"))
                    existing_keys.add(dedup_key)
                    auto_added.append({"company": company, "role": role})

    return {"auto_rejected": auto_rejected, "auto_added": auto_added, "skipped": skipped}
