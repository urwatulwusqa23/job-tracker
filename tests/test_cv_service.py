import pytest
from fastapi import HTTPException

from app.services.cv_service import extract_pdf_text

MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 44>>stream\n"
    b"BT /F1 12 Tf 10 100 Td (Hello CV Test) Tj ET\n"
    b"endstream\nendobj\n"
    b"xref\n0 6\ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n0\n%%EOF"
)


def test_extract_pdf_text_returns_text():
    text = extract_pdf_text(MINIMAL_PDF)
    assert "Hello CV Test" in text


def test_extract_pdf_text_raises_on_garbage_bytes():
    with pytest.raises(HTTPException) as exc_info:
        extract_pdf_text(b"this is not a pdf at all")
    assert exc_info.value.status_code == 500
