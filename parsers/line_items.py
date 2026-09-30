"""Turn invoice text or a table into product lines.

Quantities are the order quantity, not the pack size printed in the
description. ``Anti Seize Compound - 500g`` with a quantity of 5 stays
quantity 5; the 500 g remains part of the description so the adhesive and
lubricant rules can still see the pack mass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
PART_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-/_.]{1,24}$")
UNIT_WORDS = {
    "kg", "kgs", "g", "gr", "mg", "ml", "l", "mm", "cm", "m", "ea", "each",
    "pcs", "pc", "set", "tin", "bag", "box", "unit", "units",
}
MEASURE_UNITS = {"kg", "kgs", "g", "gr", "mg", "ml", "l", "mm", "cm", "m"}
SKIP_RE = re.compile(
    r"(^date\b|^page\b|^tel\b|^fax\b|^attn\b)|"
    r"\b(subtotal|grand total|^total\b|vat\b|tax invoice|invoice no|invoice number|"
    r"bill to|ship to|sold to|customer|supplier|telephone|phone|email|e-mail|"
    r"swift|iban|bank|page \d|pty\b|ltd\b|limited|street|avenue|road|p\.?o\.? box|"
    r"commercial invoice|tax invoice|amount due|balance due|currency|payment terms|"
    r"incoterms?|delivery address)\b",
    re.IGNORECASE,
)
HEADER_KEYS = ("description", "qty", "quantity", "part no", "part number", "sku")
_DESCRIPTION_LABEL = re.compile(
    r"\b(description|line description|goods description|item description)\b",
    re.IGNORECASE,
)
_COLUMN_LABELS = (
    ("part", re.compile(r"\b(part\s*(?:no\.?|number|#)?|sku|item\s*code|product\s*code)\b", re.IGNORECASE)),
    ("description", re.compile(r"\b(description|goods|line\s*description)\b", re.IGNORECASE)),
    ("quantity", re.compile(r"\b(qty|quantity)\b", re.IGNORECASE)),
)


@dataclass
class LineItem:
    part_number: str | None
    description: str
    quantity: int | float | None
    raw_text: str
    page: int | None = None


_LIST_MARK = re.compile(r"^(?:\d{1,3}[\.\)]\s+|[-*•]\s+)")


def collect_descriptions(text: str) -> list[str]:
    """Descriptions to classify.

    When the text has a Description column header, only the cells under that
    header are returned. A paste with no header is treated as one description
    per line.
    """
    under_header = rows_below_description_header(text)
    if under_header is not None:
        found: list[str] = []
        known: set[str] = set()
        for item in under_header:
            _add_description(found, known, item.description)
        return found

    found = []
    known = set()
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _LIST_MARK.sub("", " ".join(raw.split())).strip(" ;")
        if len(line) < 3 or is_header_line(line) or _skip_line(line):
            continue
        if not _valid_description(line):
            continue
        _add_description(found, known, line)
    return found


def rows_below_description_header(text: str) -> list[LineItem] | None:
    """Product rows that sit under a Description column. None if no such header."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header_index = None
    for index, line in enumerate(lines):
        if _is_description_header(line):
            header_index = index
            break
    if header_index is None:
        return None

    spans = _column_spans(lines[header_index])
    items: list[LineItem] = []
    blank_run = 0
    for raw in lines[header_index + 1 :]:
        if not raw.strip():
            blank_run += 1
            if items and blank_run >= 2:
                break
            continue
        blank_run = 0
        if _skip_line(raw):
            if items:
                break
            continue
        if is_header_line(raw) or _is_description_header(raw):
            continue
        item = _item_under_header(raw, spans)
        if item is not None:
            items.append(item)
    return items


def _is_description_header(line: str) -> bool:
    compact = " ".join(line.split())
    if not compact or not _DESCRIPTION_LABEL.search(compact):
        return False
    if is_header_line(compact):
        return True
    return bool(
        re.fullmatch(
            r"(item |line |goods |product )?descriptions?",
            compact,
            re.IGNORECASE,
        )
    )


