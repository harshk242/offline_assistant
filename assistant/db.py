"""SQLite index: one FTS5 row per manual page."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS manuals (
    manual          TEXT PRIMARY KEY,   -- file stem, used in citations
    file_hash       TEXT NOT NULL,      -- sha256 of the PDF
    path            TEXT NOT NULL,
    n_pages         INTEGER NOT NULL,
    printed_offset  INTEGER,            -- printed page = PDF page - offset (NULL if not detected)
    indexed_at      TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
    page_id UNINDEXED,                  -- '<file_hash[:16]>:<page>', stable key for phase-2 embeddings
    manual UNINDEXED,
    page UNINDEXED,                     -- 1-based PDF page
    printed_page UNINDEXED,             -- number printed in the footer, if known
    heading,
    text,
    tokenize = 'porter unicode61'
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn
