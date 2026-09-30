import pymupdf

from reports.classification_pdf import classification_pdf


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
    )
    assert payload.startswith(b"%PDF")
    document = pymupdf.open(stream=payload, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    document.close()
    assert "Harmonized System" in text
    assert "Schedule 1 Part 1" in text
    assert "Description" in text
    assert "Written" not in text
    assert "Recommended" in text
    assert "Explanation" in text
    assert "3403.99.90" in text
    assert "3214.10.00" in text
    assert "Anti Seize Compound - 500g" in text
    assert "Sealing compound - TIN" in text
