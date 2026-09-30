"""Classify an invoice description to an 8-digit SARS tariff line.

Keyword rules decide the heading where the WCO legal text is explicit.
Everything else is retrieved from the local tariff database by lexical
overlap with the official wording, then ranked so a specific subheading
beats a residual "Other" line only when the invoice actually uses that
more specific language (GRI 3(a) and GRI 6).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from data.tariff_db import TariffDB, TariffLine, format_heading
from engine.gri import GRI_1, GRI_3A, GRI_6
from engine.keyword_rules import RuleHit, expand_query, match_rules
from engine.textutil import tokenize

PUBLIC_FIELDS = (
    "line_number",
    "source_file",
    "part_number",
    "description",
    "quantity",
    "hs_code",
    "duty_rate_general",
    "wco_reasoning",
)


@dataclass
class Classification:
    description: str
    hs_code: str | None
    duty_rate_general: str | None
    wco_reasoning: str
    part_number: str | None = None
    quantity: int | float | None = None
    source_file: str = ""
    score: float = 0.0
    rule_id: str | None = None

    def as_dict(self, line_number: int) -> dict:
        return {
            "line_number": line_number,
            "source_file": self.source_file,
            "part_number": self.part_number,
            "description": self.description,
            "quantity": self.quantity,
            "hs_code": self.hs_code,
            "duty_rate_general": self.duty_rate_general,
            "wco_reasoning": self.wco_reasoning,
        }


def _clip(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    cut = compact[: limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


class WCOClassifier:
    def __init__(self, db: TariffDB | None = None):
        self.db = db or TariffDB()
        self._idf: dict[str, float] = {}
        self._postings: dict[str, list[int]] = defaultdict(list)
        self._build_index()

    def _build_index(self) -> None:
        document_frequency: dict[str, int] = defaultdict(int)
        for index, line in enumerate(self.db.lines):
            for token in line.tokens:
                document_frequency[token] += 1
                self._postings[token].append(index)
        total = max(len(self.db.lines), 1)
        self._idf = {
            token: math.log((total + 1) / (frequency + 1)) + 1.0
            for token, frequency in document_frequency.items()
        }

    def classify(
        self,
        description: str,
        *,
        part_number: str | None = None,
        quantity: int | float | None = None,
        source_file: str = "",
    ) -> Classification:
        text = " ".join((description or "").split())
        base = Classification(
            description=text,
            hs_code=None,
            duty_rate_general=None,
            wco_reasoning="No product description was supplied, so no tariff line was selected.",
            part_number=part_number or None,
            quantity=quantity,
            source_file=source_file,
        )
        if len(tokenize(text)) == 0 and match_rules(text) is None:
            return base

        rule = match_rules(text)
        if rule is not None:
            line, score = self._classify_rule(rule, text)
        else:
            line, score = self._search(expand_query(text))
            if line is None:
                base.wco_reasoning = (
                    "No declarable tariff line in the local SARS Schedule 1 Part 1 "
                    "index matched this description. Add a clearer commercial description "
                    "before relying on a code."
                )
                return base

        assert line is not None
        query_tokens = frozenset(tokenize(expand_query(text), drop_pack_words=True))
        indicative = rule is None and (
            score < 4.0 or len(query_tokens & line.tokens) < 2
        )
        reasoning = self._reasoning(line, rule, indicative)
        return Classification(
            description=text,
            hs_code=line.hs_code,
            duty_rate_general=line.duty_general,
            wco_reasoning=reasoning,
            part_number=part_number or None,
            quantity=quantity,
            source_file=source_file,
            score=score,
            rule_id=None if rule is None else rule.rule_id,
        )

    def _classify_rule(self, rule: RuleHit, description: str) -> tuple[TariffLine, float]:
        if rule.prefer:
            chosen = self.db.get(rule.prefer)
            if chosen is not None:
                return chosen, 100.0
        leaves = self.db.leaves_for_heading(rule.heading)
        ranked = self._rank(expand_query(description), leaves)
        if ranked:
            return ranked[0]
        # The heading constraint missed. Fall back to the whole nomenclature
        # rather than invent a code.
        found = self._search(expand_query(description))
        if found[0] is None:
            raise LookupError(f"No tariff line available for heading {rule.heading}")
        return found

    def _search(self, description: str) -> tuple[TariffLine | None, float]:
        ranked = self._rank(description, None)
        if not ranked:
            return None, 0.0
        return ranked[0]

    def _rank(
        self, description: str, restricted: list[TariffLine] | None
    ) -> list[tuple[TariffLine, float]]:
        query = frozenset(tokenize(description, drop_pack_words=True))
        if not query:
            return []
        if restricted is None:
            pool = self._candidates(query)
        else:
            pool = restricted
        scored: list[tuple[TariffLine, float]] = []
        for line in pool:
            overlap = query & line.tokens
            if not overlap:
                continue
            match = sum(self._idf.get(token, 1.0) for token in overlap)
            match *= 0.65 + 0.35 * (len(overlap) / len(query))
            near = query & line.nearest_tokens
            if near:
                match += 1.2 * sum(self._idf.get(token, 1.0) for token in near)
            # A long statutory definition ("keyboard and a display") should not
            # cancel a distinctive hit such as "portable". Count the extra words
            # instead of weighting them like a contradiction.
            near_extra = line.nearest_tokens - query
            if near_extra:
                match -= 0.45 * len(near_extra)
            extra = line.specific_tokens - query
            if extra:
                match -= 0.2 * sum(self._idf.get(token, 1.0) for token in extra)
            # A residual "Other" line has no specific tokens. A sibling that
            # adds conditions the invoice did not state should not outrank it
            # on the shared heading words alone; the penalty above does that.
            if not line.specific_tokens:
                match += 0.15
            scored.append((line, match))
        scored.sort(key=lambda item: item[1], reverse=True)
        return self._fuzzy_rerank(description, scored)

    def _fuzzy_rerank(
        self, description: str, scored: list[tuple[TariffLine, float]]
    ) -> list[tuple[TariffLine, float]]:
        """Let RapidFuzz break close lexical ties using the legal phrase."""
        if len(scored) < 2:
            return scored
        from rapidfuzz import fuzz

        head, tail = scored[:8], scored[8:]
        adjusted: list[tuple[TariffLine, float]] = []
        for line, score in head:
            fuzzy = fuzz.token_set_ratio(description, line.legal_path) / 100.0
            adjusted.append((line, score + fuzzy * 1.5))
        adjusted.sort(key=lambda item: item[1], reverse=True)
        return adjusted + tail

    def _candidates(self, query: frozenset[str]) -> list[TariffLine]:
        ordered = sorted(query, key=lambda token: self._idf.get(token, 0.0), reverse=True)
        found: set[int] = set()
        for token in ordered:
            postings = self._postings.get(token, [])
            if len(postings) > 2500 and found:
                continue
            found.update(postings)
            if len(found) > 800 and len(ordered) > 1:
                break
        pool = [self.db.lines[index] for index in found]
        seen = {line.hs_code for line in pool}
        for line in self.db.search_fts(sorted(query), limit=25):
            if line.hs_code not in seen:
                pool.append(line)
                seen.add(line.hs_code)
        return pool

    def _reasoning(self, line: TariffLine, rule: RuleHit | None, indicative: bool) -> str:
        if rule is not None:
            text = rule.reasoning.format(
                hs_code=line.hs_code,
                duty=line.duty_general,
                heading=format_heading(line.heading),
                schedule=self.db.schedule_date,
            )
            return text
        excerpt = _clip(self.db.heading_text.get(line.heading) or line.legal_path)
        if line.description and line.description.lower().strip(" :") not in {"other"}:
            specific = (
                f" {GRI_3A} {GRI_6} Subheading wording "
                f"\"{_clip(line.description, 180)}\" is preferred to a residual Other provision."
            )
        else:
            specific = (
                f" {GRI_3A} The invoice does not use a more specific subheading phrase, "
                "so the residual subheading in this heading is selected."
            )
        prefix = ""
        if indicative:
            prefix = (
                "Indicative classification — confirm the heading terms before lodging "
                "a customs declaration. "
            )
        return (
            f"{prefix}Classified under {line.hs_code}. {GRI_1} Heading "
            f"{format_heading(line.heading)} covers: {excerpt}.{specific} "
            f"General duty: {line.duty_general} (SARS Schedule 1 Part 1, {self.db.schedule_date})."
        )
