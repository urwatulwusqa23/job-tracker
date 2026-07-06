from pydantic import BaseModel


class GmailEmail(BaseModel):
    subject: str
    sender: str
    date: str
    body: str


class GmailScanResponse(BaseModel):
    emails: list[GmailEmail]
    count: int


class GmailSyncItem(BaseModel):
    company: str
    role: str | None = None
    subject: str | None = None


class GmailSyncResponse(BaseModel):
    auto_rejected: list[GmailSyncItem]
    auto_added: list[GmailSyncItem]
    skipped: list[GmailSyncItem]


class GmailStatus(BaseModel):
    primary: str | None
    scan: str | None


class GmailDisconnectRequest(BaseModel):
    provider: str = "google_scan"
