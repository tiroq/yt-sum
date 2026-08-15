#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
if [[ -z "$node_major" || "$node_major" -lt 22 ]]; then
  bundled_node_dir="/Users/mysterx/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
  if [[ -x "$bundled_node_dir/node" ]]; then
    export PATH="$bundled_node_dir:$PATH"
  else
    echo "YT Sum requires Node.js 22.13 or newer." >&2
    exit 1
  fi
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

if ! .venv/bin/python -c 'import fastapi, yt_dlp' 2>/dev/null; then
  .venv/bin/python -m pip install -e '.[dev]'
fi
run_api() {
  while true; do
    YTSUM_RESTART_ALLOWED=1 YTSUM_SHUTDOWN_ALLOWED=1 YTSUM_SUPERVISOR_PID=$$ .venv/bin/uvicorn ytsum.api:app --host 127.0.0.1 --port 8765
    echo "YT Sum API stopped; restarting in one second."
    sleep 1
  done
}
run_api &
api_pid=$!

npm run dev &
web_pid=$!

stop_tree() {
  local parent="$1"
  local child
  while read -r child; do
    [[ -n "$child" ]] || continue
    stop_tree "$child"
  done < <(pgrep -P "$parent" 2>/dev/null || true)
  kill -TERM "$parent" 2>/dev/null || true
}

cleanup() {
  stop_tree "$api_pid"
  stop_tree "$web_pid"
}
trap cleanup EXIT INT TERM

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
