import json
import subprocess
import sys
from pathlib import Path

from parsers.universal_extractor import extract_file

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def test_digital_pdf_uses_text_layer():
    extraction = extract_file(SAMPLES / "invoice_digital.pdf")
    assert extraction.route == "digital_pdf"
    by_part = {item.part_number: item for item in extraction.lines}
    assert by_part["CS1900"].description == "Sealing compound - TIN"
    assert by_part["CS1900"].quantity == 10
    assert by_part["ANTI-SEIZE"].quantity == 5
    assert "500g" in by_part["ANTI-SEIZE"].description
    assert by_part["GL-750"].quantity == 8
    assert by_part["HEX-M8"].quantity == 100
    assert by_part["CEM-50"].quantity == 20
    assert by_part["OIL-5L"].quantity == 4


def test_scan_png_is_read_by_ocr():
    extraction = extract_file(SAMPLES / "invoice_scan.png")
    assert extraction.route == "image"
    blob = " ".join(item.description for item in extraction.lines).lower()
    assert "sealing compound" in blob
    assert "anti seize" in blob
    parts = {item.part_number for item in extraction.lines}
    assert "CS1900" in parts
    assert "ANTI-SEIZE" in parts


def test_scanned_pdf_and_rotated_photo():
    scanned = extract_file(SAMPLES / "invoice_scanned.pdf")
    assert scanned.route == "scanned_pdf"
    rotated = extract_file(SAMPLES / "invoice_rotated.png")
    assert rotated.route == "image"
    for extraction in (scanned, rotated):
        by_part = {item.part_number: item for item in extraction.lines}
        assert by_part["CS1900"].quantity == 10
        assert "sealing compound" in by_part["CS1900"].description.lower()
        assert by_part["ANTI-SEIZE"].quantity == 5
        assert by_part["HEX-M8"].quantity == 100


def test_cli_json_for_digital_invoice():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--file_path", str(SAMPLES / "invoice_digital.pdf")],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    rows = json.loads(completed.stdout)
    assert rows[0]["part_number"] == "CS1900"
    assert rows[0]["hs_code"] == "3214.10.00"
    assert rows[0]["duty_rate_general"] == "Free"
    assert rows[0]["quantity"] == 10
    anti = next(row for row in rows if row["part_number"] == "ANTI-SEIZE")
    assert anti["hs_code"] == "3403.99.90"
    assert anti["duty_rate_general"] == "Free"
    glue = next(row for row in rows if row["part_number"] == "GL-750")
    assert glue["hs_code"] == "3506.10.00"
    screw = next(row for row in rows if row["part_number"] == "HEX-M8")
    assert screw["hs_code"] == "7318.15.37"
