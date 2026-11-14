"""Ingest PDF manuals into the SQLite FTS5 index, one row per page.

Per page: text outside tables (two-column pages read column by column), tables rendered
row by row as "header: value" so grid layouts keep their columns, running headers and
footers removed, and the section heading in force at the top of the page.
"""

import hashlib
import logging
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from .db import connect

log = logging.getLogger(__name__)

BAND = 0.06            # top/bottom fraction of the page treated as header/footer band
BOILERPLATE_SHARE = 0.3  # band lines repeated on this share of pages are dropped
SHORT_CELL = 15       # table cells up to this length get their column header as a prefix
MIN_PAGE_CHARS = 20    # fewer extracted characters than this = no text layer (likely scanned)


@dataclass
class Line:
    top: float
    text: str
    size: float
    bold: bool
    band: bool          # in the header/footer band


@dataclass
class RawPage:
    page: int
    lines: list[Line]   # in reading order; tables appear as Line(size=0)
    tables: int


@dataclass
class Page:
    page: int
    printed_page: int | None
    heading: str
    text: str


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --- extraction ------------------------------------------------------------------------------------

_SECTION_NO_SPACE = re.compile(r"^(\d+(?:\.\d+)+|\d+\.)(?=[A-Z][a-z])")


def _clean(text: str) -> str:
    """Normalise whitespace and fix '10.1The motor' -> '10.1 The motor'."""
    text = re.sub(r"\s+", " ", text).strip()
    return _SECTION_NO_SPACE.sub(r"\1 ", text)


def _render_table(rows: list[list[str | None]], has_header: bool) -> str:
    """Render a table as one line per row: 'first cell | header: value | ...'.

    Merged cells (None) inherit the value above, so every row of a fault table
    carries its fault code.
    """
    rows = [[_clean(c) if c else (None if c is None else "") for c in r] for r in rows]
    header = rows[0] if has_header else None
    body = rows[1:] if header else rows
    out, above = [], [""] * max(len(r) for r in rows)
    if header:
        out.append(" | ".join(c for c in header if c))
    for row in body:
        # Fill only the row key and short values; repeating long merged notes bloats the page.
        filled = [above[i] if c is None and (i == 0 or len(above[i]) <= SHORT_CELL) else (c or "")
                  for i, c in enumerate(row)]
        above[: len(filled)] = filled
        cells = []
        for i, cell in enumerate(filled):
            if not cell:
                continue
            # Short values (grid marks like "C", "R", "250 hours") mean nothing without their
            # column header; long text cells stand alone and repeating headers would bloat BM25.
            name = header[i] if header and 0 < i < len(header) and len(cell) <= SHORT_CELL else ""
            cells.append(f"{name}: {cell}" if name and name != cell else cell)
        if cells:
            out.append(" | ".join(cells))
    return "\n".join(out)


def _gutter(chars: list[dict], width: float) -> float | None:
    """x of an empty vertical strip in the middle of the page (a two-column layout), else None."""
    if len(chars) < 200:
        return None
    occupied = bytearray(int(width) + 2)
    for c in chars:
        for x in range(max(0, int(c["x0"])), min(int(width), int(c["x1"])) + 1):
            occupied[x] = 1
    run = 0
    for x in range(int(width * 0.35), int(width * 0.65)):
        run = run + 1 if not occupied[x] else 0
        if run >= 6:
            return x - run / 2
    return None


def _lines(region, height: float) -> list[Line]:
    out = []
    for ln in region.extract_text_lines(return_chars=True, strip=True):
        chars = [c for c in ln["chars"] if c["text"].strip()]
        if not chars:
            continue
        size = sum(c["size"] for c in chars) / len(chars)
        bold = sum("bold" in c["fontname"].lower() for c in chars) > len(chars) / 2
        band = ln["top"] < height * BAND or ln["top"] > height * (1 - BAND)
        out.append(Line(ln["top"], _clean(ln["text"]), size, bold, band))
    return out


def _extract_page(pg) -> tuple[list[Line], int]:
    W, H = pg.width, pg.height
    # Drop rotated text (e.g. vertical "English (GB)" tabs), which extracts reversed.
    pg = pg.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))

    tables = []
    for t in pg.find_tables():
        rows = t.extract()
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            # A first row set in bold is a header row.
            first = [c for c in pg.within_bbox(t.rows[0].bbox).chars if c["text"].strip()]
            bold = sum("bold" in c["fontname"].lower() for c in first) > len(first) / 2
            tables.append((t.bbox, _render_table(rows, bold)))

    def outside_tables(o):
        if o.get("object_type") != "char":
            return True
        cx, cy = (o["x0"] + o["x1"]) / 2, (o["top"] + o["bottom"]) / 2
        return not any(x0 <= cx <= x1 and top <= cy <= bottom for (x0, top, x1, bottom), _ in tables)

    pg = pg.filter(outside_tables)
    body_chars = [c for c in pg.chars if H * BAND < c["top"] < H * (1 - BAND) and c["text"].strip()]
    gutter = _gutter(body_chars, W)

    table_lines = [(bbox, Line(bbox[1], text, 0.0, False, False)) for bbox, text in tables]
    if gutter is None:
        lines = _lines(pg, H) + [ln for _, ln in table_lines]
        lines.sort(key=lambda ln: ln.top)
    else:
        lines = []
        for x0, x1 in ((0, gutter), (gutter, W)):
            col = _lines(pg.crop((x0, 0, x1, H)), H)
            # Tables go with the column holding their centre (full-width ones with the left column).
            col += [ln for (bx0, _, bx1, _), ln in table_lines if x0 <= (bx0 + bx1) / 2 < x1]
            lines += sorted(col, key=lambda ln: ln.top)
    return lines, len(tables)


