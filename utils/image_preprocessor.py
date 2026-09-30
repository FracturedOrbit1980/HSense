"""Normalize scans and photographs before OCR.

The intake path is the same for a phone photo, a multipage TIFF, a HEIC
export, or a page rendered from a scanned PDF: correct orientation, deskew
small rotations, and lift contrast without destroying the glyphs Tesseract
needs.
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, ImageSequence

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - optional codec
    pillow_heif = None

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".heic",
    ".heif",
}


def load_frames(path: str | Path) -> list[Image.Image]:
    """Load every frame of an image file as an RGB page."""
    image = Image.open(path)
    frames: list[Image.Image] = []
    for frame in ImageSequence.Iterator(image):
        oriented = ImageOps.exif_transpose(frame) or frame
        frames.append(oriented.convert("RGB"))
    if not frames:
        frames.append(ImageOps.exif_transpose(image).convert("RGB"))
    return frames


def pdf_pages_to_images(path: str | Path, dpi: int = 300) -> list[Image.Image]:
    """Render PDF pages to RGB images.

    ``pdf2image`` (Poppler) is preferred. PyMuPDF is the fallback when Poppler
    cannot open the file.
    """
    try:
        from pdf2image import convert_from_path

        pages = convert_from_path(str(path), dpi=dpi)
        if pages:
            return [page.convert("RGB") for page in pages]
    except Exception:
        pass
    return _render_with_pymupdf(path, dpi)


def _render_with_pymupdf(path: str | Path, dpi: int) -> list[Image.Image]:
    import pymupdf

    document = pymupdf.open(str(path))
    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    images: list[Image.Image] = []
    for page in document:
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        images.append(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
    document.close()
    return images


def preprocess_image(image: Image.Image, *, autorotate: bool = True) -> Image.Image:
    """Return a grayscale page ready for OCR."""
    rgb = image.convert("RGB")
    if autorotate:
        rgb = correct_orientation(rgb)
    rgb = _scale_for_ocr(rgb)
    gray = _to_gray(rgb)
    gray = _deskew(gray)
    gray = cv2.medianBlur(gray, 3)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return Image.fromarray(gray)


def correct_orientation(image: Image.Image) -> Image.Image:
    """Rotate by 90-degree steps when Tesseract OSD is confident."""
    try:
        import pytesseract

        osd = pytesseract.image_to_osd(image, config="--psm 0")
    except Exception:
        return image
    rotate = re.search(r"Rotate:\s+(\d+)", osd or "")
    confidence = re.search(r"Orientation confidence:\s+([\d.]+)", osd or "")
    if not rotate or not confidence:
        return image
    if float(confidence.group(1)) < 1.2:
        return image
    angle = int(rotate.group(1)) % 360
    if angle == 0:
        return image
    # OSD "Rotate" is the clockwise correction. PIL rotates counter-clockwise.
    return image.rotate(-angle, expand=True, fillcolor="white")


def _scale_for_ocr(image: Image.Image, min_side: int = 1400, max_side: int = 3200) -> Image.Image:
    width, height = image.size
    long_side = max(width, height)
    if long_side == 0:
        return image
    if long_side < min_side:
        scale = min_side / long_side
    elif long_side > max_side:
        scale = max_side / long_side
    else:
        return image
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _to_gray(image: Image.Image) -> np.ndarray:
    array = np.array(image.convert("RGB"))
    return cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Correct a small skew. Quarter-turns are left to OSD."""
    _threshold, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))
    if coords.shape[0] < 300:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.4 or abs(angle) > 10:
        return gray
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        gray,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )
