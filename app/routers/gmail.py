from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.gmail import GmailScanResponse, GmailSyncResponse
from app.services.ai_service import get_ai_client
from app.services.gmail_service import GMAIL_QUERY, extract_body, get_gmail_service, sync_gmail_applications

router = APIRouter(prefix="/api", tags=["gmail"])


@router.post("/gmail_scan", response_model=GmailScanResponse)
def gmail_scan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc = get_gmail_service(db, user.id)
    if not svc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                             detail='Gmail not connected — click "Connect Gmail" on the Import page')
    try:
        results = svc.users().messages().list(userId="me", q=GMAIL_QUERY, maxResults=25).execute()
        messages = results.get("messages", [])
        found = []
        for meta in messages:
            msg = svc.users().messages().get(userId="me", id=meta["id"], format="full").execute()
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            body = extract_body(msg["payload"])
            found.append({
                "subject": headers.get("Subject", ""),
                "sender": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "body": body[:2500],
            })
            if len(found) >= 20:
                break
        return GmailScanResponse(emails=found, count=len(found))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/gmail/sync", response_model=GmailSyncResponse)
def gmail_sync(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc = get_gmail_service(db, user.id)
    if not svc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                             detail="Gmail not connected — connect it in the Inbox tab")
    ai_client = get_ai_client()
    try:
        result = sync_gmail_applications(db, user.id, svc, ai_client)
        user.last_gmail_sync = datetime.now(timezone.utc)
        db.commit()
        return GmailSyncResponse(**result)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
