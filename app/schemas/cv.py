from datetime import datetime

from pydantic import BaseModel


class CVOut(BaseModel):
    id: int
    filename: str
    is_active: bool
    uploaded_at: datetime


class CVUploadResponse(BaseModel):
    success: bool = True
    id: int
    preview: str


class ActiveCVText(BaseModel):
    text: str | None
