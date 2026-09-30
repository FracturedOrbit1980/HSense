"""Route a file to native PDF text or OCR and return invoice lines.

Digital PDFs are read with pdfplumber (pypdf if that fails). A PDF whose
text layer is empty is treated as a scan: each page is rendered and passed
through the image preprocessor and Tesseract. Photographs and HEIC files
take the same image path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from parsers.line_items import LineItem, parse_document_text, parse_tables
from parsers.vision_ocr import transcribe_image, vision_enabled
from utils.image_preprocessor import (
    IMAGE_EXTENSIONS,
    load_frames,
    pdf_pages_to_images,
    preprocess_image,
)

SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}


@dataclass
class Extraction:
    source_file: str
    route: str
    lines: list[LineItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    text: str = ""


def extract_file(path: str | Path, *, dpi: int = 300) -> Extraction:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_dir():
        raise IsADirectoryError(source)
    suffix = source.suffix.lower()
    if suffix == ".pdf" or _looks_like_pdf(source):
        return _extract_pdf(source, dpi)
    if suffix in IMAGE_EXTENSIONS or suffix == "":
        return _extract_image(source)
    raise ValueError(
        f"Unsupported file type '{suffix or source.name}'. "
        "Use a PDF or an image (.jpg, .jpeg, .png, .webp, .tif, .tiff, .bmp, .heic)."
    )


def iter_inputs(path: str | Path) -> list[Path]:
    source = Path(path)
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(source)
    files = [
        item
        for item in sorted(source.rglob("*"))
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return files


def _extract_pdf(path: Path, dpi: int) -> Extraction:
    text, tables, warning = _read_digital_pdf(path)
    if _enough_text(text):
        lines = _choose_lines(text, tables)
        if lines:
            return Extraction(path.name, "digital_pdf", lines, _warn(warning), text)
    images = pdf_pages_to_images(path, dpi=dpi)
    if not images:
        return Extraction(
            path.name,
            "scanned_pdf",
            [],
            ["The PDF had no text layer and no pages could be rendered."],
            text,
        )
    ocr_chunks = [_ocr_page(image) for image in images]
    ocr_text = "\n".join(chunk for chunk in ocr_chunks if chunk)
    lines = parse_document_text(ocr_text)
    warnings = _warn(warning)
    if not lines:
        warnings.append("No product lines were found after OCR of the PDF pages.")
    return Extraction(path.name, "scanned_pdf", lines, warnings, ocr_text or text)


def _extract_image(path: Path) -> Extraction:
    frames = load_frames(path)
    chunks = [_ocr_page(frame) for frame in frames]
    text = "\n".join(chunk for chunk in chunks if chunk)
    lines = parse_document_text(text)
    warnings = []
    if not lines:
        warnings.append("No product lines were found in the image.")
    return Extraction(path.name, "image", lines, warnings, text)


def _ocr_page(image) -> str:
    if getattr(image, "width", 0) and image.width < 1400:
        image = image.resize((image.width * 2, image.height * 2))
    if vision_enabled():
        transcript = transcribe_image(image)
        if transcript and _enough_text(transcript):
            return transcript
    prepared = preprocess_image(image)
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pytesseract is not installed") from exc
    config = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(prepared, lang="eng", config=config)
    if _letter_count(text) < 20:
        binary = _hard_threshold(prepared)
        retry = pytesseract.image_to_string(binary, lang="eng", config=config)
        if _letter_count(retry) > _letter_count(text):
            text = retry
    return text


def _hard_threshold(image):
    import cv2
    import numpy as np
    from PIL import Image

    gray = np.array(image.convert("L"))
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8
    )
    return Image.fromarray(binary)


def _read_digital_pdf(path: Path) -> tuple[str, list, str | None]:
    try:
        import pdfplumber

        texts: list[str] = []
        tables: list = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                texts.append(page.extract_text() or "")
                tables.extend(page.extract_tables() or [])
        return "\n".join(texts), tables, None
    except Exception as exc:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            return text, [], f"pdfplumber failed ({exc}); used pypdf."
        except Exception as inner:
            return "", [], f"Digital PDF parsing failed: {inner}"


def _choose_lines(text: str, tables: list) -> list[LineItem]:
    """Prefer the Description column of a table over loose text on the page."""
    from_tables = parse_tables(tables)
    if from_tables:
        return from_tables
    return parse_document_text(text)


def _enough_text(text: str) -> bool:
    return _letter_count(text) >= 40


def _letter_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]", text or ""))


def _looks_like_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _warn(message: str | None) -> list[str]:
    return [message] if message else []
