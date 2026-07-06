import io

import pdfplumber
from fastapi import HTTPException, status


def extract_pdf_text(raw: bytes) -> str:
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"PDF parse failed: {e}")
    return text.strip()
