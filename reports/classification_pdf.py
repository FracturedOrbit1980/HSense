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

    header_cells = [
        Paragraph("Description", head),
        Paragraph("Written", head),
        Paragraph("Recommended", head),
        Paragraph("Explanation", head),
    ]
    table_rows = [header_cells]
    for row in rows:
        flag = row.get("flag") or ""
        if flag == "critical":
            mark = "Critical"
        elif flag == "incorrect":
            mark = "Incorrect"
        elif flag == "ok":
            mark = "Correct"
        else:
            mark = ""
        explanation = row.get("explanation") or row.get("header") or ""
        if mark:
            explanation = f"{mark}. {explanation}"
        table_rows.append([
            Paragraph(escape(str(row.get("description") or "")), cell),
            Paragraph(escape(str(row.get("handwritten_shown") or row.get("handwritten") or "")), cell),
            Paragraph(escape(str(row.get("recommended_label") or row.get("hs_code") or "")), cell),
            Paragraph(escape(str(explanation)), cell),
        ])
    if len(table_rows) == 1:
        table_rows.append([Paragraph("No descriptions were classified.", cell), Paragraph("", cell), Paragraph("", cell), Paragraph("", cell)])

    table = Table(table_rows, colWidths=[42 * mm, 32 * mm, 36 * mm, 68 * mm], repeatRows=1)
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
