# Demo guide

Ask a question about the equipment manuals on the IQ-9075 board and get a short answer with the manual page, in about 3–6 s, fully offline.

## 1. Get a terminal on the board

- **SSH** (only while Wi-Fi is on):
  ```bash
  ssh -i ~/.ssh/iq9_ed25519 ubuntu@10.5.55.215
  ```
- **Serial console** (keeps working with Wi-Fi off; use this for the demo): micro-USB debug port → laptop.
  ```bash
  screen /dev/ttyUSB1 115200   # log in as ubuntu / liquidxqualcomm; quit with Ctrl-A then K
  ```

## 2. Before the demo (10 minutes before)

- [ ] Power the board (12 V into JPWR) and log in.
- [ ] Model server running on the NPU: `bash ~/iq9/serve.sh status` (look for HTP0). If down: `bash ~/iq9/serve.sh start`. To stop it use `serve.sh stop`, never `pkill`.
- [ ] Model loaded: `curl -s 127.0.0.1:18181/v1/models` lists `LFM3-1.7B-GGUF:Q4_0`.
- [ ] `cd ~/offline_assistant` and ask one warm-up question so the first answer on stage isn't a cold start.
- [ ] Make the terminal font large.

## 3. Ask questions

The code and the search index are in `~/offline_assistant` on the board. It needs only the board's Python, no extra packages.

```bash
cd ~/offline_assistant
python3 -m assistant "What does fault F.OF mean on the Lenze drive?"
```

Output: the answer, then **Sources** (manual, PDF page, printed page, section heading, match score), then timings. If the model didn't cite pages inline, a `(From: …)` line names the pages it was given.

Optional shortcut, so `ask "..."` works from any folder (add to `~/.bashrc` once):

```bash
ask() { (cd ~/offline_assistant && python3 -m assistant "$@"); }
```

Flags: `--mock` (no model; shows the matched page text), `--json` (raw output), `-k N` (pages to retrieve).

## 4. Demo script

Every row was checked on the board on 2026-11-13. Times are the LLM call; search takes about 2 ms.

| # | Question | What you should see | Page | Time |
|---|---|---|---|---|
| 1 | What does fault F.OF mean on the Lenze drive? | Output (transistor) fault: short circuit, acceleration too short, motor overload | lenze_smvector_vfd p. 45 (printed 43) | 5.2 s |
| 2 | What is the tire pressure for the compressor? | 65 psi cold, tire ST225/75D15 | doosan p. 31 (printed 29) | 2.9 s |
| 3 | How do I prime the pump? | Close outlet valve, open inlet, remove priming plug, fill, refit | grundfos p. 26 | 4.2 s |
| 4 | What does fault code 5 mean on the compressor? | Low engine oil pressure shutdown (12 psi) | doosan p. 40 (printed 38) | 4.5 s |
| 5 | The pump motor does not start, what should I check? | Power supply, fuses, breaker, thermal protection (section 10.1) | grundfos p. 35 | 5.2 s |
| 6 | What is the capital of France? | Not found in the manuals. | — | 2.0 s |

Suggested order:

1. Q1 (fault code, the headline case)
2. Q3 (a procedure)
3. Q5 (a plain-language problem)
4. Q6 (it refuses instead of guessing)
5. Turn Wi-Fi off with `sudo nmcli radio wifi off`, then ask Q2 to show it works offline. Turn it back on afterwards with `sudo nmcli radio wifi on`.

## 5. What to say

Technicians lose time digging through long manuals, often with no signal. This answers from their own manuals, on the device, and always shows the page.

1. **Ingest (done ahead of time):** three real manuals (Doosan air compressor, Grundfos pump, Lenze drive) are split into pages, tables included, and indexed in a local SQLite full-text index.
2. **Search (~2 ms):** the question's keywords are matched against every page; the best 3 pages are picked.
3. **Answer (3–5 s):** one call to Liquid AI's LFM3 1.7B on the board's NPU, told to answer only from those pages and cite them.
4. **Refuse:** if nothing matches, or the model finds no answer in the pages, it says "Not found in the manuals" instead of guessing.

Nothing leaves the board: model, index and manuals all live on it, and it works with Wi-Fi off.

Next steps if asked: search by meaning with an embedding model, which is already running on the board's CPU. That way "won't start" finds "fails to energize". After that, photos of nameplates and fault screens, then voice.

## 6. Avoid on stage

- **Off-topic questions that share words with the manuals.** "How do I fix the brakes on my car?" gets answered from the drive's braking settings instead of being refused. Use Q6 to show a refusal.
- **Paraphrases far from the manual's wording.** Search is keyword-only for now; about 4 in 10 such questions miss the right page.
- **"How often should I change the compressor oil?"** The answer is muddled from the maintenance schedule table.
- **"How do I reset the drive to factory settings?"** The answer is right (P199 = 2) but can stop mid-list at the length cap.
- **Long open-ended questions.** Answers are capped at 150 tokens and can end mid-sentence.

If an answer looks off, point at the Sources list: the right page is usually there even when the wording is rough.

## 7. If something breaks

| Symptom | Fix |
|---|---|
| `LLM error: URLError … Connection refused` | Model server is down: `bash ~/iq9/serve.sh start`, then check with `serve.sh status`. |
| First answer is much slower | Cold start. Do the warm-up question before going on stage. |
| `No index at data/index.db` | Run from `~/offline_assistant`; the index is `data/index.db` there. |
| Need an answer with no model at all | Add `--mock`. |
| Can't SSH after Wi-Fi off | Expected. Use the serial console. |

## 8. Updating the board

The index on the board is a copy built on the laptop. After changing code or adding manuals, run `ingest` on the laptop, then copy everything over again:

```bash
rsync -az -e "ssh -i ~/.ssh/iq9_ed25519" assistant config.toml data ubuntu@10.5.55.215:offline_assistant/
```
