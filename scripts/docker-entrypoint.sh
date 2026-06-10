#!/bin/bash

set -euo pipefail

# SSM_PARAMETER_PATH or PARAMETER_PATH (backward compat) enables SSM loading in Python
export SSM_PARAMETER_PATH="${SSM_PARAMETER_PATH:-${PARAMETER_PATH:-}}"

exec python3 -m worker.main
