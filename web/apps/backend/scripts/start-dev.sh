#!/bin/bash

set -euo pipefail

# Load environment variables from .env files

CURRENT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${CURRENT_DIRECTORY}/../../.." && pwd)"

export SENTRY_LOCAL=true
export NODE_EXTRA_CA_CERTS="${PROJECT_DIRECTORY}/certs/aws-rds.crt"

nest start --watch --watchAssets
