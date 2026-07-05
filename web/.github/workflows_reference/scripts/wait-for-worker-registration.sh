#!/usr/bin/env bash

set -euo pipefail

export PGPASSWORD="${PGPASSWORD:-postgres}"

for attempt in $(seq 1 60); do
  worker_count="$(
    psql -h localhost -U postgres -d postgres -t \
      -c 'SELECT count(*) FROM "Worker";' 2>/dev/null | tr -d ' ' || true
  )"
  worker_count="${worker_count:-0}"

  if [ "$worker_count" -gt "0" ]; then
    echo "Worker registered in database"
    exit 0
  fi

  if [ "$attempt" -eq 60 ]; then
    echo "Worker failed to register"
    exit 1
  fi

  sleep 2
done
