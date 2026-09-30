# HS document intake and SARS tariff classification

This tool reads a commercial invoice from a digital PDF, a scanned PDF, or a photograph and classifies each product line to an 8-digit South African tariff code.

It is built for the ordinary-customs-duty schedule (SARS Schedule No. 1 Part 1), not a shortened prompt list. The legal wording of chapters 01 to 99 is stored in a local SQLite database and searched there. A small set of WCO heading rules handles the categories that invoices describe in trade language rather than in tariff language: anti-seize, mastics, and retail glues.

## What you get

Each line is returned as JSON (or CSV) with:

`line_number`, `source_file`, `part_number`, `description`, `quantity`, `hs_code`, `duty_rate_general`, `wco_reasoning`

```bash
python main.py --file_path samples/invoice_digital.pdf
```

```json
{
  "line_number": 1,
  "source_file": "invoice_digital.pdf",
  "part_number": "CS1900",
  "description": "Sealing compound - TIN",
  "quantity": 10,
  "hs_code": "3214.10.00",
  "duty_rate_general": "Free",
  "wco_reasoning": "Classified under 3214.10.00 as a mastic or sealing compound. GRI 1: heading 32.14 covers glaziers' putty, resin cements, caulking compounds and other mastics..."
}
```

## Install

System packages used for scans:

- `tesseract-ocr` and `tesseract-ocr-eng` (and `tesseract-ocr-osd` if you want automatic rotation)
- `poppler-utils` (`pdftotext` rebuilds the tariff database; `pdf2image` renders scanned pages)

```bash
pip install -r requirements.txt
python -m pytest
python main.py --file_path samples/invoice_scan.png
```

The database file `data/sars_tariff_master.db` is already built. To rebuild it from the bundled schedule:

```bash
python -m data.build_tariff
```

## How a file is read

| Input | Route |
| --- | --- |
| PDF with a text layer | `pdfplumber`, with `pypdf` if pdfplumber cannot open the file |
| Scanned PDF | pages rendered with `pdf2image` (PyMuPDF if Poppler fails), then the image path |
| `.jpg`, `.jpeg`, `.png`, `.webp`, `.tif`, `.tiff`, `.bmp`, `.heic` | EXIF orientation, OSD rotation, deskew, denoise, contrast, then Tesseract |

Pack size stays in the description. `Anti Seize Compound - 500g` with a quantity column of 5 is quantity **5**, not 500. The 500 g is still visible to the glue and lubricant rules.

Set `HS_OCR_BACKEND=vision` or `auto` and `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) to transcribe a page with Gemini Flash instead of Tesseract. The model is asked only to read the page. Classification still happens locally against the tariff database. The default backend is Tesseract, so no API key is required.

## How a code is chosen

1. **Keyword rules (GRI 1 and GRI 3(a)).** These fire before search:
   - Anti-seize, grease, cutting oil, thread lubricant, friction reducer → **heading 34.03**. A plain anti-seize paste is **3403.99.90**. It is a lubricating preparation (bolt or nut release), not a mastic of 32.14.
   - Sealing compound, sealant, caulk, putty, resin cement, mastic → **3214.10.00**. Subheading 3214.10 names those goods. Residual **3214.90** is for other non-refractory surfacing preparations.
   - Bituminous or asphalt mastic → **2715.00.20**, because Chapter 32 Note 1(c) excludes it from 32.14.
   - Prepared glue or adhesive put up at 1 kg or less → **3506.10.00**. A polymer adhesive above 1 kg → **3506.91.00**.
   - Mechanical, oil, or shaft seals → **8484.20.00**, not 32.14.
   - Engine, motor, or gear oil → **heading 27.10**. Heading 34.03 excludes oils that are 70% or more petroleum.
   - Portland cement → **2523.29.00**.
2. **Lexical search** over the declarable lines. Tokens from the invoice are matched to the official heading and subheading text. A subheading that adds conditions the invoice never stated (for example "white" cement, or a screen above 45 cm) loses to the residual line in that heading.

Duty in `duty_rate_general` is the **General** column of Schedule 1 Part 1 dated **28 August 2026**. Preferential EU, SADC, and AfCFTA rates are stored in the database but are not the rate returned on the audit line.

On that schedule, 3214.10, 3214.90, 3403.99.90, and 3506.10 are all **Free**. A sealing compound is therefore not reported at 10%, and it is reported at 3214.10.00 rather than the residual 3214.90.00, because the subheading text names mastics and caulking compounds.

## Run it in a browser

GitHub stores the source. It does not host the classifier. On your computer:

```bash
pip install -r requirements.txt
python web.py
```

Then open [HSense](http://127.0.0.1:43123). Upload an invoice or paste text. Each line shows the written code, the recommended code, and a short explanation. A handwritten `"` repeats the line above. A mismatch is marked Incorrect. A cosmetics code on these goods is marked Critical.

## Commands

```bash
python main.py --file_path samples/invoice_digital.pdf --format both --output audit.json
python main.py --file_path samples/ --format csv --output batch.csv
python main.py --describe "Anti Seize Compound - 500g" --part-number ANTI-SEIZE --quantity 5
python main.py --rebuild-db --describe "Sealing compound - TIN"
```

`--file_path` accepts one document or a directory. JSON is written to stdout unless `--output` is set. Progress and the route (`digital_pdf`, `scanned_pdf`, or `image`) go to stderr.

## Layout

- `utils/image_preprocessor.py` — orientation, deskew, contrast, PDF page rendering
- `parsers/universal_extractor.py` — file-type routing and OCR
- `parsers/line_items.py` — part number, description, quantity
- `data/build_tariff.py` — parses the SARS PDF into SQLite
- `data/tariff_db.py` — query API over `data/sars_tariff_master.db`
- `engine/keyword_rules.py` — the heading rules above
- `engine/classifier.py` — GRI reasoning and 8-digit selection
- `main.py` — CLI
- `web.py` — browser form, and a PDF of header, description, and HS code
- `reports/classification_pdf.py` — that PDF

## Source

The tariff text is SARS Schedule No. 1 Part 1, ordinary customs duty, chapters 1 to 99, dated 28 August 2026, saved at `data/sources/schedule_1_part_1.pdf`. Chapter 77 is reserved and is not in the schedule. Declarable 6-digit subheadings that South Africa does not split further are stored as `XXXX.XX.00`.

This is a classification aid. The reasoning cites the heading terms so a person can check the line before it is used on a declaration.
