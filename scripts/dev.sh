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
.venv/bin/uvicorn ytsum.api:app --host 127.0.0.1 --port 8765 &
api_pid=$!

cleanup() {
  kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

npm run dev
