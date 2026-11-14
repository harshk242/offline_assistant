# LFM3-1.7B benchmark on the IQ-9075

- **Setup:** `LiquidAI/LFM3-1.7B-GGUF:Q4_0` on the NPU (HTP0), GenieX v0.10.0 (QAIRT 2.50), Ubuntu 24.04, 2026-11-14.
- **Method:** streaming requests to the local server. Each workload ran 5 times and the numbers are medians. Every prompt starts with a unique tag so cached prompts are never reused.
- **Raw data:** [`bench/results.json`](../bench/results.json). Script: [`bench/bench_lfm.py`](../bench/bench_lfm.py), which runs on the board as `python3 bench_lfm.py`.

## Latency by prompt size

The prompts are manual-style excerpts (about 120 tokens each) plus a technician's question. The answer is capped at 256 tokens.

| Prompt | Prompt tokens | Time to first token | Total for 256-token answer | Output speed |
|---|---|---|---|---|
| Question only | 82 | 0.11 s | 1.6 s (64 tokens) | 41.5 tok/s |
| 4 excerpts | 570 | 0.50 s | 6.7 s | 41.6 tok/s |
| 8 excerpts | 1,050 | 0.88 s | 7.0 s | 41.7 tok/s |
| 16 excerpts | 2,010 | 1.60 s | 8.0 s | 40.3 tok/s |
| 28 excerpts (near the 4k context limit) | 3,450 | 2.75 s | 9.2 s | 38.6 tok/s |
| 4 excerpts, 512-token answer | 578 | 0.49 s | 12.8 s | 41.7 tok/s |

- **Prompt processing:** 1,180–1,270 tok/s (about 0.8 ms per prompt token). Time to first token grows with the number of retrieved excerpts.
- **Output speed:** about 41 tok/s, dropping slightly to 38.6 tok/s near the full 4k context.
- **Run-to-run variation:** small. The slowest time to first token was within 2% of the median.

## Startup, sustained use and resources

| Metric | Value |
|---|---|
| Server start, until it accepts requests | 1.1 s |
| First request after start (model load + answer) | 2.5 s (time to first token 1.7 s) |
| 20 back-to-back RAG queries (8 excerpts each) | 138 s, no slowdown: output 41.3 → 41.5 tok/s, time to first token 0.89 → 0.88 s |
| NPU temperature across that run | 65.4 → 68.6 °C |
| Server memory (RSS) | 389 MB; whole system 2.4 GB used of 32 GB |

## Embedding model (CPU)

`LFM2.5-Embedding-350M` Q8_0 under llama.cpp b12374 on 4 CPU threads, run over the real indexed pages (167 with text) and the 32 test questions. Raw data: [`bench/embed_results.json`](../bench/embed_results.json). Script: [`bench/bench_embed.py`](../bench/bench_embed.py) (about 1 minute).

| Metric | Value |
|---|---|
| Embed one question | 44 ms median, 72 ms p95 |
| Page size (tokens) | median 488, p95 1,414, max 2,019 (all within the 2,048 limit) |
| Embed one page | 0.9 s (256–511 tokens), 1.3 s (512–1,023), 4.9 s (1,024+) |
| Throughput | about 360–400 tok/s, 0.9 pages/s. Batching 8 pages per request gives no speedup |
| Whole corpus (88.7k tokens) | about 4 minutes, estimated |
| LFM3 64-token call | 0.91 s alone, 1.56 s while pages are being embedded (+70%) |
| Server memory (RSS) | 1.0 GB; whole system 3.1 GB used |

## What this means for the app

- **Retrieve 4–8 excerpts.** That gives a first token in 0.5–0.9 s. Each extra excerpt adds about 0.1 s.
- **Stream the answer and keep it short.** At 41 tok/s, a 150-token answer takes about 3.5 s after the first token.
- **Warm the model at startup.** A cold first request costs about 2.5 s. After 30 minutes idle the model unloads and that cost comes back.
- **Use the prefilled completion template from [model-usage.md](model-usage.md).** With manual excerpts in a chat request, `enable_think: false` does not stop the model from writing out its reasoning, which uses up the answer tokens. The prefilled template gives direct answers with page citations at the same speed.
- **Not measured:** power draw (the board has no power sensor), and the end-to-end time with retrieval included. Embedding a question adds about 44 ms on top of the LFM3 numbers.
- **Don't embed pages while answering.** Bulk embedding on the CPU slows LFM3 by about 70%, so run it at ingest time only. A single question embedding is too short to matter.
