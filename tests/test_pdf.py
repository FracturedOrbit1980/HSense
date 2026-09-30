import cv2
import numpy as np
import pymupdf

from reports.classification_pdf import classification_pdf
from reports.seal_qr import seal_qr
from pathlib import Path


def test_pdf_lists_header_description_and_code():
    payload = classification_pdf(
        [
            {
                "header": "34.03 Lubricating preparations",
                "description": "Anti Seize Compound - 500g",
                "hs_code": "3403.99.90",
            },
            {
                "header": "32.14 Glaziers' putty, grafting putty, resin cements",
                "description": "Sealing compound - TIN",
                "hs_code": "3214.10.00",
            },
        ],
        schedule="28 August 2026",
        source="Pasted descriptions",
        author="Christie",
        checked_at="30 September 2026, 19:25 UTC",
        verify_url="https://example.test/verify/abc",
    )
    assert payload.startswith(b"%PDF")
    document = pymupdf.open(stream=payload, filetype="pdf")
    assert document.page_count == 1
    text = "\n".join(page.get_text() for page in document)
    assert document[0].get_images()
    document.close()
    assert "Harmonized System" in text
    assert "Schedule 1 Part 1" in text
    assert "Description" in text
    assert "HS code" in text
    assert "Final check: Christie" in text
    assert "3403.99.90" in text
    assert "3214.10.00" in text
    assert "Anti Seize Compound - 500g" in text
    assert "Sealing compound - TIN" in text


def test_qr_seal_stays_readable_with_the_logo():
    payload = seal_qr("https://example.test/verify/abc", Path("static/lud-logo.png"))
    image = cv2.imdecode(np.frombuffer(payload.getvalue(), np.uint8), cv2.IMREAD_COLOR)
    value, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    assert value == "https://example.test/verify/abc"


def test_many_lines_stay_on_one_page():
    rows = [
        {"description": f"Industrial preparation line {index} with a long commercial description", "hs_code": "3403.99.90", "flag": "ok", "duty_rate_general": "Free"}
        for index in range(16)
    ]
    payload = classification_pdf(rows, schedule="28 August 2026", author="Ronel", verify_url="https://example.test/verify/abc")
    document = pymupdf.open(stream=payload, filetype="pdf")
    assert document.page_count == 1
    document.close()
