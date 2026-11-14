# Calling the model

The answer model, `LiquidAI/LFM3-1.7B-GGUF:Q4_0`, is served by GenieX on the board at `http://127.0.0.1:18181`. The API is OpenAI-compatible. Only code running on the board can reach it.

## Server

```bash
bash ~/iq9/serve.sh status   # running? on the NPU (look for HTP0)?
bash ~/iq9/serve.sh start    # start
bash ~/iq9/serve.sh stop     # stop (never pkill)
```

After 30 minutes without requests the model is unloaded. The next request reloads it, which takes about 2 s. Send one short request before a demo.

## Request

```bash
curl -s http://127.0.0.1:18181/v1/chat/completions -H "Content-Type: application/json" -d '{
  "model": "LiquidAI/LFM3-1.7B-GGUF:Q4_0",
  "messages": [{"role": "user", "content": "Why would a pump lose prime?"}],
  "max_completion_tokens": 256,
  "enable_think": false,
  "stream": false
}'
```

The answer is in `choices[0].message.content`.

## Python

```python
import requests

def ask(question: str) -> str:
    r = requests.post("http://127.0.0.1:18181/v1/chat/completions", timeout=60, json={
        "model": "LiquidAI/LFM3-1.7B-GGUF:Q4_0",
        "messages": [{"role": "user", "content": question}],
        "max_completion_tokens": 256,
        "enable_think": False,
        "stream": False,
    })
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
```

## Answering from manual excerpts (RAG)

When the prompt includes manual excerpts, the chat endpoint can still produce a long stretch of reasoning before the answer. Use `/v1/completions` instead, with the empty think block already written into the prompt. The model then answers directly:

```python
def ask_rag(question: str, excerpts: str) -> str:
    system = ("You are a maintenance assistant. Answer only from the manual excerpts. "
              "Cite the page for each fact as [p. N]. If the excerpts do not cover the question, say so.")
    prompt = (f"<|startoftext|><|im_start|>system\n{system}<|im_end|>\n"
              f"<|im_start|>user\nManual excerpts:\n{excerpts}\n\nQuestion: {question}<|im_end|>\n"
              "<|im_start|>assistant\n<think>\n\n</think>\n\n")
    r = requests.post("http://127.0.0.1:18181/v1/completions", timeout=60, json={
        "model": "LiquidAI/LFM3-1.7B-GGUF:Q4_0",
        "prompt": prompt,
        "max_tokens": 256,
        "stream": False,
    })
    r.raise_for_status()
    return r.json()["choices"][0]["text"]
```

For speed numbers, see [benchmark.md](benchmark.md).

## Rules

- Always set `max_completion_tokens`. Without it, a reply can run to 2048 tokens.
- Always set `enable_think: false`. Otherwise the model writes out its reasoning before answering.
- Check that the reply isn't empty before showing it. When streaming chat responses, drop the leading `</think>` chunk.
- Keep the server on `127.0.0.1`. The phone talks to our app, and our app talks to the model.

## Embedding model (CPU)

`LFM2.5-Embedding-350M` (Q8_0 GGUF) runs under `llama-server --embeddings` at `http://127.0.0.1:18182`, on the CPU only (4 threads), so it never competes with LFM3 for the NPU. The llama.cpp build (`~/llama.cpp/llama-b12374`, the plain `ubuntu-arm64` release) has no NPU or GPU backend, and the server runs with `--device none`. Model file: `~/models/LFM2.5-Embedding-350M-Q8_0.gguf`.

```bash
bash ~/iq9/embed.sh status   # running?
bash ~/iq9/embed.sh start    # start (detached, log ~/embed-serve.log)
bash ~/iq9/embed.sh stop     # stop
```

The script lives in the repo at `scripts/embed.sh`, with install steps in its header.

```bash
curl -s http://127.0.0.1:18182/v1/embeddings -H "Content-Type: application/json" \
  -d '{"input": ["query: pump will not start", "document: If the motor fails to energize, ..."]}'
```

- Prefix questions with `query: ` and pages with `document: `. The model is asymmetric, so leaving the prefixes off makes results worse.
- The vectors have 1024 dimensions and are already L2-normalized, so a dot product gives the cosine similarity.
- Each input can be up to 2048 tokens. A full 2500-character page is about 770 tokens.
- Measured on the board: about 360–400 tok/s (about 1 s for a typical page) and 44 ms per question. Bulk embedding slows LFM3 by about 70%, so embed pages at ingest time. See [benchmark.md](benchmark.md).

## From the laptop (development only)

```bash
ssh -i ~/.ssh/iq9_ed25519 -N -L 18181:127.0.0.1:18181 -L 18182:127.0.0.1:18182 ubuntu@<board-ip>
```

Then use `http://127.0.0.1:18181` (LLM) and `http://127.0.0.1:18182` (embeddings) on the laptop as above.
