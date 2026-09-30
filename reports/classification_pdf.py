"""One-page PDF of classified descriptions, with an authentication QR seal."""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from reports.seal_qr import seal_qr

LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "lud-logo.png"


def _clip(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _note(row: dict) -> str:
    flag = row.get("flag") or ""
    if flag == "critical":
        mark = "Critical"
    elif flag == "incorrect":
        mark = "Incorrect"
    elif flag == "ok":
        mark = "Correct"
    else:
        mark = ""
    bits = [part for part in (mark, "Amended" if row.get("amended") else "", row.get("duty_rate_general") or "") if part]
    return " · ".join(bits)


def classification_pdf(
    rows: list[dict],
    *,
    schedule: str,
    source: str = "",
    author: str = "",
    checked_at: str = "",
    verify_url: str = "",
) -> bytes:
    count = max(len(rows), 1)
    if count <= 8:
        font, leading, pad, desc_limit = 8, 9, 2, 88
    elif count <= 14:
        font, leading, pad, desc_limit = 7, 8, 1.5, 70
    else:
        font, leading, pad, desc_limit = 6, 7, 1, 56

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="HSense classification",
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )
    title = ParagraphStyle(
        "title",
        fontName="Times-Bold",
        fontSize=11,
        leading=13,
        textColor=colors.HexColor("#033591"),
    )
    sub = ParagraphStyle("sub", fontName="Times-Roman", fontSize=7, leading=9, textColor=colors.HexColor("#404040"))
    cell = ParagraphStyle("cell", fontName="Times-Roman", fontSize=font, leading=leading)
    head = ParagraphStyle("head", fontName="Times-Bold", fontSize=font, leading=leading, textColor=colors.white)

    who = author or "Not named"
    when = checked_at or ""
    story = [
        Paragraph("HSense tariff classification", title),
        Spacer(1, 2),
        Paragraph(
            escape(
                f"WCO Harmonized System · SARS Schedule 1 Part 1 · {schedule}. "
                f"Final check: {who}" + (f" · {when}" if when else "")
            ),
            sub,
        ),
    ]
    if source:
        story.append(Paragraph(escape(f"Source: {source}"), sub))
    story.append(Spacer(1, 4))

    header_cells = [
        Paragraph("Description", head),
        Paragraph("HS code", head),
        Paragraph("Check", head),
    ]
    table_rows = [header_cells]
    for row in rows:
        table_rows.append([
            Paragraph(escape(_clip(row.get("description") or "", desc_limit)), cell),
            Paragraph(escape(str(row.get("hs_code") or "")), cell),
            Paragraph(escape(_note(row)), cell),
        ])
    if len(table_rows) == 1:
        table_rows.append([
            Paragraph("No descriptions were classified.", cell),
            Paragraph("", cell),
            Paragraph("", cell),
        ])

    table = Table(table_rows, colWidths=[112 * mm, 32 * mm, 46 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#033591")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#8ea4c4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#e7eef6")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6))

    qr_payload = verify_url or f"HSense final check: {who}"
    qr = seal_qr(qr_payload, LOGO_PATH)
    seal = Image(qr, width=28 * mm, height=28 * mm)
    caption = Paragraph(
        escape(
            f"Scan to authenticate. Final check: {who}."
            + (f" {when}." if when else "")
            + " The LUD mark in the code confirms this sheet."
        ),
        sub,
    )
    footer = Table([[seal, caption]], colWidths=[32 * mm, 158 * mm])
    footer.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(footer)
    document.build(story)
    return buffer.getvalue()
