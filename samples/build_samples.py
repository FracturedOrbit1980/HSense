"""Create the sample invoice PDF and scan used by the tests and the README."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

ROWS = [
    ["Part No", "Description", "Qty"],
    ["CS1900", "Sealing compound - TIN", "10"],
    ["ANTI-SEIZE", "Anti Seize Compound - 500g", "5"],
    ["GL-750", "PVA wood adhesive - 750g", "8"],
    ["HEX-M8", "Hexagon head screw, stainless steel", "100"],
    ["CEM-50", "Portland cement 50 kg bag", "20"],
    ["OIL-5L", "Engine oil 5L", "4"],
]


def build_pdf(path: Path) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Commercial invoice INV-1044")
    style = ParagraphStyle("h", fontName="Times-Bold", fontSize=14, leading=18)
    small = ParagraphStyle("s", fontName="Times-Roman", fontSize=10, leading=13)
    story = [
        Paragraph("ACME INDUSTRIAL SUPPLIES (PTY) LTD", style),
        Paragraph("Commercial invoice INV-1044", small),
        Paragraph("Date 12 March 2026", small),
        Spacer(1, 12),
    ]
    table = Table(ROWS, colWidths=[110, 280, 60])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8aa0b8")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ]
        )
    )
    story.append(table)
    doc.build(story)


def build_image(path: Path, rotate: int = 0) -> Image.Image:
    image = Image.new("RGB", (1600, 980), "white")
    draw = ImageDraw.Draw(image)
    regular = ImageFont.truetype(FONT, 28)
    bold = ImageFont.truetype(FONT_BOLD, 32)
    draw.text((60, 40), "ACME INDUSTRIAL SUPPLIES (PTY) LTD", fill="black", font=bold)
    draw.text((60, 90), "Commercial invoice INV-1044", fill="black", font=regular)
    draw.text((60, 130), "Date 12 March 2026", fill="black", font=regular)
    y = 210
    draw.rectangle((50, y, 1550, y + 52), fill="#1f4e79")
    draw.text((70, y + 10), "Part No", fill="white", font=bold)
    draw.text((420, y + 10), "Description", fill="white", font=bold)
    draw.text((1380, y + 10), "Qty", fill="white", font=bold)
    y += 70
    for part, description, qty in ROWS[1:]:
        draw.text((70, y), part, fill="black", font=regular)
        draw.text((420, y), description, fill="black", font=regular)
        draw.text((1400, y), qty, fill="black", font=regular)
        y += 64
    if rotate:
        image = image.rotate(rotate, expand=True, fillcolor="white")
    image.save(path)
    return image


def build_scanned_pdf(image_path: Path, pdf_path: Path) -> None:
    picture = Image.open(image_path)
    document = pymupdf.open()
    page = document.new_page(width=picture.width, height=picture.height)
    page.insert_image(page.rect, filename=str(image_path))
    document.save(pdf_path, deflate=True, garbage=4)
    document.close()


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    build_pdf(ROOT / "invoice_digital.pdf")
    build_image(ROOT / "invoice_scan.png")
    build_image(ROOT / "invoice_rotated.png", rotate=90)
    build_scanned_pdf(ROOT / "invoice_scan.png", ROOT / "invoice_scanned.pdf")
    print(f"Wrote samples in {ROOT}")


if __name__ == "__main__":
    main()