def _extract_pypdf(path: Path) -> list[RawPage]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return [RawPage(i, [Line(0, _clean(t), 0, False, False) for t in (p.extract_text() or "").splitlines() if t.strip()], 0)
            for i, p in enumerate(reader.pages, 1)]


def extract_raw(path: Path) -> list[RawPage]:
    try:
        pages = []
        with pdfplumber.open(path) as pdf:
            for i, pg in enumerate(pdf.pages, 1):
                lines, n_tables = _extract_page(pg)
                pages.append(RawPage(i, lines, n_tables))
        return pages
    except Exception as e:  # malformed PDFs: fall back to plain pypdf text
        log.warning("%s: pdfplumber failed (%s); falling back to pypdf", path.name, e)
        return _extract_pypdf(path)


# --- page assembly ---------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower())


def _boilerplate(raw: list[RawPage]) -> set[str]:
    """Header/footer lines that repeat across many pages (digits ignored, so page numbers match)."""
    seen = Counter()
    for p in raw:
        seen.update({_norm(ln.text) for ln in p.lines if ln.band})
    threshold = max(3, BOILERPLATE_SHARE * len(raw))
    return {t for t, n in seen.items() if n >= threshold}


def printed_offset(raw: list[RawPage]) -> int | None:
    """Offset between PDF and printed page numbers, from numbers at the start/end of footer lines."""
    offsets = Counter()
    for p in raw:
        found = set()
        for ln in p.lines:
            if not ln.band:
                continue
            for m in (re.match(r"(\d{1,4})\b", ln.text), re.search(r"\b(\d{1,4})$", ln.text)):
                if m:
                    found.add(p.page - int(m.group(1)))
        offsets.update(found)
    if not offsets:
        return None
    offset, n = offsets.most_common(1)[0]
    return offset if n >= max(3, 0.3 * len(raw)) else None


def _body_size(raw: list[RawPage]) -> float:
    sizes = Counter()
    for p in raw:
        for ln in p.lines:
            if ln.size:
                sizes[round(ln.size, 1)] += len(ln.text)
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _is_heading(ln: Line, body: float) -> bool:
    if ln.band or not ln.size or not body:
        return False
    letters = sum(ch.isalpha() for ch in ln.text)
    return (ln.size >= body + 0.9 and (ln.bold or ln.size >= body * 1.3)
            and letters >= 3 and len(ln.text) <= 120)


def assemble(raw: list[RawPage]) -> list[Page]:
    boiler = _boilerplate(raw)
    offset = printed_offset(raw)
    body = _body_size(raw)
    section = ""
    pages = []
    for p in raw:
        lines = [ln for ln in p.lines if not (ln.band and _norm(ln.text) in boiler)]
        # Merge headings that wrap onto a second line.
        headings: list[tuple[int, str]] = []  # (index in lines, text)
        prev = None
        for i, ln in enumerate(lines):
            if _is_heading(ln, body):
                if prev is not None and abs(prev.size - ln.size) < 0.3 and 0 < ln.top - prev.top < prev.size * 1.8:
                    headings[-1] = (headings[-1][0], headings[-1][1] + " " + ln.text)
                else:
                    headings.append((i, ln.text))
                prev = ln
            else:
                prev = None
        first_body = next((i for i, ln in enumerate(lines) if not ln.band), None)
        if headings and (headings[0][0] == first_body or not section):
            heading = headings[0][1]
        else:
            heading = section
        if headings:
            section = headings[-1][1]
        printed = p.page - offset if offset is not None and p.page - offset >= 1 else None
        pages.append(Page(p.page, printed, heading, "\n".join(ln.text for ln in lines)))
    return pages


def extract_pages(path: Path) -> tuple[list[Page], int | None]:
    raw = extract_raw(path)
    return assemble(raw), printed_offset(raw)


# --- indexing --------------------------------------------------------------------------------------

def ingest_file(conn: sqlite3.Connection, path: Path, force: bool = False) -> str:
    """Index one PDF. Returns 'skipped', 'indexed' or 'reindexed'."""
    manual = path.stem
    digest = file_hash(path)
    row = conn.execute("SELECT file_hash FROM manuals WHERE manual = ?", (manual,)).fetchone()
    if row and row[0] == digest and not force:
        log.info("%s: unchanged, skipped", manual)
        return "skipped"

    pages, offset = extract_pages(path)
    empty = [p.page for p in pages if len(p.text) < MIN_PAGE_CHARS]
    if empty:
        log.warning("%s: %d page(s) with no text (scanned? no OCR in phase 1): %s",
                    manual, len(empty), ", ".join(map(str, empty)))

    with conn:
        conn.execute("DELETE FROM pages WHERE manual = ?", (manual,))
        conn.executemany(
            "INSERT INTO pages (page_id, manual, page, printed_page, heading, text) VALUES (?, ?, ?, ?, ?, ?)",
            [(f"{digest[:16]}:{p.page}", manual, p.page, p.printed_page, p.heading, p.text) for p in pages])
        conn.execute(
            "INSERT OR REPLACE INTO manuals (manual, file_hash, path, n_pages, printed_offset, indexed_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (manual, digest, str(path), len(pages), offset, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    log.info("%s: indexed %d pages (printed page offset: %s)", manual, len(pages), offset)
    return "reindexed" if row else "indexed"


def ingest(paths: list[Path], db_path: Path, force: bool = False) -> dict[str, str]:
    pdfs = []
    for p in paths:
        pdfs += sorted(p.glob("*.pdf")) if p.is_dir() else [p]
    conn = connect(db_path)
    try:
        return {pdf.stem: ingest_file(conn, pdf, force) for pdf in pdfs}
    finally:
        conn.close()