def _column_spans(header: str) -> dict[str, int]:
    found: list[tuple[int, str]] = []
    for name, pattern in _COLUMN_LABELS:
        match = pattern.search(header)
        if match:
            found.append((match.start(), name))
    found.sort()
    spans: dict[str, int] = {}
    for index, (start, name) in enumerate(found):
        if name in spans:
            continue
        spans[name] = start
        if index + 1 < len(found):
            spans[f"after_{name}"] = found[index + 1][0]
    return spans


def _item_under_header(raw: str, spans: dict[str, int]) -> LineItem | None:
    aligned = _item_from_aligned_row(raw, spans)
    if aligned is not None:
        return aligned
    parsed = parse_free_text_line(raw)
    if parsed is not None:
        return parsed
    line = _LIST_MARK.sub("", " ".join(raw.split())).strip(" ;")
    if len(line) < 3 or not _valid_description(line) or _skip_line(line) or is_header_line(line):
        return None
    return LineItem(None, line, None, raw)


def _item_from_aligned_row(raw: str, spans: dict[str, int]) -> LineItem | None:
    start = spans.get("description")
    if start is None or len(raw) <= start:
        return None
    if start > 0 and raw[start - 1].isalnum():
        return None
    end = spans.get("after_description")
    chunk = raw[start:end] if end else raw[start:]
    description = " ".join(chunk.split()).strip(" -")
    if not _valid_description(description) or _skip_line(description):
        return None
    part = None
    part_at = spans.get("part")
    if part_at is not None and part_at < len(raw):
        part_end = spans.get("after_part", start)
        part_text = raw[part_at:part_end].strip()
        token = part_text.split()[0] if part_text else ""
        if token and _looks_like_part(token):
            part = token.upper()
    quantity = None
    qty_at = spans.get("quantity")
    if qty_at is not None and qty_at < len(raw):
        qty_text = raw[qty_at:].strip().split()
        quantity = _number(qty_text[0]) if qty_text else None
    return LineItem(part, description, quantity, raw)


def _add_description(found: list[str], known: set[str], description: str) -> None:
    text = " ".join(description.split()).strip(" ;")
    norm = _norm(text)
    if not norm or not _valid_description(text):
        return
    if any(norm == existing or existing in norm or norm in existing for existing in known):
        return
    known.add(norm)
    found.append(text)


def parse_document_text(text: str, page: int | None = None) -> list[LineItem]:
    under_header = rows_below_description_header(text)
    if under_header is not None:
        items: list[LineItem] = []
        seen: set[tuple[str, str]] = set()
        for item in under_header:
            item.page = page
            key = ((item.part_number or "").upper(), _norm(item.description))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
        return items

    items = []
    seen = set()
    for raw_line in text.splitlines():
        item = parse_free_text_line(raw_line)
        if item is None:
            continue
        item.page = page
        key = ((item.part_number or "").upper(), _norm(item.description))
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def parse_tables(tables: list[list[list[str | None]]], page: int | None = None) -> list[LineItem]:
    items: list[LineItem] = []
    seen: set[tuple[str, str]] = set()
    for table in tables:
        for item in _parse_table(table):
            item.page = page
            key = ((item.part_number or "").upper(), _norm(item.description))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def parse_free_text_line(line: str) -> LineItem | None:
    raw = " ".join(line.replace("|", " ").replace("\t", " ").split())
    if len(raw) < 5 or is_header_line(raw) or _skip_line(raw):
        return None

    multiplied = re.match(
        r"^(?P<qty>\d+(?:[.,]\d+)?)\s*[x×]\s+(?P<body>.+)$",
        raw,
        re.IGNORECASE,
    )
    if multiplied:
        body = multiplied.group("body").strip()
        part, description = _split_part(body)
        if not _valid_description(description):
            return None
        return LineItem(part, description, _number(multiplied.group("qty")), raw)

    tokens = raw.split()
    if tokens and tokens[0].isdigit() and int(tokens[0]) < 500 and len(tokens) >= 3:
        tokens = tokens[1:]
    if len(tokens) >= 2 and tokens[-2].lower() in {"qty", "quantity"} and NUMBER_RE.match(tokens[-1]):
        quantity = _number(tokens[-1])
        tokens = tokens[:-2]
    else:
        quantity = None
        if tokens and _is_bare_quantity(tokens):
            quantity = _number(tokens[-1])
            tokens = tokens[:-1]

    if not tokens:
        return None
    part, tokens = _take_part(tokens)
    description = " ".join(tokens).strip(" -")
    if not _valid_description(description):
        return None
    if quantity is None and part is None and not re.search(r"\d", raw):
        return None
    return LineItem(part, description, quantity, raw)


