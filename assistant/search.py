"""Keyword search over manual pages: SQLite FTS5 (porter stemming) ranked by BM25.

Phase 2 replaces search() with hybrid BM25 + vector search; keep its signature.
"""

import re
import sqlite3
from typing import NamedTuple

from .config import load_config
from .db import connect

# Column weights for bm25(): page_id, manual, page, printed_page (unindexed), heading, text.
BM25_WEIGHTS = (0, 0, 0, 0, 2.0, 1.0)

# Filler words dropped from questions so the remaining terms carry the ranking.
STOPWORDS = frozenset("""
a about all also am an and any are as at be been being both but by can can't cannot could couldn't
did didn't do does doesn't doing don't due each few for from get gets getting got had has hasn't have
haven't having he her here hers him his how i i'd i'll i'm i've if in into is isn't it it's its
itself just keep keeps kind let like ll me mean means meaning might more most much must my myself
need needs now of only or other our own please really s same says she should shouldn't showing
shows so some still such t than that that's the their them then there these they thing this those
to too us ve very want was wasn't we were what what's whats when where which while who whom why
will with won won't would wouldn't you your yours
""".split())

# A term is a run of letters/digits, optionally joined by . - / (fault codes like F.OF, E-204, A/E).
_TERM = re.compile(r"[A-Za-z0-9]+(?:[.\-/][A-Za-z0-9]+)*")


class Hit(NamedTuple):
    manual: str
    page: int
    heading: str
    text: str
    score: float  # BM25 relevance, higher is better


# "code 5", "fault F.OF": the code next to its label, matched as a phrase ("SECU CODE 5").
_LABELLED_CODE = re.compile(r"\b(code|fault|error|alarm)\s+([A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*)\b", re.I)


def query_terms(question: str) -> list[str]:
    """FTS5 terms for a question: filler words dropped, compound codes kept as phrases."""
    terms: list[str] = []
    for label, code in _LABELLED_CODE.findall(question):
        if code.lower() not in STOPWORDS and any(ch.isdigit() or ch.isupper() for ch in code):
            terms.append(" ".join([label.lower(), *re.split(r"[.\-]", code.lower())]))
    for raw in _TERM.findall(question):
        parts = re.split(r"[.\-/]", raw.lower())
        if len(parts) > 1:
            # FTS5 splits "f.OF" into the tokens f, of; a phrase keeps them adjacent.
            term = " ".join(parts)
        else:
            term = parts[0]
            if term in STOPWORDS or (len(term) == 1 and term.isalpha() and raw not in "BCDEFGHJKLMNPQRSTUVWXYZ"):
                continue  # single lowercase letters are word fragments ("won't" -> "t"); capitals may be codes
        if term not in terms:
            terms.append(term)
    return terms


def match_expression(question: str) -> str:
    """OR the terms so one missing word doesn't empty the results; quoting avoids FTS5 syntax."""
    return " OR ".join(f'"{t}"' for t in query_terms(question))


def search(question: str, k: int = 3, *, conn: sqlite3.Connection | None = None) -> list[Hit]:
    expr = match_expression(question)
    if not expr:
        return []
    own = conn is None
    if own:
        conn = connect(load_config().db_path)
    try:
        weights = ", ".join(map(str, BM25_WEIGHTS))
        rows = conn.execute(
            f"SELECT manual, page, heading, text, -bm25(pages, {weights}) AS score"
            " FROM pages WHERE pages MATCH ? ORDER BY score DESC LIMIT ?",
            (expr, k),
        ).fetchall()
    finally:
        if own:
            conn.close()
    return [Hit(m, int(p), h, t, round(s, 3)) for m, p, h, t, s in rows]
