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

## Notes

- Do not install or update `qcom-adreno1`; it breaks external monitors. Prefer headless/SSH.
- The demo runs with Wi-Fi off (`sudo nmcli radio wifi off`). Keep a serial or USB-C link as the control path.
- Reference: https://github.com/heath0xFF/cleared-for-takeoff-hackathon
