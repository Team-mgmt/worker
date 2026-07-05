#!/bin/bash

set -euo pipefail

CURRENT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${CURRENT_DIRECTORY}/../../.." && pwd)"

# Add tail slash to PARAMETER_PATH if not present
if [[ "${PARAMETER_PATH}" != */ ]]; then
  PARAMETER_PATH="${PARAMETER_PATH}/"
fi

aws ssm get-parameters-by-path --path "${PARAMETER_PATH}" --output json > /tmp/parameters.json
jq -r '.Parameters[] | "export \(.Name | split("/")[-1])=\(.Value)"' /tmp/parameters.json > /tmp/env.sh

# shellcheck source=/dev/null
source /tmp/env.sh

cd "${PROJECT_DIRECTORY}" || exit 1

pnpm install --frozen-lockfile

if [[ "${1:-}" == "staging" ]]; then
  pnpm turbo --filter @shelfalign/backoffice check-types build:staging
elif [[ "${1:-}" == "develop" ]]; then
  pnpm turbo --filter @shelfalign/backoffice check-types build:dev
else
  pnpm turbo --filter @shelfalign/backoffice check-types build
fi
