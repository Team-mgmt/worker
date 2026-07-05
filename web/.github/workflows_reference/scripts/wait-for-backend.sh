#!/usr/bin/env bash

set -euo pipefail

for attempt in $(seq 1 30); do
  if curl -sf http://localhost:4000/; then
    exit 0
  fi

  if [ "$attempt" -eq 30 ]; then
    echo "Backend failed to start"
    exit 1
  fi

  sleep 2
done
