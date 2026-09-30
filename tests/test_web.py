from web import app


def test_opening_the_page_clears_the_previous_classification():
    client = app.test_client()
    posted = client.post("/", data={"description": "Portland cement 50 kg bag"})
    assert posted.status_code == 200
    assert b"2523.29.00" in posted.data
    assert b"Portland cement 50 kg bag" in posted.data

    opened = client.get("/")
    assert opened.status_code == 200
    assert b"2523.29.00" not in opened.data
    assert b"Portland cement 50 kg bag" not in opened.data
    assert "no-store" in opened.headers.get("Cache-Control", "")

    exported = client.get("/export.json")
    assert exported.status_code == 200
    assert exported.data.strip() == b"[]"