def is_header_line(line: str) -> bool:
    lowered = line.lower()
    hits = sum(key in lowered for key in HEADER_KEYS)
    return hits >= 2


def _parse_table(table: list[list[str | None]]) -> list[LineItem]:
    rows = [[_cell(cell) for cell in row] for row in table if row]
    rows = [row for row in rows if any(row)]
    if len(rows) < 2:
        return []
    header_at = None
    for index, row in enumerate(rows[:5]):
        if is_header_line(" ".join(row)):
            header_at = index
            break
    if header_at is None:
        return []
    columns = _map_columns(rows[header_at])
    if "description" not in columns:
        return []
    items: list[LineItem] = []
    for row in rows[header_at + 1 :]:
        description = _at(row, columns.get("description"))
        if not description or is_header_line(description) or _skip_line(description):
            continue
        if not _valid_description(description):
            continue
        part = _at(row, columns.get("part")) or None
        if part and not _looks_like_part(part):
            part = None
        quantity = _number(_at(row, columns.get("quantity")))
        items.append(
            LineItem(part, description, quantity, " | ".join(cell for cell in row if cell))
        )
    return items


def _map_columns(header: list[str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for index, name in enumerate(header):
        lowered = name.lower()
        if any(key in lowered for key in ("part no", "part number", "part #", "sku", "item code", "product code")):
            columns["part"] = index
        elif "part" in lowered and "part" not in columns:
            columns["part"] = index
        elif "description" in lowered or lowered in {"goods", "product", "line description"}:
            columns["description"] = index
        elif "qty" in lowered or "quantity" in lowered:
            columns["quantity"] = index
    return columns


def _split_part(text: str) -> tuple[str | None, str]:
    part, tokens = _take_part(text.split())
    return part, " ".join(tokens).strip()


def _looks_like_part(token: str) -> bool:
    candidate = token.upper()
    if not PART_RE.match(candidate):
        return False
    if candidate.lower() in UNIT_WORDS:
        return False
    has_digit = any(character.isdigit() for character in candidate)
    has_separator = any(character in candidate for character in "-/_")
    return has_digit or has_separator


def _take_part(tokens: list[str]) -> tuple[str | None, list[str]]:
    if not tokens:
        return None, tokens
    if len(tokens) >= 2 and tokens[1].startswith("-"):
        joined = tokens[0] + tokens[1]
        if _looks_like_part(joined):
            return joined.upper(), tokens[2:]
    if _looks_like_part(tokens[0]):
        return tokens[0].upper(), tokens[1:]
    return None, tokens


def _is_bare_quantity(tokens: list[str]) -> bool:
    """A trailing integer is the order quantity, not a pack mass such as ``50 kg``."""
    if not NUMBER_RE.match(tokens[-1]):
        return False
    if len(tokens) >= 2 and tokens[-2].lower() in MEASURE_UNITS:
        return False
    return True


def _valid_description(description: str) -> bool:
    return re.search(r"[A-Za-z]{3,}", description or "") is not None


def _skip_line(line: str) -> bool:
    if re.fullmatch(r"[\W_]+", line):
        return True
    if SKIP_RE.search(line):
        return True
    return False


def _number(value: str | None) -> int | float | None:
    if not value:
        return None
    text = value.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        text = text.replace(",", "")
    elif "," in text and "." not in text:
        text = text.replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    number = float(text)
    if number.is_integer():
        return int(number)
    return number


def _cell(value: str | None) -> str:
    return " ".join((value or "").split())


def _at(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()
