"""SQLite lookup over the SARS 8-digit tariff.

The database is built from Schedule 1 Part 1. Search is lexical: an inverted
index over the legal wording, with FTS5 available for audit queries. The
classifier, not this module, applies the WCO rules.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from engine.textutil import tokenize

DB_PATH = Path(__file__).resolve().parent / "sars_tariff_master.db"


@dataclass(frozen=True)
class TariffLine:
    hs_code: str
    heading: str
    chapter: str
    description: str
    legal_path: str
    search_text: str
    duty_general: str
    tokens: frozenset[str]
    specific_tokens: frozenset[str]
    nearest_tokens: frozenset[str]


def _nearest_tokens(legal_path: str) -> frozenset[str]:
    """Tokens of the most specific path segment that still says something."""
    for part in reversed((legal_path or "").split("|")):
        tokens = frozenset(tokenize(part))
        if tokens:
            return tokens
    return frozenset()


def format_code(value: str) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 6:
        digits += "00"
    if len(digits) != 8:
        return None
    return f"{digits[:4]}.{digits[4:6]}.{digits[6:]}"


def format_heading(heading: str) -> str:
    digits = re.sub(r"\D", "", heading).zfill(4)[:4]
    return f"{digits[:2]}.{digits[2:]}"


class TariffDB:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DB_PATH
        if not self.path.exists():
            from data.build_tariff import DEFAULT_PDF, build_database

            build_database(DEFAULT_PDF, self.path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.row_factory = sqlite3.Row
        self.meta = {
            row["key"]: row["value"]
            for row in self.conn.execute("SELECT key, value FROM metadata")
        }
        self.notes = {
            row["chapter"]: row["notes"] or ""
            for row in self.conn.execute("SELECT chapter, notes FROM chapters")
        }
        self.heading_text = self._load_heading_text()
        self.lines = self._load_lines()
        self.by_code = {line.hs_code: line for line in self.lines}
        self.by_heading: dict[str, list[TariffLine]] = {}
        for line in self.lines:
            self.by_heading.setdefault(line.heading, []).append(line)

    def close(self) -> None:
        self.conn.close()

    def _load_heading_text(self) -> dict[str, str]:
        texts: dict[str, str] = {}
        rows = self.conn.execute(
            """
            SELECT heading, digits, description
            FROM tariff_lines
            WHERE description != ''
            ORDER BY heading, length(digits), digits
            """
        )
        for row in rows:
            heading = row["heading"]
            if heading in texts:
                continue
            description = (row["description"] or "").strip()
            if description.lower().rstrip(":") == "other":
                continue
            texts[heading] = description
        return texts

    def _load_lines(self) -> list[TariffLine]:
        rows = self.conn.execute(
            """
            SELECT hs_code, heading, chapter, description, legal_path,
                   search_text, duty_general
            FROM tariff_lines
            WHERE is_leaf = 1 AND hs_code IS NOT NULL
            """
        )
        lines: list[TariffLine] = []
        for row in rows:
            description = row["description"] or ""
            legal_path = row["legal_path"] or description
            lines.append(
                TariffLine(
                    hs_code=row["hs_code"],
                    heading=row["heading"],
                    chapter=row["chapter"],
                    description=description,
                    legal_path=legal_path,
                    search_text=row["search_text"] or description,
                    duty_general=row["duty_general"] or "Unknown",
                    tokens=frozenset(tokenize(row["search_text"] or description)),
                    specific_tokens=frozenset(tokenize(description)),
                    nearest_tokens=_nearest_tokens(legal_path),
                )
            )
        return lines

    def get(self, hs_code: str) -> TariffLine | None:
        formatted = format_code(hs_code)
        if formatted is None:
            return None
        return self.by_code.get(formatted)

    def leaves_for_heading(self, heading: str) -> list[TariffLine]:
        digits = re.sub(r"\D", "", heading)[:4]
        return self.by_heading.get(digits, [])

    def search_fts(self, tokens: list[str], limit: int = 25) -> list[TariffLine]:
        """BM25 candidates from the FTS5 index over the legal wording."""
        if not tokens:
            return []
        query = " OR ".join(f'"{token}"' for token in tokens[:12])
        try:
            with self._lock:
                rows = self.conn.execute(
                    """
                    SELECT hs_code FROM tariff_fts
                    WHERE tariff_fts MATCH ?
                    ORDER BY bm25(tariff_fts)
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        found: list[TariffLine] = []
        for row in rows:
            line = self.by_code.get(row["hs_code"])
            if line is not None:
                found.append(line)
        return found

    @property
    def schedule_date(self) -> str:
        raw = self.meta.get("source_date", "")
        if len(raw) == 10 and raw[4] == "-":
            year, month, day = raw.split("-")
            months = {
                "01": "January", "02": "February", "03": "March", "04": "April",
                "05": "May", "06": "June", "07": "July", "08": "August",
                "09": "September", "10": "October", "11": "November", "12": "December",
            }
            return f"{int(day)} {months.get(month, month)} {year}"
        return raw or "the current SARS Schedule 1 Part 1"

    @property
    def leaf_count(self) -> int:
        return len(self.lines)
