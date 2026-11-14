# Offline Maintenance Assistant

Ask a question about your equipment manuals and get a short answer with the exact manual page. It runs entirely on a Qualcomm Dragonwing IQ-9075 with Liquid AI's LFM3-1.7B on the NPU. No network is needed and nothing leaves the device.

```bash
python3 -m assistant "What does fault F.OF mean on the Lenze drive?"
```

The output is a short answer with inline citations like `[lenze_smvector_vfd, p. 45]`. After it come the source pages, each with its section heading and match score, and then the search and LLM times.

## The problem

- Field and plant technicians spend a lot of time digging through long PDF manuals. One survey put it at about 18 minutes of every hour on site.
- They often search where there is no signal: basements, mechanical rooms, factory floors, remote sites.
- Many sites don't allow plant data or documents to leave the premises, so cloud AI tools aren't an option.
- Ctrl-F fails when the technician's words don't match the manual's ("won't start" vs "fails to energize").

## Why this isn't a cloud API call

- **No network where the work happens.** The demo runs with Wi-Fi switched off (`sudo nmcli radio wifi off`). The model, the search index and the manuals are all on the board.
- **Data stays on site.** Manuals, questions and answers never leave the device. That matters for sites that don't allow outbound data.
- **Flat cost.** Once the manuals are on the device, an answer costs nothing per question, however many technicians use it.
- **Fast enough to use with a tool in your hand.** Search takes about 2 ms and the first answer token arrives in under 1 s. A full cited answer takes about 3–5 s on the NPU.

## What works today (phase 1)

```
Ingest (once):  PDF ─► text per page, tables included (pdfplumber) ─► SQLite FTS5 index
Ask:            question ─► BM25 keyword search (~2 ms) ─► top 3 pages
                         ─► one capped LFM3-1.7B call on the NPU (~3–5 s) ─► answer + [manual, p. N]
                         └► nothing relevant found ─► "Not found in the manuals." (no LLM call)
```

- **Ingest** (`assistant/ingest.py`)
  - Reads each PDF page by page. Tables are written out row by row with their column headers, two-column pages are read in order, and repeated headers and footers are stripped.
  - Each page is stored with its section heading, its PDF page number and the page number printed on it, which can differ by 2.
  - Each page has a stable ID (file hash plus page number). A manual that hasn't changed is skipped on re-ingest, and pages with no text are logged.
- **Search** (`assistant/search.py`)
  - SQLite FTS5 with Porter stemming, ranked by BM25, with headings weighted 2×.
  - Filler words are dropped and the remaining terms are ORed, so one missing word doesn't empty the results.
  - Fault codes like `F.OF` or `code 5` are matched as exact phrases.
- **Answer** (`assistant/answer.py`)
  - Makes one LFM3 call with the top 3 pages, each labelled `[manual, p. N]`. Long pages are cut down to the part that best matches the question.
  - Every call sets `max_completion_tokens` (150) and `enable_think: false`.
  - Citations to pages the model wasn't given are removed. If no valid citation is left, the source pages are appended so every answer still names its source.
  - If no page scores above the threshold, or the model says the pages don't contain the answer, the reply is "Not found in the manuals." instead of a guess.
- **Runtime dependencies:** answering needs only Python's standard library, so it runs on the board's stock Python. Ingest also needs `pdfplumber`, with `pypdf` as a fallback.

### Test data

Three public manuals with different layouts, in `manuals/`:

| Manual | Equipment | Pages |
|---|---|---|
| Doosan P250WJD | Diesel portable air compressor | 64 |
| Grundfos CR/CRI/CRN | Vertical multistage centrifugal pump | 59 |
| Lenze SMVector | Variable frequency drive | 48 |

171 pages in total, 167 of them with text. The other 4 are divider pages, which ingest logs. The index is 0.9 MB.

## Results

### Retrieval

We wrote 32 test questions (`eval/questions.json`) with the expected manual and page for each: 28 the manuals can answer and 4 they can't. Run with `python eval/run_eval.py`.

| Question type | Expected page in top 3 |
|---|---|
| Fault codes | 6/6 (100%) |
| Spanning several manuals | 3/3 (100%) |
| Worded like the manual | 6/7 (86%) |
| Paraphrased | 7/12 (58%) |
| **All answerable questions** | **22/28 (79%)**, ranked first for 13/28 (46%) |

Paraphrased questions are the weak spot, as expected for keyword search. Phase 2 adds search by meaning to fix this.

### End-to-end on the board

These questions were run through the real pipeline on the IQ-9075 on 2026-11-13. Times are for the LLM call; search adds about 2 ms.

| Question | Answer | Cited page | Time |
|---|---|---|---|
| What does fault F.OF mean on the Lenze drive? | Output (transistor) fault: short circuit, acceleration too short, motor overload | Lenze p. 45 | 5.2 s |
| What is the tire pressure for the compressor? | 65 psi cold, tire ST225/75D15 | Doosan p. 31 | 2.9 s |
| How do I prime the pump? | Close outlet valve, open inlet, remove priming plug, fill, refit | Grundfos p. 26 | 4.2 s |
| What does fault code 5 mean on the compressor? | Low engine oil pressure shutdown (12 psi) | Doosan p. 40 | 4.5 s |
| The pump motor does not start, what should I check? | Power supply, fuses, breaker, thermal protection (section 10.1) | Grundfos p. 35 | 5.2 s |
| What is the capital of France? | Not found in the manuals. | none | 2.0 s |

**Unit tests:** 30 pass (`pytest`). They cover ingest of a real manual, search, citation checking, and the LLM client against a fake GenieX server, including the token cap, `enable_think`, the retry and the server being down.

