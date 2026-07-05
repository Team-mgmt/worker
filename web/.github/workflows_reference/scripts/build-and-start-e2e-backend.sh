#!/usr/bin/env bash

set -euo pipefail

log_dir="$RUNNER_TEMP/e2e-logs"

mkdir -p "$log_dir"

pnpm turbo --env-mode=loose --filter @qmr/backend build
pnpm --filter @qmr/backend start > "$log_dir/backend.stdout.log" 2> "$log_dir/backend.stderr.log" &
echo "$!" > "$log_dir/backend.pid"
