#!/bin/bash

set -euo pipefail

if [[ -z "${PARAMETER_PATH:-}" ]]; then
  echo "ERROR: PARAMETER_PATH environment variable must be set."
  exit 1
fi

# Add tail slash to PARAMETER_PATH if not present
if [[ "${PARAMETER_PATH}" != */ ]]; then
  PARAMETER_PATH="${PARAMETER_PATH}/"
fi

aws ssm get-parameters-by-path --path "${PARAMETER_PATH}" --output json --with-decryption | \
  jq -r '.Parameters[] | "export \(.Name | split("/")[-1])=\(.Value)"' > /tmp/env.sh

# shellcheck source=/dev/null
source /tmp/env.sh

node /app/apps/backend/dist/main.js
