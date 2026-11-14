#!/usr/bin/env python3
"""Benchmark LFM3-1.7B on GenieX (board-local). Stdlib only.

Measures, per workload: time to first token (TTFT), time to first answer text
(after the empty think block), prefill tok/s, decode tok/s, end-to-end latency.
Also: cold load, sustained-run thermals, and server memory.

Run on the board:  python3 bench_lfm.py --runs 5 --out results.json
"""
import argparse, glob, json, os, statistics, subprocess, time, uuid, urllib.request

URL = "http://127.0.0.1:18181/v1/chat/completions"
MODEL = "LiquidAI/LFM3-1.7B-GGUF:Q4_0"
SYSTEM = ("You are a maintenance assistant. Answer only from the manual excerpts. "
          "Cite the page for each fact as [p. N]. If the excerpts do not cover the question, say so.")

# Manual-style filler used to build RAG contexts of realistic size.
CHUNK = ("[p. {p}] Section {p}.2 Troubleshooting. If the drive fails to energize, verify that the "
         "main disconnect is closed and that line voltage is present at terminals L1, L2 and L3. "
         "Check the control transformer fuse F{p} and the 24 VDC control supply. A fault code E0{p} "
         "indicates an overcurrent condition; inspect the motor leads for insulation damage and "
         "measure winding resistance phase to phase. Reset the thermal overload only after the motor "
         "has cooled for at least 15 minutes. Torque terminal screws to 2.5 N·m. ")

QUESTION = "The pump motor won't start and the display shows E04. What should I check first?"


def context(n_chunks):
    return "\n\n".join(CHUNK.format(p=i + 1) for i in range(n_chunks))


def stream(messages, max_tokens):
    body = json.dumps({"model": MODEL, "messages": messages, "max_completion_tokens": max_tokens,
                       "enable_think": False, "stream": True,
                       "stream_options": {"include_usage": True}}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    t0 = time.perf_counter(); ttft = ttfa = None; text = ""; final = {}; finish = None
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data:[DONE]":
                continue
            ev = json.loads(line[5:])
            if ev.get("timings"):
                final = ev
            for ch in ev.get("choices", []):
                finish = ch.get("finish_reason") or finish
                c = ch.get("delta", {}).get("content")
                if c:
                    now = time.perf_counter() - t0
                    ttft = ttft or now
                    if c.strip() and "think>" not in c:
                        ttfa = ttfa or now
                    text += c
    total = time.perf_counter() - t0
    t = final.get("timings", {}); u = final.get("usage", {})
    return {"ttft_s": ttft, "ttfa_s": ttfa, "total_s": total, "finish": finish,
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "prefill_tps": t.get("prompt_per_second"), "prefill_ms": t.get("prompt_ms"),
            "decode_tps": t.get("predicted_per_second"),
            "e2e_tps": (u.get("completion_tokens") or 0) / total, "text": text}


def msgs(n_chunks, question=QUESTION):
    # Nonce first so no prefix-cache reuse between runs.
    sys = f"[run {uuid.uuid4().hex[:8]}] {SYSTEM}"
    user = (f"Manual excerpts:\n{context(n_chunks)}\n\nQuestion: {question}" if n_chunks else question)
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def nsp_temp_c():
    vals = []
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            if open(f"{z}/type").read().startswith("nsp"):
                vals.append(int(open(f"{z}/temp").read()) / 1000)
        except OSError:
            pass
    return max(vals) if vals else None


def server_rss_mb():
    out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
    pid = next((l.split("pid=")[1].split(",")[0] for l in out.splitlines() if ":18181 " in l), None)
    if not pid:
        return None
    st = open(f"/proc/{pid}/status").read()
    get = lambda k: int(next(l.split()[1] for l in st.splitlines() if l.startswith(k))) / 1024
    return {"rss_mb": round(get("VmRSS"), 1), "peak_rss_mb": round(get("VmHWM"), 1)}


def med(rows, k):
    v = [r[k] for r in rows if r[k] is not None]
    return round(statistics.median(v), 3) if v else None


def summarize(name, rows):
    s = {"workload": name, "runs": len(rows)}
    for k in ("prompt_tokens", "completion_tokens", "ttft_s", "ttfa_s", "total_s",
              "prefill_tps", "decode_tps", "e2e_tps"):
        s[k] = med(rows, k)
    s["ttft_p_max_s"] = round(max(r["ttft_s"] for r in rows), 3)
    s["finish"] = sorted({r["finish"] for r in rows})
    s["sample"] = rows[-1]["text"][:300]
    return s


def cold_load(serve_sh):
    subprocess.run(["bash", serve_sh, "stop"], check=True, capture_output=True)
    t0 = time.perf_counter()
    subprocess.run(["setsid", "bash", serve_sh, "start"], check=True, capture_output=True,
                   stdin=subprocess.DEVNULL)
    up = time.perf_counter() - t0
    r = stream(msgs(0), 32)
    return {"server_up_s": round(up, 2), "first_request_s": round(r["total_s"], 2),
            "first_request_ttft_s": round(r["ttft_s"], 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--serve-sh", default=os.path.expanduser("~/iq9/serve.sh"))
    ap.add_argument("--out", default="results.json")
    a = ap.parse_args()

    res = {"model": MODEL, "date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    res["cold"] = cold_load(a.serve_sh)
    print("cold:", res["cold"], flush=True)
    stream(msgs(0), 16)  # warm-up

    # (name, manual chunks in prompt, answer cap)
    workloads = [("no_context_short", 0, 64), ("rag_4_chunks", 4, 256), ("rag_8_chunks", 8, 256),
                 ("rag_16_chunks", 16, 256), ("rag_28_chunks", 28, 256), ("long_answer_512", 4, 512)]
    res["workloads"] = []
    for name, n, cap in workloads:
        rows = []
        for _ in range(a.runs):
            q = (QUESTION + " Give a detailed step-by-step procedure." if name == "long_answer_512" else QUESTION)
            rows.append(stream(msgs(n, q), cap))
        s = summarize(name, rows); res["workloads"].append(s)
        print(json.dumps({k: v for k, v in s.items() if k != "sample"}), flush=True)

    # Sustained: 20 back-to-back RAG queries; watch decode speed and NPU temperature.
    t_start = nsp_temp_c(); rows = []
    t0 = time.perf_counter()
    for _ in range(20):
        rows.append(stream(msgs(8), 256))
    res["sustained"] = {"queries": 20, "wall_s": round(time.perf_counter() - t0, 1),
                        "nsp_temp_start_c": t_start, "nsp_temp_end_c": nsp_temp_c(),
                        "decode_tps_first5": round(statistics.median(r["decode_tps"] for r in rows[:5]), 1),
                        "decode_tps_last5": round(statistics.median(r["decode_tps"] for r in rows[-5:]), 1),
                        "ttft_first5_s": round(statistics.median(r["ttft_s"] for r in rows[:5]), 3),
                        "ttft_last5_s": round(statistics.median(r["ttft_s"] for r in rows[-5:]), 3)}
    print("sustained:", res["sustained"], flush=True)
    res["memory"] = server_rss_mb()
    mi = dict(l.split(":") for l in open("/proc/meminfo").read().splitlines())
    res["memory"]["system_used_gb"] = round((int(mi["MemTotal"].split()[0]) - int(mi["MemAvailable"].split()[0])) / 2**20, 2)
    print("memory:", res["memory"])
    json.dump(res, open(a.out, "w"), indent=2)


if __name__ == "__main__":
    main()
