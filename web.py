#!/usr/bin/env python3
"""Browser front end for invoice HS classification.

Run: python web.py
Then open http://127.0.0.1:43123
"""

from __future__ import annotations

import csv
import io
import json
import secrets
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, render_template_string, request, send_file

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.tariff_db import TariffDB, format_code, format_heading
from engine.classifier import PUBLIC_FIELDS, WCOClassifier, classify_extracted_lines
from engine.gri import FRAMEWORK
from engine.notify import AUTHORITY_INBOX, send_authorisation_email
from parsers.line_items import LineItem, _number, collect_descriptions, parse_document_text
from parsers.universal_extractor import SUPPORTED_EXTENSIONS, extract_file
from reports.classification_pdf import classification_pdf

PORT = 43123
PREVIEW_PATH = Path("/tmp/hsense-preview/page.png")
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
    --bg: #e7eef6;
    --ink: #0a0a0a;
    --muted: #4f4f4f;
    --card: #ffffff;
    --line: #d5deea;
    --accent: #033591;
    --accent-dark: #022669;
    --chip: #e7eef8;
    --chip-ink: #022669;
    --danger-bg: #fdecea;
    --danger: #8a332c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font: 16px/1.5 "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
    color: var(--ink);
    background: var(--bg);
  }
  .mast {
    position: relative;
    min-height: 248px;
    color: white;
    background: #022669 url("/static/lud-stage.jpg") center right / cover no-repeat;
    overflow: hidden;
  }
  .mast::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(100deg, rgba(2, 38, 105, 0.88) 0%, rgba(2, 38, 105, 0.42) 48%, rgba(3, 53, 145, 0.12) 100%);
  }
  .mast-inner {
    position: relative;
    z-index: 1;
    max-width: 1120px;
    margin: 0 auto;
    padding: 36px 20px 40px;
    display: flex;
    align-items: center;
    gap: 28px;
  }
  .plate {
    flex: 0 0 auto;
    background: #fff;
    border-radius: 18px;
    padding: 14px 16px 10px;
    transform: perspective(900px) rotateY(-10deg) rotateX(5deg);
    transform-style: preserve-3d;
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.9) inset,
      0 22px 36px rgba(0, 0, 0, 0.38),
      0 6px 0 rgba(255, 255, 255, 0.18);
  }
  .plate img { display: block; width: 210px; height: auto; }
  .kicker { margin: 0 0 6px; letter-spacing: 0.16em; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; }
  h1 { margin: 0; font-size: clamp(1.7rem, 3vw, 2.35rem); line-height: 1.08; letter-spacing: -0.03em; font-weight: 700; }
  .when { margin: 8px 0 0; color: rgba(255, 255, 255, 0.82); font-size: 0.92rem; }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 28px 20px 64px; }
  .lede { margin: 0 0 16px; max-width: 46rem; color: var(--muted); font-size: 0.98rem; }
  form, .results, .sheet {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 18px;
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.95) inset,
      0 14px 32px rgba(2, 38, 105, 0.12),
      0 2px 0 rgba(3, 53, 145, 0.05);
  }
  form { padding: 16px; }
  .workspace { display: grid; grid-template-columns: minmax(260px, 380px) minmax(0, 1fr); gap: 18px; align-items: start; margin-top: 18px; }
  .workspace.solo { grid-template-columns: 1fr; }
  label.field { display: block; font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
  textarea {
    width: 100%; min-height: 168px; resize: vertical; border: 0; border-radius: 14px;
    background: #f3f6fb; padding: 14px 16px; font: inherit; color: var(--ink);
    box-shadow: inset 0 2px 6px rgba(2, 38, 105, 0.06);
  }
  textarea:focus { outline: 2px solid var(--accent); background: white; }
  .row { display: flex; gap: 12px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
  .drop {
    display: inline-flex; align-items: center; gap: 8px; padding: 10px 14px;
    border: 1px dashed #8ea4c4; border-radius: 999px; color: var(--ink); cursor: pointer; background: white;
  }
  .drop input { position: absolute; width: 1px; height: 1px; opacity: 0; }
  .drop small { color: var(--muted); }
  button.camera {
    margin-left: 0;
    color: white;
    background: #033591;
    box-shadow: 0 4px 0 #022669, 0 10px 16px rgba(2, 38, 105, 0.25);
  }
  button.camera small { color: rgba(255, 255, 255, 0.82); font-weight: 500; }
  #camera-panel { margin-top: 12px; background: #022669; border-radius: 16px; padding: 10px; }
  #camera-panel[hidden] { display: none; }
  #camera-video { width: 100%; max-height: 62vh; object-fit: cover; border-radius: 12px; background: #000; display: block; }
  .camera-actions { display: flex; gap: 8px; margin-top: 10px; }
  .camera-actions button { margin-left: 0; flex: 1; justify-content: center; }
  #camera-close { background: transparent; color: white; box-shadow: none; border: 1px solid rgba(255, 255, 255, 0.45); }
  button, .pdf {
    border: 0; border-radius: 999px; padding: 11px 18px; font: inherit; font-weight: 600;
    cursor: pointer; text-decoration: none; display: inline-flex; align-items: center;
  }
  button {
    margin-left: auto;
    color: white;
    background: linear-gradient(#0a4cb8, var(--accent));
    box-shadow: 0 4px 0 var(--accent-dark), 0 12px 20px rgba(2, 38, 105, 0.28);
  }
  button:hover { transform: translateY(1px); box-shadow: 0 3px 0 var(--accent-dark), 0 8px 16px rgba(2, 38, 105, 0.24); }
  button:active { transform: translateY(4px); box-shadow: 0 0 0 var(--accent-dark); }
  .pdf {
    color: white;
    background: linear-gradient(#0a0a0a, #262626);
    box-shadow: 0 4px 0 #000, 0 10px 16px rgba(0, 0, 0, 0.18);
  }
  .pdf:hover { transform: translateY(1px); }
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
    background: var(--chip); color: var(--chip-ink); border-radius: 999px; padding: 4px 10px; font-size: 0.9rem; white-space: nowrap;
  }
  .written { color: var(--muted); font-family: ui-monospace, Consolas, monospace; }
  .written.bad { color: var(--danger); text-decoration: line-through; }
  .flag {
    display: inline-flex; align-items: center; border-radius: 999px; padding: 3px 8px;
    background: var(--danger-bg); color: var(--danger); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  }
  tr.bad td { background: #fff8f6; }
  .review { padding: 16px 18px 14px; border-top: 1px solid var(--line); }
  .review.bad { background: #fffaf8; }
  .review.critical { background: #fff4f1; }
  .review.ok { box-shadow: inset 4px 0 0 #1c6b38; }
  .review header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
  .part { margin: 0; font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
  .review h3 { margin: 2px 0 0; font-size: 1.02rem; font-weight: 650; }
  .status { border-radius: 999px; padding: 4px 9px; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; white-space: nowrap; }
  .status.ok { background: #e5f4ea; color: #1c6b38; }
  .status.bad { background: var(--danger-bg); color: var(--danger); }
  .status.critical { background: #2c1210; color: white; }
  .pair { display: grid; grid-template-columns: 1fr; gap: 10px; margin-top: 12px; }
  .pair div { background: #f3f6fb; border-radius: 12px; padding: 10px 12px; box-shadow: inset 0 1px 0 #fff, 0 1px 2px rgba(2, 38, 105, 0.05); }
  .pair span { display: block; font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 4px; }
  .pair strong { font-family: ui-monospace, Consolas, monospace; font-size: 0.98rem; font-weight: 650; }
  .pair em { font-style: normal; color: var(--muted); font-family: inherit; font-size: 0.82rem; font-weight: 600; }
  .why { margin: 10px 0 0; color: #262626; font-size: 0.92rem; }
  @media (max-width: 640px) { .pair { grid-template-columns: 1fr; } }
  .code-input {
    width: 100%; max-width: 220px; font-family: ui-monospace, Consolas, monospace;
    font-size: 1rem; border: 1px solid #8ea4c4; border-radius: 10px; padding: 8px 10px; color: var(--ink); background: white;
  }
  .author-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; padding: 4px 18px 16px; }
  .author-row label { font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
  .author-row select {
    display: block; margin-top: 6px; min-width: 180px; border: 1px solid #8ea4c4; border-radius: 10px;
    padding: 10px 12px; font: inherit; background: white; color: var(--ink);
  }
  .quiet { margin: 0; padding: 4px 18px 16px; color: var(--muted); font-size: 0.88rem; }
  .quiet a { color: var(--accent-dark); }
  .sheet { padding: 12px; position: sticky; top: 16px; }
  .sheet img, #local-preview img { width: 100%; height: auto; border-radius: 12px; display: block; background: #e7eef6; box-shadow: 0 8px 18px rgba(2, 38, 105, 0.12); }
  .sheet figcaption, #local-preview p { margin: 8px 4px 0; color: var(--muted); font-size: 0.82rem; }
  #local-preview { display: none; margin-top: 12px; }
  #local-preview.visible { display: block; }
  .table-wrap { overflow-x: auto; }
  @media (max-width: 860px) {
    .workspace { grid-template-columns: 1fr; }
    .sheet { position: static; }
    button { margin-left: 0; width: 100%; justify-content: center; }
    .bar { align-items: flex-start; flex-direction: column; }
    .camera-actions button { width: auto; }
    .mast-inner { flex-direction: column; align-items: flex-start; }
    .plate { transform: none; }
    .plate img { width: 180px; }
  }
</style>
</head>
<body>
<header class="mast">
  <div class="mast-inner">
    <a class="plate" href="https://www.lud.co.za/" target="_blank" rel="noopener">
      <img src="/static/lud-logo.png" alt="LUD Logistics" width="210" height="92">
    </a>
    <div>
      <p class="kicker">HSense</p>
      <h1>Check the description column.</h1>
      <p class="when">Schedule 1 · {{ schedule }}</p>
    </div>
  </div>
</header>
<div class="wrap">
  <p class="lede">{{ framework }}, {{ schedule }}. Lines under Description are classified to an 8-digit line, and a handwritten code is verified against that line.</p>
  <form id="classify-form" method="post" enctype="multipart/form-data" autocomplete="off">
    <label class="field" for="description">Or paste the lines under Description</label>
    <textarea id="description" name="description" autocomplete="off" placeholder="Sealing compound - TIN&#10;Anti Seize Compound - 500g&#10;PVA wood adhesive - 750g">{{ description }}</textarea>
    <div id="local-preview"><img alt="Selected document"><p></p></div>
    <div class="row">
      <label class="drop">
        <input type="file" name="document" accept=".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp,.heic,.heif,image/*">
        <span>Upload invoice</span>
        <small>PDF or image</small>
      </label>
      <button type="button" class="camera" id="open-camera"><span>Take photo</span><small>Phone camera</small></button>
      <input id="camera-input" type="file" name="camera" accept="image/*" capture="environment" hidden>
      <button type="submit">Assign HS codes</button>
    </div>
    <div id="camera-panel" hidden>
      <video id="camera-video" autoplay playsinline muted></video>
      <div class="camera-actions">
        <button type="button" id="camera-close">Close</button>
        <button type="button" id="camera-shutter">Use this photo</button>
      </div>
    </div>
    <p class="hint">Take a photo with the phone camera, or upload a file. A handwritten " repeats the code above.</p>
  </form>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if rows or preview %}
  <div class="workspace{% if not preview %} solo{% endif %}">
    {% if preview %}
    <figure class="sheet">
      <img src="/preview?t={{ preview_token }}" alt="Preview of {{ document_name or 'the uploaded document' }}">
      <figcaption>Uploaded invoice</figcaption>
    </figure>
    {% endif %}
    {% if rows %}
    <form class="results" method="post" action="/export.pdf">
      <div class="bar">
        <div>
          <h2>{{ rows|length }} description{{ "s" if rows|length != 1 else "" }}</h2>
          <p>{% if flagged %}{{ flagged }} handwritten code{{ "s" if flagged != 1 else "" }} to check.{% else %}Handwritten codes match, or none were read.{% endif %}</p>
        </div>
      </div>
      {% for row in rows %}
      {% set tone = 'critical' if row.flag == 'critical' else ('bad' if row.flag == 'incorrect' else ('ok' if row.flag == 'ok' else '')) %}
      <article class="review {{ tone }}">
        <header>
          <div>
            {% if row.part_number %}<p class="part">{{ row.part_number }}</p>{% endif %}
            <h3>{{ row.description }}</h3>
          </div>
          {% if row.flag == 'ok' %}<span class="status ok">Correct</span>
          {% elif row.flag == 'critical' %}<span class="status critical">Critical</span>
          {% elif row.flag == 'incorrect' %}<span class="status bad">Incorrect</span>
          {% endif %}
        </header>
        <div class="pair">
          <div>
            <span>HS code</span>
            <input class="code-input" name="hs_{{ row.line_number }}" value="{{ row.hs_code or '' }}" autocomplete="off" aria-label="HS code for {{ row.description }}">
          </div>
        </div>
        {% if row.explanation %}<p class="why">{{ row.explanation }}</p>{% endif %}
      </article>
      {% endfor %}
      <div class="author-row">
        <label>Authorise
          <select name="authoriser" required>
            <option value="">Select name</option>
            {% for name in authorisers %}<option>{{ name }}</option>{% endfor %}
          </select>
        </label>
        <button class="pdf" type="submit">Download PDF</button>
        <p class="hint">Authorising emails the PDF to {{ authority_inbox }}.</p>
      </div>
      <p class="quiet"><a href="/export.json">JSON</a> · <a href="/export.csv">CSV</a></p>
    </form>
    {% endif %}
  </div>
  {% endif %}
</div>
<script>
  const fileInput = document.querySelector(".drop input");
  const fileLabel = document.querySelector(".drop small");
  const localPreview = document.getElementById("local-preview");
  const localImage = localPreview.querySelector("img");
  const localCaption = localPreview.querySelector("p");
  const classifyForm = document.getElementById("classify-form");
  const cameraInput = document.getElementById("camera-input");
  const openCamera = document.getElementById("open-camera");
  const cameraPanel = document.getElementById("camera-panel");
  const cameraVideo = document.getElementById("camera-video");
  const cameraShutter = document.getElementById("camera-shutter");
  const cameraClose = document.getElementById("camera-close");
  let cameraStream = null;
  let useNativeCamera = !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

  function showPreview(file) {
    if (!file) {
      localPreview.classList.remove("visible");
      return;
    }
    localCaption.textContent = file.name || "Photo";
    if (file.type.startsWith("image/")) {
      localImage.src = URL.createObjectURL(file);
      localImage.hidden = false;
    } else {
      localImage.removeAttribute("src");
      localImage.hidden = true;
      localCaption.textContent = (file.name || "File") + " — preview appears after classification";
    }
    localPreview.classList.add("visible");
  }

  function stopCamera() {
    if (cameraStream) {
      cameraStream.getTracks().forEach((track) => track.stop());
      cameraStream = null;
    }
    if (cameraVideo) cameraVideo.srcObject = null;
    if (cameraPanel) cameraPanel.hidden = true;
  }

  if (fileInput && fileLabel) {
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      fileLabel.textContent = file ? file.name : "PDF or image";
      showPreview(file);
    });
  }

  if (openCamera && cameraInput) {
    openCamera.addEventListener("click", async () => {
      if (useNativeCamera) {
        cameraInput.click();
        return;
      }
      try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" } },
        });
        cameraVideo.srcObject = cameraStream;
        cameraPanel.hidden = false;
      } catch (error) {
        useNativeCamera = true;
        cameraInput.click();
      }
    });
    cameraInput.addEventListener("change", () => {
      const file = cameraInput.files && cameraInput.files[0];
      if (!file) return;
      showPreview(file);
      classifyForm.requestSubmit();
    });
  }

  if (cameraClose) cameraClose.addEventListener("click", stopCamera);
  if (cameraShutter) {
    cameraShutter.addEventListener("click", () => {
      if (!cameraVideo.videoWidth) return;
      const canvas = document.createElement("canvas");
      canvas.width = cameraVideo.videoWidth;
      canvas.height = cameraVideo.videoHeight;
      canvas.getContext("2d").drawImage(cameraVideo, 0, 0);
      canvas.toBlob((blob) => {
        if (!blob) return;
        const photo = new File([blob], "camera.jpg", { type: "image/jpeg" });
        const transfer = new DataTransfer();
        transfer.items.add(photo);
        cameraInput.files = transfer.files;
        stopCamera();
        showPreview(photo);
        classifyForm.requestSubmit();
      }, "image/jpeg", 0.92);
    });
  }
</script>
</body>
</html>
"""

AUTHORISERS = ("Christie", "Ronel", "Nelly", "Thabang")

_last_rows: list[dict] = []
_last_source = ""
_preview_token = ""
_seals: dict[str, dict] = {}


def _save_preview(path: Path) -> None:
    global _preview_token
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf

        document = pymupdf.open(path)
        page = document[0]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
        pixmap.save(PREVIEW_PATH)
        document.close()
    else:
        from PIL import Image

        image = Image.open(path).convert("RGB")
        image.thumbnail((1600, 2000))
        image.save(PREVIEW_PATH, "PNG")
    _preview_token = str(time.time())


def _clear_preview() -> None:
    global _preview_token
    _preview_token = ""
    if PREVIEW_PATH.exists():
        PREVIEW_PATH.unlink()


def _reset_session() -> None:
    """Drop the last invoice, pasted lines, and preview when the page is opened."""
    global _last_rows, _last_source
    _last_rows = []
    _last_source = ""
    _clear_preview()


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Permissions-Policy"] = "camera=*"
    return response


def _view_context(**extra):
    rows = extra.get("rows", _last_rows)
    flagged = sum(1 for row in rows if row.get("flag") in {"incorrect", "critical"})
    extra.setdefault("rows", rows)
    extra.setdefault("description", "")
    extra.setdefault("part_number", "")
    extra.setdefault("quantity", "")
    extra.setdefault("error", None)
    extra.setdefault("document_name", _last_source)
    extra["authorisers"] = AUTHORISERS
    extra["authority_inbox"] = AUTHORITY_INBOX
    extra["framework"] = FRAMEWORK
    extra["schedule"] = _database.schedule_date
    extra["preview"] = bool(_preview_token and PREVIEW_PATH.exists())
    extra["preview_token"] = _preview_token
    extra["flagged"] = flagged
    return extra


def _heading_label(hs_code: str | None) -> str:
    if not hs_code:
        return ""
    line = _database.by_code.get(hs_code)
    if line is None:
        return ""
    wording = (_database.heading_text.get(line.heading) or "").strip()
    return f"{format_heading(line.heading)} {wording}".strip()


def _with_headers(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["header"] = _heading_label(row.get("hs_code"))
    return rows


def _classify_description(description: str, part_number: str, quantity: str) -> list[dict]:
    items = parse_document_text(description)
    if not items:
        items = [LineItem(None, text, None, text) for text in collect_descriptions(description)]
    if not items:
        return []
    if len(items) == 1:
        if part_number.strip():
            items[0].part_number = part_number.strip()
        if quantity.strip():
            items[0].quantity = _number(quantity)
    return _with_headers(classify_extracted_lines(_classifier, items, "pasted descriptions"))


def _chosen_upload():
    """A phone photo is sent as `camera`. A chosen file is sent as `document`."""
    camera = request.files.get("camera")
    document = request.files.get("document")
    if camera is not None and camera.filename:
        return camera
    if document is not None and document.filename:
        return document
    return None


def _classify_upload(upload) -> tuple[list[dict], str]:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        kind = (upload.mimetype or "").split(";")[0].strip().lower()
        guessed = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/heic": ".heic",
            "image/heif": ".heif",
            "application/pdf": ".pdf",
        }.get(kind)
        if guessed is None:
            raise ValueError("Upload a PDF or an image (.jpg, .png, .webp, .tif, .bmp, .heic).")
        upload.filename = f"camera{guessed}"
        suffix = guessed
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / Path(upload.filename).name
        upload.save(path)
        _save_preview(path)
        extraction = extract_file(path)
    ordered = list(extraction.lines)
    if not ordered and extraction.text:
        for description in collect_descriptions(extraction.text):
            ordered.append(LineItem(None, description, None, description))
    if not ordered:
        detail = " ".join(extraction.warnings) or "No product descriptions were found in that file."
        raise ValueError(detail)
    rows = _with_headers(classify_extracted_lines(_classifier, ordered, extraction.source_file))
    return rows, extraction.source_file


@app.get("/")
def index():
    _reset_session()
    return _no_store(app.make_response(render_template_string(PAGE, **_view_context())))


@app.get("/preview")
def preview():
    if not PREVIEW_PATH.exists():
        return Response(status=404)
    return send_file(PREVIEW_PATH, mimetype="image/png", max_age=0)


@app.post("/")
def classify():
    global _last_rows, _last_source
    description = request.form.get("description") or ""
    part_number = request.form.get("part_number") or ""
    quantity = request.form.get("quantity") or ""
    upload = _chosen_upload()
    error = None
    rows: list[dict] = []
    source = ""
    try:
        if upload and upload.filename:
            rows, source = _classify_upload(upload)
        elif description.strip():
            _clear_preview()
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
    return _no_store(app.make_response(render_template_string(
        PAGE,
        **_view_context(
            rows=rows,
            error=error,
            description=description,
            part_number=part_number,
            quantity=quantity,
            document_name=source,
        ),
    )))


def _pdf_response(rows: list[dict], author: str) -> Response:
    checked_at = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    seal = secrets.token_urlsafe(9)
    _seals[seal] = {
        "author": author,
        "checked_at": checked_at,
        "source": _last_source,
        "lines": [
            {
                "description": row.get("description") or "",
                "hs_code": row.get("hs_code") or "",
                "flag": row.get("flag") or "",
                "amended": bool(row.get("amended")),
            }
            for row in rows
        ],
    }
    verify_url = request.host_url.rstrip("/") + "/verify/" + seal
    payload = classification_pdf(
        rows,
        schedule=_database.schedule_date,
        source=_last_source,
        author=author,
        checked_at=checked_at,
        verify_url=verify_url,
    )
    send_authorisation_email(
        author=author,
        checked_at=checked_at,
        source=_last_source,
        rows=rows,
        pdf=payload,
        verify_url=verify_url,
    )
    return Response(
        payload,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=hsense.pdf"},
    )


def _amended_rows() -> tuple[list[dict] | None, str | None]:
    author = (request.form.get("authoriser") or "").strip()
    if author not in AUTHORISERS:
        return None, "Select Christie, Ronel, Nelly, or Thabang to authorise the PDF."
    if not _last_rows:
        return None, "Classify the descriptions before downloading the PDF."
    prepared: list[dict] = []
    for row in _last_rows:
        raw = request.form.get(f"hs_{row.get('line_number')}") or row.get("hs_code") or ""
        formatted = format_code(raw)
        if formatted is None:
            return None, f"Enter an 8-digit HS code for {row.get('description') or 'each line'}."
        updated = dict(row)
        updated["amended"] = formatted != (row.get("hs_code") or "")
        updated["hs_code"] = formatted
        updated["recommended_label"] = formatted
        line = _database.get(formatted)
        if line is not None:
            updated["duty_rate_general"] = line.duty_general
        prepared.append(updated)
    return prepared, None


@app.post("/export.pdf")
def export_pdf():
    rows, error = _amended_rows()
    if error or rows is None:
        return _no_store(app.make_response(render_template_string(
            PAGE,
            **_view_context(
                rows=_last_rows,
                error=error,
                document_name=_last_source,
            ),
        )))
    try:
        return _pdf_response(rows, (request.form.get("authoriser") or "").strip())
    except Exception as exc:
        return _no_store(app.make_response(render_template_string(
            PAGE,
            **_view_context(
                rows=_last_rows,
                error=str(exc),
                document_name=_last_source,
            ),
        )))


@app.get("/verify/<seal>")
def verify(seal: str):
    record = _seals.get(seal)
    if record is None:
        body = "<h1>Not authenticated</h1><p>This seal is not on file.</p>"
        status = 404
    else:
        lines = "".join(
            f"<li>{line['description']} — {line['hs_code']}</li>" for line in record["lines"]
        )
        body = (
            f"<p class=\"kicker\">Authenticated</p>"
            f"<h1>Final check: {record['author']}</h1>"
            f"<p>{record['checked_at']}</p><ul>{lines}</ul>"
        )
        status = 200
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HSense authentication</title>
<style>
  body {{ margin: 0; font: 16px/1.5 "Segoe UI", sans-serif; background: #e7eef6; color: #0a0a0a; }}
  main {{ max-width: 640px; margin: 32px auto; background: white; border-radius: 18px; padding: 24px; }}
  .kicker {{ letter-spacing: 0.14em; text-transform: uppercase; color: #033591; font-weight: 700; font-size: 0.78rem; }}
  h1 {{ margin: 6px 0; color: #022669; }}
</style></head><body><main>{body}</main></body></html>"""
    return Response(page, status=status, mimetype="text/html")


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
