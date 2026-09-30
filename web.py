#!/usr/bin/env python3
"""Browser front end for invoice HS classification.

Run: python web.py
Then open http://127.0.0.1:43123
"""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
from pathlib import Path

from flask import Flask, Response, render_template_string, request

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.tariff_db import TariffDB, format_heading
from engine.classifier import PUBLIC_FIELDS, WCOClassifier
from parsers.line_items import LineItem, _number, collect_descriptions
from parsers.universal_extractor import SUPPORTED_EXTENSIONS, extract_file
from reports.classification_pdf import classification_pdf

PORT = 43123
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

_database = TariffDB()
_classifier = WCOClassifier(_database)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HSense tariff classification</title>
<style>
  :root { color-scheme: light; --ink: #1c2430; --muted: #5c6b7a; --line: #d5dde6; --paper: #f4f7fb; --accent: #1f4e79; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 16px/1.45 "Segoe UI", sans-serif; color: var(--ink); background: var(--paper); }
  header { background: var(--accent); color: white; padding: 28px 20px 22px; }
  header h1 { margin: 0 0 6px; font-size: 1.6rem; font-weight: 650; }
  header p { margin: 0; max-width: 48rem; color: #d7e6f5; }
  main { max-width: 1100px; margin: 0 auto; padding: 22px 16px 48px; }
  form, .panel { background: white; border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
  .grid { display: grid; gap: 12px; grid-template-columns: 160px 1fr 120px; }
  label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 4px; }
  input, textarea { width: 100%; font: inherit; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; }
  textarea { min-height: 160px; resize: vertical; }
  .actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
  button, .button { background: var(--accent); color: white; border: 0; border-radius: 6px; padding: 9px 14px; font: inherit; cursor: pointer; text-decoration: none; }
  button.secondary, .button.secondary { background: white; color: var(--accent); border: 1px solid var(--accent); }
  .note { color: var(--muted); font-size: 0.9rem; margin: 10px 0 0; }
  .error { background: #fff4f2; border: 1px solid #e7b2aa; color: #7a2e24; padding: 10px 12px; border-radius: 8px; margin: 14px 0; }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; background: white; }
  th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 10px 8px; vertical-align: top; }
  th { font-size: 0.78rem; letter-spacing: 0.02em; text-transform: uppercase; color: var(--muted); }
  td.reason { max-width: 28rem; }
  code { font-family: ui-monospace, Consolas, monospace; }
  @media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>HSense</h1>
  <p>Paste every product description, one per line, or upload an invoice. Each description is given an 8-digit SARS tariff code. The PDF lists the tariff header, the description, and the HS code.</p>
</header>
<main>
  <form method="post" enctype="multipart/form-data">
    <div class="grid">
      <div>
        <label for="part">Part number</label>
        <input id="part" name="part_number" value="{{ part_number }}" placeholder="ANTI-SEIZE">
      </div>
      <div>
        <label for="description">Descriptions, one per line</label>
        <textarea id="description" name="description" placeholder="Sealing compound - TIN&#10;Anti Seize Compound - 500g&#10;PVA wood adhesive - 750g&#10;Portland cement 50 kg bag">{{ description }}</textarea>
      </div>
      <div>
        <label for="quantity">Quantity</label>
        <input id="quantity" name="quantity" value="{{ quantity }}" placeholder="5">
      </div>
    </div>
    <p class="note">Or upload a digital PDF, a scanned PDF, or an image. Every description in the file is classified.</p>
    <input type="file" name="document" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp,.heic,.heif">
    <div class="actions">
      <button type="submit">Classify</button>
      {% if rows %}
      <a class="button secondary" href="/export.pdf">Download PDF</a>
      <a class="button secondary" href="/export.json">Download JSON</a>
      <a class="button secondary" href="/export.csv">Download CSV</a>
      {% endif %}
    </div>
  </form>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if rows %}
  <table>
    <thead>
      <tr><th>Line</th><th>Header</th><th>Description</th><th>HS code</th><th>Duty</th></tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ row.line_number }}</td>
        <td>{{ row.header or "" }}</td>
        <td>{{ row.description }}</td>
        <td><code>{{ row.hs_code or "" }}</code></td>
        <td>{{ row.duty_rate_general or "" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
</main>
</body>
</html>
"""

_last_rows: list[dict] = []
_last_source = ""


def _heading_label(hs_code: str | None) -> str:
    if not hs_code:
        return ""
    line = _database.by_code.get(hs_code)
    if line is None:
        return ""
    wording = (_database.heading_text.get(line.heading) or "").strip()
    return f"{format_heading(line.heading)} {wording}".strip()


def _row_from_item(item: LineItem, index: int, source_file: str) -> dict:
    result = _classifier.classify(
        item.description,
        part_number=item.part_number,
        quantity=item.quantity,
        source_file=source_file,
    )
    row = result.as_dict(index)
    row["header"] = _heading_label(row.get("hs_code"))
    return row


def _classify_description(description: str, part_number: str, quantity: str) -> list[dict]:
    descriptions = collect_descriptions(description)
    if not descriptions:
        return []
    single = len(descriptions) == 1
    rows = []
    for index, text in enumerate(descriptions, start=1):
        item = LineItem(
            (part_number.strip() or None) if single else None,
            text,
            _number(quantity) if single and quantity.strip() else None,
            text,
        )
        rows.append(_row_from_item(item, index, "pasted descriptions"))
    return rows


def _classify_upload(upload) -> tuple[list[dict], str]:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Upload a PDF or an image (.jpg, .png, .webp, .tif, .bmp, .heic).")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / Path(upload.filename).name
        upload.save(path)
        extraction = extract_file(path)
    by_description = {item.description.casefold(): item for item in extraction.lines}
    ordered: list[LineItem] = list(extraction.lines)
    for description in collect_descriptions(extraction.text):
        if description.casefold() in by_description:
            continue
        ordered.append(LineItem(None, description, None, description))
        by_description[description.casefold()] = ordered[-1]
    if not ordered:
        detail = " ".join(extraction.warnings) or "No product descriptions were found in that file."
        raise ValueError(detail)
    rows = [
        _row_from_item(item, index, extraction.source_file)
        for index, item in enumerate(ordered, start=1)
    ]
    return rows, extraction.source_file


@app.get("/")
def index():
    return render_template_string(
        PAGE,
        rows=_last_rows,
        error=None,
        description="",
        part_number="",
        quantity="",
    )


@app.post("/")
def classify():
    global _last_rows, _last_source
    description = request.form.get("description") or ""
    part_number = request.form.get("part_number") or ""
    quantity = request.form.get("quantity") or ""
    upload = request.files.get("document")
    error = None
    rows: list[dict] = []
    source = ""
    try:
        if upload and upload.filename:
            rows, source = _classify_upload(upload)
        elif description.strip():
            rows = _classify_description(description, part_number, quantity)
            source = "Pasted descriptions"
            if not rows:
                error = "No product descriptions were found. Put one description on each line."
        else:
            error = "Enter one description per line, or choose a file."
    except Exception as exc:
        error = str(exc)
    _last_rows = rows
    _last_source = source
    return render_template_string(
        PAGE,
        rows=rows,
        error=error,
        description=description,
        part_number=part_number,
        quantity=quantity,
    )


@app.get("/export.pdf")
def export_pdf():
    payload = classification_pdf(
        _last_rows,
        schedule=_database.schedule_date,
        source=_last_source,
    )
    return Response(
        payload,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=hsense.pdf"},
    )


@app.get("/export.json")
def export_json():
    payload = json.dumps(_last_rows, indent=2, ensure_ascii=False)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=hsense.json"},
    )


@app.get("/export.csv")
def export_csv():
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(PUBLIC_FIELDS), extrasaction="ignore")
    writer.writeheader()
    for row in _last_rows:
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in PUBLIC_FIELDS})
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=hsense.csv"},
    )


def main() -> None:
    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
