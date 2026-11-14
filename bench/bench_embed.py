#!/usr/bin/env python3
"""Benchmark LFM2.5-Embedding-350M (Q8_0, llama-server on CPU) on the board. Stdlib only.

Uses the real indexed manual pages and the test questions (export them on the laptop with
--export, copy the JSON to the board). Quick run (~1 min): question latency, page latency by size,
batching, contention with LFM3 on the NPU, memory.

Laptop:  python3 bench/bench_embed.py --export corpus.json
Board:   python3 bench_embed.py --corpus corpus.json --out embed_results.json
"""
import argparse, json, os, re, sqlite3, statistics, subprocess, threading, time, urllib.request

EMBED = "http://127.0.0.1:18182"
LLM = "http://127.0.0.1:18181/v1/chat/completions"
LLM_MODEL = "LiquidAI/LFM3-1.7B-GGUF:Q4_0"
MAX_TOKENS = 2048  # per-input limit set by embed.sh (-ub 2048)


def post(path, body, timeout=600):
    req = urllib.request.Request(EMBED + path if path.startswith("/") else path,
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def embed(texts):
    t0 = time.perf_counter()
    r = post("/v1/embeddings", {"input": texts})
    return time.perf_counter() - t0, r


def n_tokens(text):
    return len(post("/tokenize", {"content": text})["tokens"])


def doc(p):
    return "document: " + p["text"]


def pct(v, q):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(round(q * (len(v) - 1))))], 4)


def stats(v):
    return {"median": round(statistics.median(v), 4), "p95": pct(v, 0.95), "max": round(max(v), 4)}


def server_pid(port):
    out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
    return next((l.split("pid=")[1].split(",")[0] for l in out.splitlines() if f":{port} " in l), None)


def rss_mb(port):
    pid = server_pid(port)
    if not pid:
        return None
    st = open(f"/proc/{pid}/status").read()
    get = lambda k: round(int(next(l.split()[1] for l in st.splitlines() if l.startswith(k))) / 1024, 1)
    return {"rss_mb": get("VmRSS"), "peak_rss_mb": get("VmHWM")}


def llm_call():
    body = {"model": LLM_MODEL, "max_completion_tokens": 64, "enable_think": False, "stream": False,
            "messages": [{"role": "user", "content": f"[{time.time_ns()}] In one sentence, why would a pump lose prime?"}]}
    t0 = time.perf_counter()
    post(LLM, body, timeout=120)
    return time.perf_counter() - t0


def throughput(pages, batch):
    """Embed `pages` in batches; return pages/s and tok/s."""
    t0 = time.perf_counter(); toks = 0
    for i in range(0, len(pages), batch):
        _, r = embed([doc(p) for p in pages[i:i + batch]])
        toks += r["usage"]["prompt_tokens"]
    wall = time.perf_counter() - t0
    return {"batch": batch, "pages": len(pages), "wall_s": round(wall, 2),
            "pages_per_s": round(len(pages) / wall, 2), "tok_per_s": round(toks / wall)}


def export(path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    c = sqlite3.connect(os.path.join(root, "data", "index.db"))
    pages = [{"id": r[0], "manual": r[1], "page": r[2], "text": r[3]}
             for r in c.execute("select page_id, manual, page, text from pages")]
    qs = [m.group(1).strip() for line in open(os.path.join(root, "manuals", "test_questions.md"))
          if (m := re.match(r"\|\s*[A-Z]+\d+\s*\|[^|]*\|([^|]+)\|", line))]
    json.dump({"pages": pages, "questions": qs}, open(path, "w"))
    print(f"exported {len(pages)} pages, {len(qs)} questions to {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", help="laptop: write pages + questions from data/index.db to this JSON")
    ap.add_argument("--corpus", default="corpus.json")
    ap.add_argument("--out", default="embed_results.json")
    a = ap.parse_args()
    if a.export:
        return export(a.export)

    corpus = json.load(open(a.corpus))
    qs = corpus["questions"]
    res = {"model": "LFM2.5-Embedding-350M Q8_0", "date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}

    # Token counts of the real pages (empty, scanned pages are skipped as ingest would).
    pages = [p for p in corpus["pages"] if p["text"].strip()]
    for p in pages:
        p["tokens"] = n_tokens(doc(p))
    over = [p["id"] for p in pages if p["tokens"] > MAX_TOKENS]
    pages = [p for p in pages if p["tokens"] <= MAX_TOKENS]
    toks = [p["tokens"] for p in pages]
    res["corpus"] = {"pages": len(pages), "over_limit": over, "tokens": {"median": statistics.median(toks),
                     "p95": pct(toks, 0.95), "max": max(toks), "total": sum(toks)}}
    print("corpus:", res["corpus"], flush=True)

    embed(["query: warm-up"])
    res["query_latency_s"] = stats([embed(["query: " + q])[0] for q in qs])
    print("query:", res["query_latency_s"], flush=True)

    # Single-page latency by size, 5 pages per bucket.
    res["page_latency"] = []
    for lo, hi in [(0, 256), (256, 512), (512, 1024), (1024, MAX_TOKENS + 1)]:
        sel = [p for p in pages if lo <= p["tokens"] < hi][:5]
        if sel:
            t = [embed([doc(p)])[0] for p in sel]
            row = {"tokens": f"{lo}-{hi - 1}", "n": len(sel), "latency_s": stats(t),
                   "tok_per_s": round(sum(p["tokens"] for p in sel) / sum(t))}
            res["page_latency"].append(row); print("page:", row, flush=True)

    # Batching: 16 pages, 1 vs 8 per request. Full-corpus time is extrapolated from the faster one.
    sample = pages[:16]
    res["batching"] = [throughput(sample, b) for b in (1, 8)]
    for r in res["batching"]:
        print("batch:", r, flush=True)
    best = max(r["tok_per_s"] for r in res["batching"])
    res["corpus"]["est_full_embed_s"] = round(sum(toks) / best)

    # Contention with LFM3 on the NPU: 64-token LLM call alone vs while pages are being embedded.
    llm_call()  # warm
    alone = [llm_call() for _ in range(3)]
    stop = threading.Event()
    def churn():
        while not stop.is_set():
            embed([doc(p) for p in sample[:8]])
    th = threading.Thread(target=churn); th.start()
    time.sleep(1)
    busy = [llm_call() for _ in range(3)]
    stop.set(); th.join()
    res["contention"] = {"llm_alone_s": stats(alone), "llm_while_embedding_s": stats(busy)}
    print("contention:", res["contention"], flush=True)

    res["memory"] = rss_mb(18182)
    mi = dict(l.split(":") for l in open("/proc/meminfo").read().splitlines())
    res["memory"]["system_used_gb"] = round((int(mi["MemTotal"].split()[0]) - int(mi["MemAvailable"].split()[0])) / 2**20, 2)
    print("memory:", res["memory"])
    json.dump(res, open(a.out, "w"), indent=2)


if __name__ == "__main__":
    main()
