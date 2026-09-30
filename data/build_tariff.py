"""Build the local SARS Schedule 1 Part 1 tariff database.

The source document is the official ordinary-customs-duty schedule published by
the South African Revenue Service (chapters 1 to 99). Declarable national lines
are stored as 8-digit codes. A 6-digit subheading with no further split is
stored as ``XXXX.XX.00``, which is how that line is declared.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PDF = ROOT / "sources" / "schedule_1_part_1.pdf"
DEFAULT_DB = ROOT / "sars_tariff_master.db"
SOURCE_DATE = "2026-08-28"
SOURCE_TITLE = "SARS Schedule No. 1 Part 1 — Ordinary Customs Duty"

# Tariff codes sit in column 0. Indented "22.03 to 22.06" lines are chapter-note
# cross-references, not schedule rows.
CODE_RE = re.compile(
    r"^((?:\d{4}\.\d{2}\.\d{2})|(?:\d{4}\.\d{2})|(?:\d{4}\.\d)|(?:\d{2}\.\d{2}))(?!\d)\s+(.*)$"
)
RATE_START_RE = re.compile(
    r"^(?:free|\d+(?:[.,]\d+)?%|\d+(?:[.,]\d+)?c/[A-Za-z0-9²]+)",
    re.IGNORECASE,
)
DUTY_GLUE = {"with", "a", "an", "maximum", "max", "of", "or", "plus", "per", "cent", "less"}
UNIT_RE = re.compile(
    r"^(?:kg|u|li|l|m²|m2|m³|m3|t|2u|pr|100u|1000u|gi|m|carat|m³/101\.3kP|m3/101\.3kP)$",
    re.IGNORECASE,
)
RATE_WORD_RE = re.compile(
    r"^(?:free|\d+(?:[.,]\d+)?%|\d+(?:[.,]\d+)?c/[A-Za-z0-9²]+|or)$",
    re.IGNORECASE,
)
CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+(\d+)\s*$", re.IGNORECASE)
NOTE_RE = re.compile(
    r"^\s*(NOTES?|SUB-?HEADING NOTES?|ADDITIONAL NOTES?)\s*:",
    re.IGNORECASE,
)
OTHER_RE = re.compile(r"^other\s*:?\s*$", re.IGNORECASE)


@dataclass
class TariffNode:
    raw_code: str
    chapter: str
    check_digit: str | None
    level: int
    description: str
    statistical_unit: str | None = None
    duty_cols: list[str] = field(default_factory=list)
    ancestors: list[TariffNode] = field(default_factory=list)

    @property
    def digits(self) -> str:
        return self.raw_code.replace(".", "")


def pdf_to_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(f"SARS tariff PDF not found: {pdf_path}")
    cache = pdf_path.with_suffix(".txt")
    if cache.exists() and cache.stat().st_mtime >= pdf_path.stat().st_mtime:
        return cache.read_text(encoding="utf-8", errors="replace")
    subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), str(cache)],
        check=True,
        capture_output=True,
    )
    return cache.read_text(encoding="utf-8", errors="replace")


def is_chrome(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("Date:"):
        return True
    if "SCHEDULE 1" in stripped and "Customs" in stripped:
        return True
    if stripped.startswith("Heading /") or stripped.startswith("Subheading"):
        return True
    if "Rate of Duty" in stripped and "General" in stripped:
        return True
    if stripped in {"Customs & Excise Tariff"}:
        return True
    if re.fullmatch(r"\d{1,3}", stripped):
        return True
    return False


def _tokens(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"\S+", text))


def split_desc_and_rates(text: str) -> tuple[str, str | None, list[str]]:
    """Split a tariff row fragment into description, unit, and duty columns.

    The statistical unit is the last unit token immediately followed by a duty
    (``free``, ``10%``, ``1,8c/kg``). Words such as ``with a maximum of`` belong
    to the duty, not the description, so the duty side is not limited to a
    single token.
    """
    tokens = _tokens(text)
    chosen: re.Match[str] | None = None
    rate_from = 0
    for index, token in enumerate(tokens[:-1]):
        if not UNIT_RE.match(token.group()):
            continue
        nxt = index + 1
        # "u (jue/pack)" keeps a parenthetical note in the unit column.
        if tokens[nxt].group().startswith("(") and nxt + 1 < len(tokens):
            nxt += 1
        if RATE_START_RE.match(tokens[nxt].group()):
            chosen = token
            rate_from = tokens[nxt].start()
    if chosen is None:
        return text.strip(), None, []
    description = text[: chosen.start()].strip()
    rate_text = text[rate_from:].strip()
    columns = [part.strip() for part in re.split(r"\s{2,}", rate_text) if part.strip()]
    return description, chosen.group(), columns


def is_duty_fragment(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    for token in tokens:
        if RATE_WORD_RE.match(token) or RATE_START_RE.match(token):
            continue
        if token.lower().strip(",;") in DUTY_GLUE:
            continue
        if re.fullmatch(r"\d+(?:[.,]\d+)?%?", token):
            continue
        return False
    return True


def _first_column(text: str) -> str:
    return re.split(r"\s{2,}", text.strip(), maxsplit=1)[0].strip()


def split_description_and_duty_continuation(line: str) -> tuple[str, str]:
    """Separate a wrapped description from a right-aligned duty continuation.

    Returns ``(description, duty_text)``. Pure duty lines have an empty
    description. Ordinary description wraps have empty duty text.
    """
    for match in re.finditer(r"\s{3,}", line):
        left = line[: match.start()].strip()
        right = line[match.end() :].strip()
        if not right or not is_duty_fragment(right):
            continue
        if left and not is_duty_fragment(left):
            return left, right
    if is_duty_fragment(line):
        return "", line.strip()
    return line.strip(), ""


def duty_incomplete(cell: str) -> bool:
    if not cell or not cell.strip():
        return True
    last = cell.split()[-1].lower().strip(",;")
    return last in DUTY_GLUE


def _should_extend_duty(general: str, fragment: str) -> bool:
    """Continue a wrapped general-rate cell without absorbing the next column.

    ``450c/kg`` followed by ``with a maximum of 96%`` is still the general
    rate. Once that phrase is complete, a later ``of 6%`` is another column.
    """
    if not general or duty_incomplete(general):
        return True
    if general.lower() == "free":
        return False
    first = fragment.split()[0].lower().strip(",;")
    return first in {"with", "less", "plus", "or"}


def normalize_duty(cell: str | None) -> str | None:
    if cell is None:
        return None
    text = re.sub(r"\s+", " ", cell).strip()
    if not text:
        return None
    if text.lower() == "free":
        return "Free"
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    return text


def _append_description(existing: str, extra: str) -> str:
    extra = extra.strip()
    if not extra:
        return existing
    if existing.endswith("-") and extra[:1].islower():
        return existing[:-1] + extra
    if not existing:
        return extra
    return f"{existing} {extra}"


def _level_for(raw_code: str, dashes: str | None) -> int:
    if dashes:
        return len(dashes)
    digits = raw_code.replace(".", "")
    if len(digits) <= 4:
        return 0
    if len(digits) == 5:
        return 1
    if len(digits) == 6:
        return 1
    return 2


def parse_schedule(text: str) -> tuple[list[TariffNode], dict[str, dict[str, str]]]:
    nodes: list[TariffNode] = []
    chapters: dict[str, dict[str, str]] = {}
    current: TariffNode | None = None
    chapter: str | None = None
    mode: str | None = None
    title_parts: list[str] = []
    note_parts: list[str] = []

    def flush() -> None:
        nonlocal current
        if current is not None:
            current.description = clean_description(current.description)
            nodes.append(current)
            current = None

    def close_chapter_text() -> None:
        nonlocal title_parts, note_parts
        if chapter is None:
            title_parts = []
            note_parts = []
            return
        record = chapters.setdefault(chapter, {"title": "", "notes": ""})
        if title_parts and not record["title"]:
            record["title"] = clean_description(" ".join(title_parts))
        if note_parts:
            joined = clean_description(" ".join(note_parts))
            record["notes"] = f"{record['notes']} {joined}".strip() if record["notes"] else joined
        title_parts = []
        note_parts = []

    for raw in text.splitlines():
        line = raw.replace("\f", "").rstrip()
        if CHAPTER_RE.match(line):
            flush()
            close_chapter_text()
            chapter = CHAPTER_RE.match(line).group(1).zfill(2)  # type: ignore[union-attr]
            chapters.setdefault(chapter, {"title": "", "notes": ""})
            mode = "title"
            continue
        if is_chrome(line):
            continue
        if NOTE_RE.match(line):
            flush()
            if mode == "title":
                close_chapter_text()
            mode = "notes"
            note_parts.append(line.strip())
            continue

        matched = CODE_RE.match(line)
        if matched and mode in {None, "title", "notes", "body"}:
            if mode in {"title", "notes"}:
                close_chapter_text()
            mode = "body"
            flush()
            raw_code, rest = matched.group(1), matched.group(2)
            node_chapter = raw_code.replace(".", "")[:2]
            check_digit = None
            dashes = None
            body = rest.strip()
            cd_match = re.match(r"^(\d)\s+(-{1,4})?\s*(.*)$", body)
            # A digit followed by HS dashes is the check-digit column. Duty text
            # may still read "1,8c/kg with a maximum of 15%", so dashes alone are
            # enough. Rows without dashes must actually reach a duty rate.
            if cd_match and (cd_match.group(2) or _looks_like_check_digit_row(cd_match.group(3))):
                check_digit = cd_match.group(1)
                dashes = cd_match.group(2)
                body = cd_match.group(3).strip()
            else:
                dash_match = re.match(r"^(-{1,4})\s+(.*)$", body)
                if dash_match:
                    dashes = dash_match.group(1)
                    body = dash_match.group(2).strip()
            description, unit, columns = split_desc_and_rates(body)
            # Drop a leading dash leftover on heading rows that also carry rates.
            description = re.sub(r"^-{1,4}\s+", "", description).strip()
            current = TariffNode(
                raw_code=raw_code,
                chapter=node_chapter,
                check_digit=check_digit,
                level=_level_for(raw_code, dashes),
                description=description,
                statistical_unit=unit,
                duty_cols=columns,
            )
            continue

        if mode == "title":
            if line.strip():
                title_parts.append(line.strip())
            continue
        if mode == "notes":
            if line.strip():
                note_parts.append(line.strip())
            continue
        if current is not None and line.strip():
            left, right = split_description_and_duty_continuation(line)
            if right:
                fragment = _first_column(right)
                if fragment:
                    general = current.duty_cols[0] if current.duty_cols else ""
                    if not current.duty_cols:
                        current.duty_cols = [fragment]
                    elif _should_extend_duty(general, fragment):
                        current.duty_cols[0] = re.sub(
                            r"\s+", " ", f"{current.duty_cols[0]} {fragment}"
                        ).strip()
            if left:
                current.description = _append_description(current.description, left)

    flush()
    close_chapter_text()
    _assign_ancestors(nodes)
    return nodes, chapters


def _looks_like_check_digit_row(body: str) -> bool:
    """A single digit after the code is the check digit only on real tariff rows.

    Heading rows such as ``01.01 Live horses...`` must not treat the first digit
    of a quantity or the word itself as a check digit. Rows with a check digit
    either start with HS dashes or reach a statistical unit and duty rates.
    """
    if re.match(r"^-{1,4}\s+", body):
        return True
    _, unit, columns = split_desc_and_rates(body)
    return bool(unit and columns)


def clean_description(text: str) -> str:
    text = text.replace("—", " ").replace("–", "-")
    text = re.sub(r"\s+", " ", text).strip(" ;")
    return text


def _assign_ancestors(nodes: list[TariffNode]) -> None:
    """Parent links follow the code itself, not the printed dash count.

    SARS restarts dashes under each split, so a one-dash national line can sit
    under a six-digit heading that has no dashes of its own. A code is a child
    when its digits extend the nearest open code.
    """
    stack: list[TariffNode] = []
    for node in nodes:
        digits = node.digits
        while stack and not (digits.startswith(stack[-1].digits) and len(digits) > len(stack[-1].digits)):
            stack.pop()
        node.ancestors = list(stack)
        node.level = len(stack)
        stack.append(node)


def _significant(text: str) -> bool:
    return bool(text) and not OTHER_RE.match(text.strip())


def legal_path(node: TariffNode) -> str:
    parts: list[str] = []
    for ancestor in node.ancestors:
        if _significant(ancestor.description):
            parts.append(ancestor.description.rstrip(":"))
    if _significant(node.description) or not parts:
        if node.description:
            parts.append(node.description.rstrip(":"))
    # De-duplicate adjacent repeats ("Other" parents already removed).
    collapsed: list[str] = []
    for part in parts:
        if not collapsed or collapsed[-1] != part:
            collapsed.append(part)
    return " | ".join(collapsed)


def heading_digits(node: TariffNode) -> str:
    if node.ancestors:
        return node.ancestors[0].digits[:4]
    return node.digits[:4]


def is_extended_by_later(nodes: list[TariffNode]) -> set[int]:
    """Indexes of nodes that have a more specific descendant code."""
    parents: set[int] = set()
    digits_list = [node.digits for node in nodes]
    for index, digits in enumerate(digits_list):
        for later in digits_list[index + 1 :]:
            if later.startswith(digits) and len(later) > len(digits):
                parents.add(index)
                break
            if not later.startswith(digits[:4]):
                break
    return parents


def to_eight_digit(node: TariffNode) -> str | None:
    digits = node.digits
    if len(digits) == 6:
        return f"{digits[:4]}.{digits[4:6]}.00"
    if len(digits) == 8:
        return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"
    return None


def column(values: list[str], index: int) -> str | None:
    if index >= len(values):
        return None
    return normalize_duty(values[index])


def build_database(pdf_path: Path = DEFAULT_PDF, db_path: Path = DEFAULT_DB) -> dict[str, int]:
    text = pdf_to_text(pdf_path)
    nodes, chapters = parse_schedule(text)
    parents = is_extended_by_later(nodes)

    if db_path.exists():
        db_path.unlink()
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE chapters (
            chapter TEXT PRIMARY KEY,
            title TEXT,
            notes TEXT
        );
        CREATE TABLE tariff_lines (
            id INTEGER PRIMARY KEY,
            hs_code TEXT,
            raw_code TEXT NOT NULL,
            digits TEXT NOT NULL,
            check_digit TEXT,
            chapter TEXT NOT NULL,
            heading TEXT NOT NULL,
            description TEXT NOT NULL,
            legal_path TEXT NOT NULL,
            search_text TEXT NOT NULL,
            statistical_unit TEXT,
            duty_general TEXT,
            duty_eu_uk TEXT,
            duty_efta TEXT,
            duty_sadc TEXT,
            duty_mercosur TEXT,
            duty_afcfta TEXT,
            is_leaf INTEGER NOT NULL,
            level INTEGER NOT NULL
        );
        CREATE VIRTUAL TABLE tariff_fts USING fts5(
            hs_code UNINDEXED,
            search_text,
            tokenize = 'porter unicode61'
        );
        """
    )

    leaf_count = 0
    unknown_duty = 0
    for index, node in enumerate(nodes):
        leaf = node.check_digit is not None and index not in parents and len(node.digits) >= 6
        hs_code = to_eight_digit(node) if leaf else None
        if leaf and hs_code is None:
            leaf = False
        path = legal_path(node)
        search = path or node.description
        duty_general = column(node.duty_cols, 0) if leaf else None
        if leaf and not duty_general:
            unknown_duty += 1
            duty_general = "Unknown"
        if leaf:
            leaf_count += 1
        connection.execute(
            """
            INSERT INTO tariff_lines (
                hs_code, raw_code, digits, check_digit, chapter, heading, description,
                legal_path, search_text, statistical_unit, duty_general, duty_eu_uk,
                duty_efta, duty_sadc, duty_mercosur, duty_afcfta, is_leaf, level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hs_code,
                node.raw_code,
                node.digits,
                node.check_digit,
                node.chapter,
                heading_digits(node),
                node.description,
                path,
                search,
                node.statistical_unit,
                duty_general,
                column(node.duty_cols, 1) if leaf else None,
                column(node.duty_cols, 2) if leaf else None,
                column(node.duty_cols, 3) if leaf else None,
                column(node.duty_cols, 4) if leaf else None,
                column(node.duty_cols, 5) if leaf else None,
                1 if leaf else 0,
                node.level,
            ),
        )
        if leaf and hs_code:
            connection.execute(
                "INSERT INTO tariff_fts (hs_code, search_text) VALUES (?, ?)",
                (hs_code, search),
            )

    for number, record in chapters.items():
        connection.execute(
            "INSERT OR REPLACE INTO chapters (chapter, title, notes) VALUES (?, ?, ?)",
            (number, record.get("title") or "", record.get("notes") or ""),
        )

    connection.executemany(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        [
            ("source_title", SOURCE_TITLE),
            ("source_date", SOURCE_DATE),
            ("source_file", pdf_path.name),
            ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            ("leaf_count", str(leaf_count)),
            ("chapter_count", str(len(chapters))),
        ],
    )
    connection.execute("CREATE INDEX idx_tariff_heading ON tariff_lines (heading, is_leaf)")
    connection.execute("CREATE INDEX idx_tariff_hs ON tariff_lines (hs_code)")
    connection.execute("CREATE INDEX idx_tariff_digits ON tariff_lines (digits)")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.commit()
    connection.close()
    return {
        "nodes": len(nodes),
        "leaves": leaf_count,
        "chapters": len(chapters),
        "unknown_duty": unknown_duty,
    }


def main() -> None:
    stats = build_database()
    print(
        f"Built {DEFAULT_DB.name}: {stats['leaves']} declarable 8-digit lines, "
        f"{stats['chapters']} chapters, {stats['nodes']} schedule rows, "
        f"{stats['unknown_duty']} leaves without a parsed general rate."
    )


if __name__ == "__main__":
    main()
