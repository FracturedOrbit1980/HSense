"""PDF of classified descriptions: heading, description, and HS code."""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def classification_pdf(
    rows: list[dict],
    *,
    schedule: str,
    source: str = "",
) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="HSense classification",
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    title = ParagraphStyle(
        "title",
        fontName="Times-Bold",
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1f4e79"),
    )
    sub = ParagraphStyle("sub", fontName="Times-Roman", fontSize=10, leading=13, textColor=colors.HexColor("#3d4c5c"))
    cell = ParagraphStyle("cell", fontName="Times-Roman", fontSize=9, leading=12)
    head = ParagraphStyle("head", fontName="Times-Bold", fontSize=9, leading=12, textColor=colors.white)

    story = [
        Paragraph("HSense tariff classification", title),
        Spacer(1, 4),
        Paragraph(escape(f"SARS Schedule 1 Part 1, {schedule}"), sub),
    ]
    if source:
        story.append(Paragraph(escape(f"Source: {source}"), sub))
    story.append(Paragraph(escape(f"{len(rows)} description{'s' if len(rows) != 1 else ''}"), sub))
    story.append(Spacer(1, 10))

    written = any(row.get("handwritten") for row in rows)
    header_cells = [
        Paragraph("Header", head),
        Paragraph("Description", head),
        Paragraph("HS code", head),
    ]
    if written:
        header_cells.extend([Paragraph("Handwritten", head), Paragraph("Check", head)])
    table_rows = [header_cells]
    for row in rows:
        cells = [
            Paragraph(escape(str(row.get("header") or "")), cell),
            Paragraph(escape(str(row.get("description") or "")), cell),
            Paragraph(escape(str(row.get("hs_code") or "")), cell),
        ]
        if written:
            mark = "Incorrect" if row.get("flag") == "incorrect" else ""
            cells.append(Paragraph(escape(str(row.get("handwritten_shown") or "")), cell))
            cells.append(Paragraph(escape(mark), cell))
        table_rows.append(cells)
    if len(table_rows) == 1:
        table_rows.append([Paragraph("", cell), Paragraph("No descriptions were classified.", cell), Paragraph("", cell)])

    widths = [52 * mm, 62 * mm, 28 * mm, 24 * mm, 22 * mm] if written else [70 * mm, 78 * mm, 28 * mm]
    table = Table(table_rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8aa0b8")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fb")]),
            ]
        )
    )
    story.append(table)
    document.build(story)
    return buffer.getvalue()
