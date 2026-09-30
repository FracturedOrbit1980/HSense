"""Optional multimodal transcription.

Tesseract is the default because the pipeline has to run without a network
key. When ``HS_OCR_BACKEND`` is ``vision`` or ``auto`` and a Gemini API key is
present, a page image can be transcribed by Gemini Flash instead. The model
is asked only to read the page, not to classify it.
"""

from __future__ import annotations

import base64
import io
import json
import os
import urllib.request
from PIL import Image

_PROMPT = (
    "Transcribe this commercial document into plain text. Keep each product "
    "row on its own line, including part number, description and quantity. "
    "Do not classify the goods, do not add HS codes, and do not invent lines "
    "that are not visible."
)


def vision_enabled() -> bool:
    backend = os.getenv("HS_OCR_BACKEND", "tesseract").strip().lower()
    if backend not in {"vision", "auto"}:
        return False
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def transcribe_image(image: Image.Image) -> str | None:
    if not vision_enabled():
        return None
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": _PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
                        }
                    },
                ]
            }
        ]
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    candidates = body.get("candidates") or []
    if not candidates:
        return None
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    texts = [part.get("text", "") for part in parts if part.get("text")]
    transcript = "\n".join(texts).strip()
    return transcript or None
