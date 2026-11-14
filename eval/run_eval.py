"""Phase 1 evaluation over eval/questions.json.

Retrieval: share of answerable questions with an expected page in the top 1 / top k.
Answers (--answer): share with a valid citation to an expected page, share whose text contains
the expected keywords, refusals that correctly say "not found", and latency per question.

    python eval/run_eval.py                 # retrieval only
    python eval/run_eval.py --answer --mock # full pipeline with the offline mock LLM
    python eval/run_eval.py --answer        # full pipeline against the configured LFM endpoint
"""

import argparse
import dataclasses
import json
import re
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from assistant.answer import answer  # noqa: E402
from assistant.config import load_config  # noqa: E402
from assistant.search import search  # noqa: E402


def accepted(q: dict) -> set[tuple[str, int]]:
    pairs = q.get("accept") or ([[q["manual"], q["pages"]]] if "manual" in q else [])
    return {(m, p) for m, pages in pairs for p in pages}


def keywords_ok(text: str, groups: list[str]) -> bool:
    """Every group must match; a group is 'alt1|alt2' (case-insensitive substrings)."""
    low = text.lower()
    return all(any(alt.lower() in low for alt in g.split("|")) for g in groups)


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer", action="store_true", help="run the full pipeline, not just search")
    ap.add_argument("--mock", action="store_true", help="use the mock LLM")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("-v", "--verbose", action="store_true", help="print each answer")
    args = ap.parse_args()

    cfg = load_config()
    if args.mock:
        cfg = dataclasses.replace(cfg, llm_mock=True)
    questions = json.loads((HERE / "questions.json").read_text())
    if args.only:
        keep = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in keep]
    conn = sqlite3.connect(cfg.db_path)

    rows = []
    for q in questions:
        exp = accepted(q)
        hits = search(q["q"], cfg.top_k, conn=conn)
        ranks = [i for i, h in enumerate(hits, 1) if (h.manual, h.page) in exp]
        row = {"id": q["id"], "type": q["type"], "question": q["q"],
               "top": [[h.manual, h.page, h.score] for h in hits],
               "rank": ranks[0] if ranks else None}
        if args.answer:
            t0 = time.perf_counter()
            a = answer(q["q"], cfg, conn=conn)
            total_ms = (time.perf_counter() - t0) * 1000
            row.update(
                answer=a.text, found=a.found, citations=a.citations,
                citation_ok=any(c in exp for c in a.citations),
                keywords_ok=a.found and "keywords" in q and keywords_ok(a.text, q["keywords"]),
                llm_called=a.llm is not None, llm_error=a.llm.error if a.llm else None,
                llm_ms=round(a.llm.ms, 1) if a.llm else None, llm_tokens=a.llm.tokens if a.llm else None,
                total_ms=round(total_ms, 1),
            )
            if args.verbose:
                mark = "refused" if not a.found else ("cite OK" if row["citation_ok"] else "cite --")
                print(f"\n[{q['id']}] {q['q']}\n  -> {a.text}\n  ({mark}, {total_ms:.0f} ms)")
        rows.append(row)

    answerable = [r for r in rows if r["type"] != "refuse"]
    refuse = [r for r in rows if r["type"] == "refuse"]
    print(f"\n{'id':4} {'type':10} {'rank':4}  top pages")
    for r in rows:
        top = ", ".join(f"{m.split('_')[0]} p{p} ({s:.1f})" for m, p, s in r["top"])
        extra = ""
        if args.answer:
            extra = ("  REFUSED" if not r["found"] else "") + ("  cite✓" if r.get("citation_ok") else "") + \
                    ("  kw✓" if r.get("keywords_ok") else "") + (f"  {r['total_ms']:.0f}ms")
        print(f"{r['id']:4} {r['type']:10} {r['rank'] or '-':>4}  {top}{extra}")

    print(f"\nRetrieval (answerable, n={len(answerable)}):")
    print(f"  expected page at rank 1:     {pct(sum(r['rank'] == 1 for r in answerable), len(answerable))}")
    print(f"  expected page in top {cfg.top_k}:     {pct(sum(r['rank'] is not None for r in answerable), len(answerable))}")
    for t in sorted({r["type"] for r in answerable}):
        sub = [r for r in answerable if r["type"] == t]
        print(f"    {t:10} top {cfg.top_k}: {pct(sum(r['rank'] is not None for r in sub), len(sub))}")

    if args.answer:
        print(f"\nAnswers ({'mock' if cfg.llm_mock else cfg.llm_url}):")
        print(f"  answered with a citation to an expected page: {pct(sum(r['citation_ok'] for r in answerable), len(answerable))}")
        print(f"  answer contains expected keywords:            {pct(sum(r['keywords_ok'] for r in answerable), len(answerable))}")
        print(f"  wrongly refused (answerable):                 {pct(sum(not r['found'] for r in answerable), len(answerable))}")
        print(f"  correctly refused (not in manuals):           {pct(sum(not r['found'] for r in refuse), len(refuse))}")
        errors = [r for r in rows if r["llm_error"]]
        if errors:
            print(f"  LLM errors: {len(errors)} (e.g. {errors[0]['llm_error']})")
        lat = [r["total_ms"] for r in rows if r["llm_called"]]
        if lat:
            print(f"  latency with LLM call: median {statistics.median(lat):.0f} ms, max {max(lat):.0f} ms (n={len(lat)})")

    out = HERE / "results" / f"{datetime.now():%Y%m%d-%H%M%S}{'-answer' if args.answer else ''}{'-mock' if cfg.llm_mock else ''}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, indent=1))
    print(f"\nSaved {out.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
