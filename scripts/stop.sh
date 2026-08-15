#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$project_dir/.runtime"
pid_file="$runtime_dir/yt-sum-dev.pid"

if [[ ! -f "$pid_file" ]]; then
  echo "YT Sum is not running."
  exit 0
fi

pid="$(<"$pid_file")"
rm -f "$pid_file"

if ! kill -0 "$pid" 2>/dev/null; then
  echo "YT Sum was already stopped."
  exit 0
fi

stop_tree() {
  local parent="$1"
  local child
  while read -r child; do
    [[ -n "$child" ]] || continue
    stop_tree "$child"
  done < <(pgrep -P "$parent" 2>/dev/null || true)
  kill -TERM "$parent" 2>/dev/null || true
}

stop_tree "$pid"
for _ in {1..20}; do
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.25
done
if kill -0 "$pid" 2>/dev/null; then
  kill -KILL "$pid" 2>/dev/null || true
fi
echo "YT Sum stopped."
