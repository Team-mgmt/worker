#!/usr/bin/env bash

CURRENT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIRECTORY="$(cd "${CURRENT_DIRECTORY}/../../.." && pwd)"

# [ ! -f "${PROJECT_DIRECTORY}/.env" ] || export $(grep -v '^#' "${PROJECT_DIRECTORY}/.env" | xargs)
if [[ -f "${PROJECT_DIRECTORY}/packages/database/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${PROJECT_DIRECTORY}/packages/database/.env"
  set +a
fi

if [[ -z "${DATABASE_PASS:-}" ]] && [[ -n "${DATABASE_SECRET_ID:-}" ]]; then
  echo "Retrieving database credentials from AWS Secrets Manager..."
  DATABASE_CREDENTIALS="$(aws secretsmanager get-secret-value --secret-id "${DATABASE_SECRET_ID}" --query 'SecretString' --output text)"
  DATABASE_USER="$(echo "${DATABASE_CREDENTIALS}" | jq -r '.username')"
  DATABASE_PASS="$(echo "${DATABASE_CREDENTIALS}" | jq -r '.password | @uri')"
  echo
fi

: "${DATABASE_HOST:?DATABASE_HOST must be set}"
: "${DATABASE_NAME:?DATABASE_NAME must be set}"
: "${DATABASE_PASS:?DATABASE_PASS must be set}"
: "${DATABASE_USER:?DATABASE_USER must be set}"

export DATABASE_URL="postgresql://${DATABASE_USER}:${DATABASE_PASS}@${DATABASE_HOST}:${DATABASE_PORT:-5432}/${DATABASE_NAME}"
export SHADOWDB_URL="postgresql://${DATABASE_USER}:${DATABASE_PASS}@${DATABASE_HOST}:${DATABASE_PORT:-5432}/${DATABASE_NAME}_shadow"

if [[ "${1:-}" = "--silent" ]]; then
  shift
else
  echo "Working on database at ${DATABASE_HOST}" 1>&2
  read -r -p "Press enter to continue..."
fi

if [[ $# -gt 0 ]]; then
  exec "$@"
fi

pnpm prisma generate
