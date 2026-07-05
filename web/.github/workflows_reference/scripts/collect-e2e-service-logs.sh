#!/usr/bin/env bash

set -euo pipefail

log_dir="$RUNNER_TEMP/e2e-logs"

mkdir -p "$log_dir"

if [ -f "$log_dir/worker.pid" ]; then
  worker_pid="$(cat "$log_dir/worker.pid")"
  ps -p "$worker_pid" -o pid,ppid,stat,etime,cmd > "$log_dir/worker-process.txt" || true
  kill "$worker_pid" 2>/dev/null || true
else
  echo "Worker PID file was not found" > "$log_dir/worker-process.txt"
  touch "$log_dir/worker.stdout.log" "$log_dir/worker.stderr.log"
fi

docker ps -a > "$log_dir/docker-ps.txt" || true

if [ -f "$log_dir/backend.pid" ]; then
  backend_pid="$(cat "$log_dir/backend.pid")"
  ps -p "$backend_pid" -o pid,ppid,stat,etime,cmd > "$log_dir/backend-process.txt" || true
else
  echo "Backend PID file was not found" > "$log_dir/backend-process.txt"
fi
