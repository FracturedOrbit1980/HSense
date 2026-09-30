"""Token helpers shared by tariff search."""

from __future__ import annotations

import re

STOPWORDS = {
    "the", "of", "and", "or", "for", "with", "from", "other", "including",
    "excluding", "whether", "not", "than", "per", "cent", "mass", "heading",
    "chapter", "into", "onto", "such", "only", "but", "its", "are", "was",
    "which", "that", "this", "these", "those", "under", "over", "more", "less",
    "non", "any", "all", "their", "without", "within", "between", "above",
    "below", "same", "being", "been", "have", "has", "had", "also", "than",
    "compound", "compounds", "product", "products", "material", "materials",
    "preparation", "preparations", "kind", "thereof", "therein", "hereby",
    "where", "when", "each", "item", "line", "description", "qty", "quantity",
}

# Pack words that describe the container, not the goods.
PACK_WORDS = {
    "tin", "can", "drum", "pail", "bottle", "tube", "cartridge", "bag", "box",
    "set", "kit", "pack", "pail", "jar", "bucket", "carton",
}

_TOKEN = re.compile(r"[a-z0-9]+")
NEGATORS = {"not", "excluding", "except", "without", "non"}


def stem(token: str) -> str:
    """Light plural stemmer. ``machines`` stays aligned with ``machine``."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es"):
        if token[-3] in "sxz" or token.endswith(("ches", "shes", "oes")):
            return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str, *, drop_pack_words: bool = False) -> list[str]:
    """Tokenize legal or invoice text.

    A word immediately after ``not``, ``excluding``, ``except``, ``without``
    or ``non`` is dropped. Otherwise ``not roasted`` still retrieves every
    roasted-coffee line, and the negation never gets a vote.
    """
    words = _TOKEN.findall(text.lower())
    tokens: list[str] = []
    skip_next = False
    for index, raw in enumerate(words):
        # "whether or not roasted" includes roasted goods. Only a real negation
        # ("not roasted", "excluding steel") should suppress the next word.
        inclusive_not = (
            raw == "not"
            and index >= 2
            and words[index - 2] == "whether"
            and words[index - 1] == "or"
        )
        if raw in NEGATORS and not inclusive_not:
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        if raw.isdigit() or len(raw) < 3:
            continue
        token = stem(raw)
        if token in STOPWORDS or len(token) < 3:
            continue
        if drop_pack_words and token in PACK_WORDS:
            continue
        tokens.append(token)
    return tokens
