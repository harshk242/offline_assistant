# AGENTS.md

## Project: offline maintenance assistant

An offline AI assistant that runs on the device and answers technicians' questions from their equipment manuals. It uses Liquid AI models and on-device retrieval (RAG). Nothing goes to the cloud.

### Problem

- Field and plant maintenance technicians lose a lot of time searching long equipment manuals. One survey put it at about 18 minutes of every hour on-site.
- They usually search with no connection: basements, mechanical rooms, factory floors, remote sites.
- Keyword search in PDFs fails when the technician's words don't match the manual's ("won't start" vs "fails to energize").
- Cloud AI tools often can't be used, either because there's no signal or because the site won't let data leave.
- The result is slower repairs, more repeat visits and lower first-time fix rates.

### Roadmap

- **V1, text search over the manuals:** manuals are loaded onto the device. The technician asks in plain language and gets a short answer plus the exact page or section it came from. Everything runs on the device, with no internet needed.
- **V2, images:** the technician photographs a nameplate, fault screen or part. The assistant identifies the equipment or fault code and returns the relevant section.
- **V3, voice:** hands-free questions and spoken answers, so the technician can keep working.

### Users

Field service technicians and plant maintenance teams using phones, rugged handhelds (like the TC53) or tablets.

### Success metrics

- Time to find the answer
- First-time fix rate
- Fewer calls to senior techs or support

### Design constraints

- Must work fully offline. No network calls at runtime: models, embeddings and the index all live on the device.
- Every answer must cite its source (manual, page or section). If the manuals don't cover a question, say so instead of guessing.
- Retrieval must match by meaning, not just keywords, so plain-language questions find the manual's technical wording.

### Scope

- Build only the RAG backend. Skip the frontend for now.
- It runs offline on the edge device, over the PDF manuals, and is used from the terminal (CLI) or through a backend API.

## Phase 1 (current): keyword search + one LFM call

Goal: get the simplest working RAG loop. Find the right pages by keyword, then have the LFM answer from those pages with a citation.

```
Ingest:  PDF → text per page (pdfplumber) → SQLite FTS5 table (manual, page, heading, text)
Query:   question → FTS5 BM25 search → top 3 pages → one capped LFM3 call → answer + [manual, p. N]
```

- **Ingest (`ingest.py`):** extract text page by page with `pdfplumber`, including tables. Store each page as a row with `manual`, `page` (1-based), the nearest section `heading`, and `text`. Give every page a stable ID (manual file hash + page number) so phase 2 can add embeddings without re-parsing. Skip a PDF that's already indexed and unchanged (hash check). Log pages with no text (likely scanned); there's no OCR in phase 1.
- **Search (`search.py`):** a single function `search(question, k=3) -> list[(manual, page, heading, text, score)]`. Use FTS5 with `tokenize='porter unicode61'` for stemming. Drop filler words and OR the remaining terms so one missing word doesn't empty the results. Rank by `bm25()`. Keep this signature fixed: phase 2 replaces only this function with hybrid search.
- **Answer (`answer.py`):** one capped LFM3 call per question, with no query rewriting. The prompt contains the top pages, each labelled `[manual, p. N]`. The model must answer briefly from those pages only and cite them. If search returns nothing above a score threshold, reply "not found in the manuals" without calling the LLM.
- **LLM:** `LiquidAI/LFM3-1.7B-GGUF:Q4_0` via `geniex serve` on the NPU (`127.0.0.1:18181`, OpenAI-compatible). Always set `max_completion_tokens` and `enable_think: false`. Read the LLM endpoint from config, with a mock option so ingest and search can be tested on the laptop without the board.
- **Interface:** CLI (`ask "question"`) first. A backend API is optional in phase 1.
- **Dependencies:** Python standard library `sqlite3` and `pdfplumber` (plus `pypdf` as a fallback). Nothing that needs the network at runtime.

### Phase 1 evaluation

- 20–30 test questions over real manuals, each with the expected manual and page(s). Include plain-language questions, fault codes and part numbers, and questions phrased differently from the manual.
- Measure the share where an expected page is in the top 3 (search quality), the share with a correct answer and citation (answer quality), and response time on the board.
- Expected weakness: questions whose wording doesn't match the manual. Phase 1 is deliberately keyword-only; the design-constraint requirement to match by meaning is met in phase 2.

### Phase 2 (next)

Add an embedding model (`LFM2.5-Embedding-350M`, on CPU) and embed each page. Make `search()` hybrid by combining BM25 and vector results (for example with reciprocal rank fusion). Later options: a reranker (`LFM2.5-ColBERT-350M`), pulling in the next page when a match runs across the page break, and splitting long pages.

## Device: Qualcomm Dragonwing IQ-9075 EVK

- SoC QCS9075, Hexagon v73 NPU, 36 GB RAM, aarch64
- OS: Ubuntu 24.04 (preinstalled; do not reflash)
- Login: `ubuntu` / `liquidxqualcomm` (shared hackathon credentials)

## Connecting from the laptop (Linux)

- **Serial console:** micro-USB debug port → laptop. Shows up as an FTDI FT4232H (`0403:6011`) with four ports; the login console is `/dev/ttyUSB1` at 115200 baud.
  ```bash
  screen /dev/ttyUSB1 115200   # user is in the dialout group, no sudo needed
  ```
- **Network:** on the board, `sudo nmcli --ask dev wifi connect '<SSID>'`, then `ip -br address` for the IP.
- **SSH:** `ssh ubuntu@<board-ip>`
- **Power:** 12 V adapter into the JPWR barrel jack.

## Model

- Answer model `LiquidAI/LFM3-1.7B-GGUF:Q4_0` runs on the board's NPU through GenieX at `http://127.0.0.1:18181`. See [docs/model-usage.md](docs/model-usage.md) for how to call it and [docs/benchmark.md](docs/benchmark.md) for benchmark numbers (latency, tok/s, cold start, memory).
- Embedding model `LiquidAI/LFM2.5-Embedding-350M-GGUF` (Q8_0) runs on the CPU only, so it doesn't compete with LFM3 for the NPU. It's served by `llama-server --embeddings` (llama.cpp b12374) at `http://127.0.0.1:18182/v1/embeddings`.
  - Start, stop or check it with `bash ~/iq9/embed.sh start|stop|status` (repo copy: `scripts/embed.sh`). It doesn't restart after a reboot.
  - Prefix questions with `query: ` and pages with `document: `. Vectors have 1024 dimensions and are already normalized (dot product = cosine). Each input can be up to 2048 tokens.
  - Speed: about 44 ms per question, about 1 s per typical page (about 4 min for the current 167 pages). Bulk embedding slows LFM3 by about 70%, so embed pages at ingest time, not while answering. See [docs/benchmark.md](docs/benchmark.md).

## Notes

- Do not install or update `qcom-adreno1`; it breaks external monitors. Prefer headless/SSH.
- The demo runs with Wi-Fi off (`sudo nmcli radio wifi off`). Keep a serial or USB-C link as the control path.
- Reference: https://github.com/heath0xFF/cleared-for-takeoff-hackathon
