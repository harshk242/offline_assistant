"""Command line: `ingest [PDF or dir ...]` and `ask "question"`."""

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path

from .answer import answer
from .config import load_config
from .db import connect


def ingest_main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(prog="ingest", description="Index PDF manuals for search.")
    ap.add_argument("paths", nargs="*", type=Path, help=f"PDF files or directories (default: {cfg.manuals_dir})")
    ap.add_argument("--force", action="store_true", help="re-index even if a manual is unchanged")
    args = ap.parse_args(argv)
    from .ingest import ingest  # needs pdfplumber; `ask` runs on the standard library alone

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = ingest(args.paths or [cfg.manuals_dir], cfg.db_path, args.force)
    if not results:
        print("No PDFs found.", file=sys.stderr)
        return 1
    for manual, status in results.items():
        print(f"{status:9} {manual}")
    print(f"Index: {cfg.db_path}")
    return 0


def _printed_pages(db_path: Path, hits) -> dict[tuple[str, int], int | None]:
    conn = connect(db_path)
    try:
        return {(h.manual, h.page): conn.execute(
            "SELECT printed_page FROM pages WHERE manual = ? AND page = ?", (h.manual, h.page)).fetchone()[0]
            for h in hits}
    finally:
        conn.close()


def ask_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ask", description="Ask a question about the indexed manuals.")
    ap.add_argument("question", nargs="+")
    ap.add_argument("--mock", action="store_true", help="use the offline mock LLM (no server needed)")
    ap.add_argument("-k", type=int, help="pages to retrieve (default from config)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.mock:
        cfg = dataclasses.replace(cfg, llm_mock=True)
    if args.k:
        cfg = dataclasses.replace(cfg, top_k=args.k)
    if not cfg.db_path.exists():
        print(f"No index at {cfg.db_path}. Run `ingest` first.", file=sys.stderr)
        return 1

    a = answer(" ".join(args.question), cfg)
    printed = _printed_pages(cfg.db_path, a.hits)
    if args.json:
        print(json.dumps({
            "question": a.question, "answer": a.text, "found": a.found,
            "citations": [{"manual": m, "page": p, "printed_page": printed.get((m, p))} for m, p in a.citations],
            "sources": [{"manual": h.manual, "page": h.page, "printed_page": printed[(h.manual, h.page)],
                         "heading": h.heading, "score": h.score} for h in a.hits],
            "search_ms": round(a.search_ms, 1),
            "llm_ms": round(a.llm.ms, 1) if a.llm else None,
            "llm_tokens": a.llm.tokens if a.llm else None,
        }, indent=2))
        return 0

    print(a.text)
    if a.hits:
        print("\nSources:")
        for h in a.hits:
            pp = printed[(h.manual, h.page)]
            pp = f" (printed p. {pp})" if pp is not None and pp != h.page else ""
            print(f"  [{h.manual}, p. {h.page}]{pp}  {h.heading}  (score {h.score:.1f})")
    llm = f", LLM {a.llm.ms:.0f} ms / {a.llm.tokens} tokens" if a.llm else ", no LLM call"
    print(f"\n({'mock, ' if cfg.llm_mock else ''}search {a.search_ms:.0f} ms{llm})", file=sys.stderr)
    return 0
