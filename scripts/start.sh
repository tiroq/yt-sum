#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$project_dir/.runtime"
pid_file="$runtime_dir/yt-sum-dev.pid"
log_file="$runtime_dir/yt-sum-dev.log"

if [[ -f "$pid_file" ]]; then
  pid="$(<"$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "YT Sum is already running (PID $pid)."
    exit 0
  fi
  rm -f "$pid_file"
fi

mkdir -p "$runtime_dir"
cd "$project_dir"
nohup ./scripts/dev.sh >"$log_file" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$pid_file"
echo "YT Sum started (PID $pid)."
echo "Log: $log_file"
