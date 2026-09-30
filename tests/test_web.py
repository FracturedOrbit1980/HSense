from web import app


def test_opening_the_page_clears_the_previous_classification():
    client = app.test_client()
    posted = client.post("/", data={"description": "Portland cement 50 kg bag"})
    assert posted.status_code == 200
    assert b"2523.29.00" in posted.data
    assert b"Portland cement 50 kg bag" in posted.data
    assert b"Written HS code" not in posted.data

    opened = client.get("/")
    assert opened.status_code == 200
    assert b"2523.29.00" not in opened.data
    assert b"Portland cement 50 kg bag" not in opened.data
    assert "no-store" in opened.headers.get("Cache-Control", "")

    exported = client.get("/export.json")
    assert exported.status_code == 200
    assert exported.data.strip() == b"[]"


def test_authorisation_email_goes_to_olive(monkeypatch):
    from engine.notify import AUTHORITY_INBOX, send_authorisation_email

    assert AUTHORITY_INBOX == "Olive@lud.co.za"
    monkeypatch.delenv("HS_SMTP_USER", raising=False)
    monkeypatch.delenv("HS_SMTP_PASSWORD", raising=False)
    try:
        send_authorisation_email(
            author="Christie",
            checked_at="30 September 2026, 19:25 UTC",
            source="Pasted descriptions",
            rows=[{"description": "Sealing compound - TIN", "hs_code": "3214.10.00"}],
            pdf=b"%PDF",
            verify_url="https://example.test/verify/abc",
        )
    except RuntimeError as exc:
        assert "Olive@lud.co.za" in str(exc)
    else:
        raise AssertionError("email send should require a mailbox login")


def test_phone_camera_photo_is_accepted_for_analysis():
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="JPEG")
    client = app.test_client()
    response = client.post(
        "/",
        data={"camera": (BytesIO(buffer.getvalue()), "camera.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"choose a file" not in response.data
    assert b"Take photo" in response.data


def test_pdf_requires_an_authoriser_and_keeps_an_amended_code(monkeypatch):
    sent = {}

    def capture(**kwargs):
        sent.update(kwargs)

    monkeypatch.setattr("web.send_authorisation_email", capture)
    client = app.test_client()
    client.post("/", data={"description": "Sealing compound - TIN"})
    refused = client.post("/export.pdf", data={"authoriser": "", "hs_1": "3214.10.00"})
    assert refused.status_code == 200
    assert b"Select Christie" in refused.data

    pdf = client.post("/export.pdf", data={"authoriser": "Nelly", "hs_1": "3403.99.90"})
    assert sent["author"] == "Nelly"
    assert sent["pdf"].startswith(b"%PDF")
    assert "Sealing compound" in sent["rows"][0]["description"]
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    import pymupdf

    document = pymupdf.open(stream=pdf.data, filetype="pdf")
    text = document[0].get_text()
    document.close()
    assert "Final check: Nelly" in text
    assert "3403.99.90" in text
    assert "Amended" in text
