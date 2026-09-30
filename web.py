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

from data.tariff_db import TariffDB
from engine.classifier import PUBLIC_FIELDS, WCOClassifier
from parsers.line_items import _number
from parsers.universal_extractor import SUPPORTED_EXTENSIONS, extract_file

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
  header p { margin: 0; max-width: 46rem; color: #d7e6f5; }
  main { max-width: 1100px; margin: 0 auto; padding: 22px 16px 48px; }
  form, .panel { background: white; border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
  .grid { display: grid; gap: 12px; grid-template-columns: 1fr 1fr 120px; }
  label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 4px; }
  input, textarea { width: 100%; font: inherit; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; }
  textarea { min-height: 74px; resize: vertical; }
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
  <p>Classify an invoice line, a PDF, or a scan to an 8-digit SARS tariff code. Duty is the General rate from Schedule 1 Part 1, 28 August 2026.</p>
</header>
<main>
  <form method="post" enctype="multipart/form-data">
    <div class="grid">
      <div>
        <label for="part">Part number</label>
        <input id="part" name="part_number" value="{{ part_number }}" placeholder="ANTI-SEIZE">
      </div>
      <div>
        <label for="description">Line description</label>
        <textarea id="description" name="description" placeholder="Anti Seize Compound - 500g">{{ description }}</textarea>
      </div>
      <div>
        <label for="quantity">Quantity</label>
        <input id="quantity" name="quantity" value="{{ quantity }}" placeholder="5">
      </div>
    </div>
    <p class="note">Or upload a digital PDF, a scanned PDF, or an image (.jpg, .png, .webp, .tif, .bmp, .heic).</p>
    <input type="file" name="document" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp,.heic,.heif">
    <div class="actions">
      <button type="submit">Classify</button>
      {% if rows %}
      <a class="button secondary" href="/export.json">Download JSON</a>
      <a class="button secondary" href="/export.csv">Download CSV</a>
      {% endif %}
    </div>
  </form>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if rows %}
  <table>
    <thead>
      <tr><th>Line</th><th>Part</th><th>Description</th><th>Qty</th><th>HS code</th><th>Duty</th><th>WCO reasoning</th></tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ row.line_number }}</td>
        <td>{{ row.part_number or "" }}</td>
        <td>{{ row.description }}</td>
        <td>{{ row.quantity if row.quantity is not none else "" }}</td>
        <td><code>{{ row.hs_code or "" }}</code></td>
        <td>{{ row.duty_rate_general or "" }}</td>
        <td class="reason">{{ row.wco_reasoning }}</td>
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


def _classify_description(description: str, part_number: str, quantity: str) -> list[dict]:
    text = description.strip()
    if not text:
        return []
    result = _classifier.classify(
        text,
        part_number=part_number.strip() or None,
        quantity=_number(quantity) if quantity.strip() else None,
        source_file="manual",
    )
    return [result.as_dict(1)]


def _classify_upload(upload) -> list[dict]:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Upload a PDF or an image (.jpg, .png, .webp, .tif, .bmp, .heic).")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / Path(upload.filename).name
        upload.save(path)
        extraction = extract_file(path)
    if not extraction.lines:
        detail = " ".join(extraction.warnings) or "No product lines were found in that file."
        raise ValueError(detail)
    rows = []
    for index, item in enumerate(extraction.lines, start=1):
        result = _classifier.classify(
            item.description,
            part_number=item.part_number,
            quantity=item.quantity,
            source_file=extraction.source_file,
        )
        rows.append(result.as_dict(index))
    return rows


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
    global _last_rows
    description = request.form.get("description") or ""
    part_number = request.form.get("part_number") or ""
    quantity = request.form.get("quantity") or ""
    upload = request.files.get("document")
    error = None
    rows: list[dict] = []
    try:
        if upload and upload.filename:
            rows = _classify_upload(upload)
        elif description.strip():
            rows = _classify_description(description, part_number, quantity)
        else:
            error = "Enter a product description or choose a file."
    except Exception as exc:
        error = str(exc)
    _last_rows = rows
    return render_template_string(
        PAGE,
        rows=rows,
        error=error,
        description=description,
        part_number=part_number,
        quantity=quantity,
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
