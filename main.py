#!/usr/bin/env python3
"""Classify invoice lines from a PDF, an image, or a directory.

Examples
--------
python main.py --file_path samples/invoice_digital.pdf
python main.py --file_path samples/invoice_scan.png --format csv --output audit.csv
python main.py --describe "Anti Seize Compound - 500g" --part-number ANTI-SEIZE --quantity 5
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.tariff_db import TariffDB
from engine.classifier import PUBLIC_FIELDS, WCOClassifier, classify_extracted_lines
from parsers.line_items import _number
from parsers.universal_extractor import extract_file, iter_inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract invoice lines and classify them to 8-digit SARS HS codes."
    )
    parser.add_argument(
        "--file_path",
        help="PDF, image, or directory of documents to classify.",
    )
    parser.add_argument(
        "--describe",
        help="Classify a single description without reading a file.",
    )
    parser.add_argument("--part-number", default=None, help="Part number for --describe.")
    parser.add_argument("--quantity", default=None, help="Quantity for --describe.")
    parser.add_argument(
        "--format",
        choices=("json", "csv", "both"),
        default="json",
        help="Output format. Default: json on stdout.",
    )
    parser.add_argument(
        "--output",
        help="Write the report to this path. With --format both, a sibling CSV/JSON is written too.",
    )
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI for scanned PDFs.")
    parser.add_argument(
        "--db",
        default=None,
        help="Path to sars_tariff_master.db. Built from the bundled schedule if missing.",
    )
    parser.add_argument(
        "--rebuild-db",
        action="store_true",
        help="Rebuild the tariff database from the SARS Schedule 1 PDF before classifying.",
    )
    args = parser.parse_args(argv)

    if not args.file_path and not args.describe:
        parser.error("Provide --file_path or --describe.")

    db_path = Path(args.db) if args.db else None
    if args.rebuild_db:
        from data.build_tariff import DEFAULT_DB, DEFAULT_PDF, build_database

        target = db_path or DEFAULT_DB
        stats = build_database(DEFAULT_PDF, target)
        print(
            f"Rebuilt tariff database: {stats['leaves']} declarable lines.",
            file=sys.stderr,
        )
        db_path = target

    database = TariffDB(db_path)
    classifier = WCOClassifier(database)
    rows: list[dict] = []
    line_number = 1

    if args.describe:
        quantity = _number(args.quantity) if args.quantity is not None else None
        result = classifier.classify(
            args.describe,
            part_number=args.part_number,
            quantity=quantity,
            source_file="manual",
        )
        rows.append(result.as_dict(line_number))
        line_number += 1

    if args.file_path:
        try:
            files = iter_inputs(args.file_path)
        except FileNotFoundError:
            print(f"File not found: {args.file_path}", file=sys.stderr)
            return 2
        if not files:
            print(f"No PDF or image files found in {args.file_path}", file=sys.stderr)
            return 1
        for path in files:
            try:
                extraction = extract_file(path, dpi=args.dpi)
            except (ValueError, FileNotFoundError) as exc:
                print(f"{path}: {exc}", file=sys.stderr)
                if len(files) == 1:
                    return 1
                continue
            print(
                f"{extraction.source_file}: {extraction.route}, {len(extraction.lines)} line(s)",
                file=sys.stderr,
            )
            for warning in extraction.warnings:
                print(f"  warning: {warning}", file=sys.stderr)
            classified = classify_extracted_lines(classifier, extraction.lines, extraction.source_file)
            for row in classified:
                row["line_number"] = line_number
                rows.append(row)
                line_number += 1

    _emit(rows, args.format, args.output)
    database.close()
    return 0


def _emit(rows: list[dict], fmt: str, output: str | None) -> None:
    if output:
        target = Path(output)
        if fmt == "csv" or (fmt == "both" and target.suffix.lower() == ".csv"):
            _write_csv(rows, target if fmt != "both" else _with_suffix(target, ".csv"))
            if fmt == "both":
                _write_json(rows, _with_suffix(target, ".json"))
        elif fmt == "json" or fmt == "both":
            json_path = target if fmt != "both" else _with_suffix(target, ".json")
            _write_json(rows, json_path)
            if fmt == "both":
                _write_csv(rows, _with_suffix(target, ".csv"))
        print(f"Wrote {target}", file=sys.stderr)
        return
    if fmt == "csv":
        _write_csv(rows, None)
        return
    json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if fmt == "both":
        print("Refusing to mix CSV into the JSON stdout stream. Pass --output.", file=sys.stderr)


def _with_suffix(path: Path, suffix: str) -> Path:
    return path.with_suffix(suffix)


def _write_json(rows: list[dict], path: Path) -> None:
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(rows: list[dict], path: Path | None) -> None:
    handle = path.open("w", newline="", encoding="utf-8") if path else sys.stdout
    try:
        writer = csv.DictWriter(handle, fieldnames=list(PUBLIC_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in PUBLIC_FIELDS})
    finally:
        if path is not None:
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
