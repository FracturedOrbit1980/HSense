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
<title>HSense</title>
<style>
  :root {
    color-scheme: light;
    --bg: #f4f0e8;
    --ink: #1b1916;
    --muted: #6f675e;
    --card: #fffdf9;
    --line: #e6dfd4;
    --accent: #0e6b62;
    --accent-dark: #0a4f49;
    --chip: #e5f3f1;
    --chip-ink: #0d3d38;
    --danger-bg: #fdecea;
    --danger: #8a332c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font: 16px/1.5 "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
    color: var(--ink);
    background:
      radial-gradient(900px 420px at 0% -10%, #fff 0%, transparent 55%),
      var(--bg);
  }
  .wrap { max-width: 860px; margin: 0 auto; padding: 40px 20px 72px; }
  .brand { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 36px; }
  .brand strong { font-size: 0.95rem; letter-spacing: 0.16em; font-weight: 700; }
  .brand span { color: var(--muted); font-size: 0.85rem; }
  h1 { margin: 0 0 10px; font-size: clamp(2rem, 5vw, 3.1rem); line-height: 1.05; letter-spacing: -0.035em; font-weight: 650; }
  .lede { margin: 0 0 28px; max-width: 36rem; color: var(--muted); font-size: 1.05rem; }
  form, .results { background: var(--card); border: 1px solid var(--line); border-radius: 20px; }
  form { padding: 18px; }
  label.field { display: block; font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
  textarea {
    width: 100%; min-height: 168px; resize: vertical; border: 0; border-radius: 14px;
    background: #f7f4ee; padding: 14px 16px; font: inherit; color: var(--ink);
  }
  textarea:focus { outline: 2px solid var(--accent); background: white; }
  .row { display: flex; gap: 12px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
  .drop {
    display: inline-flex; align-items: center; gap: 8px; padding: 10px 14px;
    border: 1px dashed #cfc6b8; border-radius: 999px; color: var(--ink); cursor: pointer; background: white;
  }
  .drop input { position: absolute; width: 1px; height: 1px; opacity: 0; }
  .drop small { color: var(--muted); }
  button, .pdf {
    border: 0; border-radius: 999px; padding: 11px 18px; font: inherit; font-weight: 600;
    cursor: pointer; text-decoration: none; display: inline-flex; align-items: center;
  }
  button { background: var(--accent); color: white; margin-left: auto; }
  button:hover { background: var(--accent-dark); }
  .pdf { background: var(--ink); color: white; }
  .pdf:hover { background: #000; }
  .hint { margin: 12px 2px 0; color: var(--muted); font-size: 0.9rem; }
  .error { margin-top: 16px; background: var(--danger-bg); color: var(--danger); border-radius: 14px; padding: 12px 14px; }
  .results { margin-top: 22px; overflow: hidden; }
  .bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 18px 18px 0; }
  .bar h2 { margin: 0; font-size: 1.05rem; font-weight: 650; }
  .bar p { margin: 2px 0 0; color: var(--muted); font-size: 0.88rem; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th { text-align: left; font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 600; padding: 12px 18px; }
  td { padding: 14px 18px; border-top: 1px solid var(--line); vertical-align: middle; }
  td.duty { color: var(--muted); white-space: nowrap; }
  .code {
    font-family: ui-monospace, "SFMono-Regular", Consolas, monospace;
    background: var(--chip); color: var(--chip-ink); border-radius: 999px; padding: 4px 10px; font-size: 0.92rem;
  }
  .quiet { margin: 0; padding: 4px 18px 16px; color: var(--muted); font-size: 0.88rem; }
  .quiet a { color: var(--accent-dark); }
  @media (max-width: 640px) {
    button { margin-left: 0; width: 100%; justify-content: center; }
    .bar { align-items: flex-start; flex-direction: column; }
  }
</style>
</head>
<body>
<div class="wrap">
  <div class="brand"><strong>HSENSE</strong><span>Schedule 1 · 28 August 2026</span></div>
  <h1>Codes for the description column.</h1>
  <p class="lede">Upload an invoice or paste the lines under Description. Everything above that header is left alone. Each description gets an 8-digit HS code.</p>
  <form method="post" enctype="multipart/form-data">
    <label class="field" for="description">Under Description</label>
    <textarea id="description" name="description" placeholder="Sealing compound - TIN&#10;Anti Seize Compound - 500g&#10;PVA wood adhesive - 750g">{{ description }}</textarea>
    <div class="row">
      <label class="drop">
        <input type="file" name="document" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp,.heic,.heif">
        <span>Upload invoice</span>
        <small>PDF or image</small>
      </label>
      <button type="submit">Assign HS codes</button>
    </div>
    <p class="hint">Only rows below a Description header are read. A paste with no header is taken one line at a time.</p>
  </form>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if rows %}
  <section class="results">
    <div class="bar">
      <div>
        <h2>{{ rows|length }} description{{ "s" if rows|length != 1 else "" }}</h2>
        <p>Header, description, and HS code are in the PDF.</p>
      </div>
      <a class="pdf" href="/export.pdf">Download PDF</a>
    </div>
    <table>
      <thead><tr><th>Description</th><th>HS code</th><th>Duty</th></tr></thead>
      <tbody>
        {% for row in rows %}
        <tr>
          <td>{{ row.description }}</td>
          <td><span class="code">{{ row.hs_code or "—" }}</span></td>
          <td class="duty">{{ row.duty_rate_general or "" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <p class="quiet"><a href="/export.json">JSON</a> · <a href="/export.csv">CSV</a></p>
  </section>
  {% endif %}
</div>
<script>
  const fileInput = document.querySelector(".drop input");
  const fileLabel = document.querySelector(".drop small");
  if (fileInput && fileLabel) {
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      fileLabel.textContent = file ? file.name : "PDF or image";
    });
  }
</script>
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
    ordered = list(extraction.lines)
    if not ordered and extraction.text:
        for description in collect_descriptions(extraction.text):
            ordered.append(LineItem(None, description, None, description))
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
