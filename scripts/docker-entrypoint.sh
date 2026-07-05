#!/bin/bash

set -euo pipefail

# SSM_PARAMETER_PATH or PARAMETER_PATH (backward compat) enables SSM loading in Python.
export SSM_PARAMETER_PATH="${SSM_PARAMETER_PATH:-${PARAMETER_PATH:-}}"

exec python3 -m fastapi run worker/api/server.py --host 0.0.0.0 --port 8080
