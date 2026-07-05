#!/usr/bin/env bash

set -euo pipefail

CURRENT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABASE_DIRECTORY="$(cd "${CURRENT_DIRECTORY}/.." && pwd)"

cd "${DATABASE_DIRECTORY}" || exit 1

if [[ -f src/generated/.docker ]]; then
  exit 0
fi

# `prisma generate` only validates datasource URLs; it does not connect to the
# database. Use local placeholders so frontend builds do not need DB secrets.
export DATABASE_URL="${DATABASE_URL:-postgresql://shelfalign:shelfalign@localhost:5432/shelfalign}"
export SHADOWDB_URL="${SHADOWDB_URL:-postgresql://shelfalign:shelfalign@localhost:5432/shelfalign_shadow}"

pnpm prisma generate