### Model benchmarks

These numbers are from the IQ-9075 itself. Full method and raw data: [docs/benchmark.md](docs/benchmark.md), [`bench/results.json`](bench/results.json), [`bench/embed_results.json`](bench/embed_results.json).

**LFM3-1.7B Q4_0 on the Hexagon NPU** (GenieX v0.10.0, medians of 5 runs):

| Prompt | Prompt tokens | Time to first token | Total for a 256-token answer | Output speed |
|---|---|---|---|---|
| Question only | 82 | 0.11 s | 1.6 s (64 tokens) | 41.5 tok/s |
| 4 excerpts | 570 | 0.50 s | 6.7 s | 41.6 tok/s |
| 8 excerpts | 1,050 | 0.88 s | 7.0 s | 41.7 tok/s |
| 16 excerpts | 2,010 | 1.60 s | 8.0 s | 40.3 tok/s |
| 28 excerpts (near the 4k context limit) | 3,450 | 2.75 s | 9.2 s | 38.6 tok/s |

| Metric | Value |
|---|---|
| Prompt processing | 1,180–1,270 tok/s |
| Server start / first request after start | 1.1 s / 2.5 s |
| 20 back-to-back RAG queries | 138 s with no slowdown (41.3 → 41.5 tok/s) |
| NPU temperature over those 20 queries | 65.4 → 68.6 °C |
| Model server memory | 389 MB (whole system 2.4 GB of 32 GB) |

**LFM2.5-Embedding-350M Q8_0 on the CPU** (llama.cpp, 4 threads, run over the 167 real pages). It runs on the CPU so it doesn't compete with LFM3 for the NPU.

| Metric | Value |
|---|---|
| Embed one question | 44 ms median, 72 ms p95 |
| Embed one page | 0.9 s (median page, 488 tokens) |
| Whole corpus (88.7k tokens) | about 4 min, at ingest time only |
| Memory | 1.0 GB |
| Effect on LFM3 while bulk-embedding | +70% latency, so pages are embedded at ingest and never while answering |

**What we changed because of the benchmarks:**
- Retrieve 3 pages instead of more. Each extra excerpt adds about 0.1 s before the first token.
- Cap answers at 150 tokens. That brought a typical answer from about 6.5 s to about 5 s.
- Send a warm-up question before the demo, because a cold first request costs about 2.5 s.
- Embed pages only at ingest time, because bulk embedding slows the answer model by about 70%.

## Run it

### On the IQ-9075 (the demo setup)

You need GenieX serving `LiquidAI/LFM3-1.7B-GGUF:Q4_0` on `127.0.0.1:18181`. See [docs/model-usage.md](docs/model-usage.md).

```bash
cd ~/offline_assistant
python3 -m assistant "What does fault F.OF mean on the Lenze drive?"
python3 -m assistant --json "How do I prime the pump?"   # raw output: citations, scores, timings
```

The board doesn't need `pdfplumber`. Build the index on the laptop and copy `assistant/`, `config.toml` and `data/` across (see [docs/demo.md](docs/demo.md)).

### On a laptop, with no board and no model

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ingest                                   # index manuals/ into data/index.db
.venv/bin/ask --mock "How do I prime the pump?"    # mock LLM: shows the matched page lines
.venv/bin/python eval/run_eval.py                  # retrieval eval
.venv/bin/pytest                                   # unit tests
```

Settings live in `config.toml`. Any key can be overridden with an `OA_<KEY>` environment variable, for example `OA_LLM_URL` or `OA_LLM_MOCK=1`.

### Demo

[docs/demo.md](docs/demo.md) has the pre-demo checklist, the question script, and what to do if something breaks. In short: run a warm-up question, ask the fault-code, procedure and "won't start" questions, show the refusal, then switch Wi-Fi off from the serial console and ask again.

## Known limits

- **Search is keyword-only.** About 4 in 10 paraphrased questions miss the right page.
- **Off-topic questions that share words with a manual** (for example "fix the brakes on my car") can get an answer from loosely related pages instead of a refusal.
- **Answers capped at 150 tokens** sometimes end mid-list.
- **Answer quality has only been checked by hand**, on the demo questions above. A full run of the 32 test questions against the real LFM is still to do.
- **No OCR.** Scanned manuals aren't indexed yet.

## Roadmap

- **Phase 2, search by meaning:** the embedding model is already running and benchmarked on the board's CPU. Next is embedding each page at ingest and combining BM25 and vector results with reciprocal rank fusion. That way "won't start" finds "fails to energize".
- **V2, images:** photograph a nameplate, fault screen or part to find the equipment or fault code.
- **V3, voice:** hands-free questions and spoken answers.

## Repository layout

```
assistant/   ingest.py, search.py, answer.py, llm.py (GenieX client), cli.py
eval/        questions.json (32 questions with expected pages), run_eval.py
bench/       bench_lfm.py, bench_embed.py and their raw results
docs/        benchmark.md, model-usage.md, demo.md
manuals/     the three test manuals and their sources
scripts/     embed.sh (start/stop the embedding server on the board)
tests/       unit tests
```

## Hardware and models

- Qualcomm Dragonwing IQ-9075 EVK: QCS9075, Hexagon v73 NPU, 36 GB RAM, Ubuntu 24.04
- Answer model: [LiquidAI/LFM3-1.7B-GGUF](https://huggingface.co/LiquidAI) Q4_0 on the NPU through GenieX
- Embedding model (phase 2): LiquidAI/LFM2.5-Embedding-350M-GGUF Q8_0 on the CPU through llama.cpp
