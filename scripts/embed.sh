#!/usr/bin/env bash
# embed.sh: start, stop, restart, or check the embedding server (llama-server --embeddings) on the IQ-9075.
#
#   embed.sh run       foreground (use a separate terminal)
#   embed.sh start     detached
#   embed.sh stop
#   embed.sh restart
#   embed.sh status
#
# LFM2.5-Embedding-350M (Q8_0) on the CPU only, on loopback port 18182, so it never competes with
# LFM3 on the NPU (geniex, port 18181). The llama.cpp build is the plain ubuntu-arm64 release: it ships
# only CPU and RPC backends, and --device none keeps everything on the CPU regardless.
# Install (once, needs network):
#   mkdir -p ~/llama.cpp ~/models
#   curl -fsSL https://github.com/ggml-org/llama.cpp/releases/download/b12374/llama-b12374-bin-ubuntu-arm64.tar.gz \
#     | tar -xz -C ~/llama.cpp
#   curl -fsSL -o ~/models/LFM2.5-Embedding-350M-Q8_0.gguf \
#     https://huggingface.co/LiquidAI/LFM2.5-Embedding-350M-GGUF/resolve/main/LFM2.5-Embedding-350M-Q8_0.gguf
# The server log goes to $EMBED_LOG (default ~/embed-serve.log); each run/start replaces it.

set -euo pipefail

PORT="${EMBED_PORT:-18182}"
LOG="${EMBED_LOG:-$HOME/embed-serve.log}"
BIN="${LLAMA_SERVER:-$HOME/llama.cpp/llama-b12374/llama-server}"
MODEL="${EMBED_MODEL:-$HOME/models/LFM2.5-Embedding-350M-Q8_0.gguf}"
THREADS="${EMBED_THREADS:-4}"   # of 8 A78C cores; leaves the rest for geniex and the app
URL="http://127.0.0.1:$PORT"

# -c 8192 instead of the model's 128k default; -b/-ub 2048 because an embedding input must fit in one
# ubatch (the default 512 would reject a full manual page). 4 slots share the 8192-token context.
ARGS=(-m "$MODEL" --embeddings --device none -t "$THREADS"
      -c 8192 -b 2048 -ub 2048 -np 4
      --host 127.0.0.1 --port "$PORT" -a LFM2.5-Embedding-350M --no-webui)

pid_on_port() {
  ss -ltnp 2>/dev/null | sed -n "s/.*127.0.0.1:$PORT .*pid=\([0-9]*\).*/\1/p" | head -1
}

up() { curl -fsS -o /dev/null -m 3 "$URL/health" 2>/dev/null; }

check() {
  [ -x "$BIN" ] || { echo "llama-server not found at $BIN (set LLAMA_SERVER)" >&2; exit 1; }
  [ -f "$MODEL" ] || { echo "model not found at $MODEL (set EMBED_MODEL)" >&2; exit 1; }
}

run() {
  check
  if up; then echo "already running on $URL (pid $(pid_on_port))"; return 0; fi
  echo "foreground embedding server on $URL (cpu, threads=$THREADS, log=$LOG)"
  "$BIN" "${ARGS[@]}" 2>&1 | tee "$LOG"
}

start() {
  check
  if up; then echo "already running on $URL (pid $(pid_on_port))"; return 0; fi
  nohup "$BIN" "${ARGS[@]}" > "$LOG" 2>&1 < /dev/null &
  for _ in $(seq 1 60); do
    if up; then echo "started on $URL (pid $(pid_on_port), cpu, threads=$THREADS, log=$LOG)"; return 0; fi
    sleep 1
  done
  echo "llama-server did not answer within 60 s; see $LOG" >&2
  exit 1
}

stop() {
  local pid args
  pid="$(pid_on_port)"
  if [ -z "$pid" ]; then echo "not running"; return 0; fi
  args="$(ps -p "$pid" -o args=)"
  case "$args" in *llama-server*) ;; *) echo "refusing to stop non-llama-server pid $pid: $args" >&2; exit 1 ;; esac
  kill "$pid"
  for _ in $(seq 1 15); do
    [ -z "$(pid_on_port)" ] && { echo "stopped (pid $pid)"; return 0; }
    sleep 1
  done
  echo "pid $pid did not exit; try: kill -9 $pid" >&2
  exit 1
}

status() {
  if up; then
    echo "running on $URL (pid $(pid_on_port))"
    curl -s -m 5 "$URL/v1/models" | python3 -c 'import json,sys; [print("  model:", m["id"]) for m in json.load(sys.stdin)["data"]]'
  else
    echo "not running"
    return 3
  fi
}

cmd="${1:-status}"
case "$cmd" in
  run) run ;;
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  --help|-h) echo "usage: embed.sh run|start|stop|restart|status" ;;
  *) echo "usage: embed.sh run|start|stop|restart|status" >&2; exit 64 ;;
esac
