"""QR seal with the LUD logo in the centre."""

from __future__ import annotations

import io
from pathlib import Path

import qrcode
from PIL import Image
from qrcode.constants import ERROR_CORRECT_H


def seal_qr(payload: str, logo_path: Path) -> io.BytesIO:
    """Return a PNG QR code. The logo sits in the middle; error correction stays high enough to scan."""
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=8, border=2)
    code.add_data(payload)
    code.make(fit=True)
    image = code.make_image(fill_color="#022669", back_color="white").convert("RGBA")
    logo = Image.open(logo_path).convert("RGBA")
    side = max(int(image.size[0] * 0.22), 32)
    badge = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    logo.thumbnail((side - 8, side - 8))
    badge.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2), logo)
    origin = ((image.size[0] - side) // 2, (image.size[1] - side) // 2)
    image.paste(badge, origin, badge)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
