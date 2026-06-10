#!/bin/bash

SCRIPT_DIRECTORY="$(dirname "$0")"
CURRENT_DIRECTORY="$(realpath "${PWD}/${SCRIPT_DIRECTORY}")"
PROJECT_DIRECTORY="$(realpath "${CURRENT_DIRECTORY}"/../)"

if [[ -f "${PROJECT_DIRECTORY}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${PROJECT_DIRECTORY}/.env"
  set +a
fi

if [[ -z "${DATABASE_PASS:-}" && -n "${DATABASE_SECRET_ID:-}" ]]; then
  echo "Retrieving database credentials from AWS Secrets Manager..."
  DATABASE_CREDENTIALS="$(aws secretsmanager get-secret-value --secret-id "${DATABASE_SECRET_ID}" --query 'SecretString' --output text)"
  DATABASE_USER="$(echo "${DATABASE_CREDENTIALS}" | jq -r '.username')"
  DATABASE_PASS="$(echo "${DATABASE_CREDENTIALS}" | jq -r '.password | @uri')"
  echo
fi

if [[ -z "${DATABASE_PASS}" ]]; then
  echo "Generating temporary database authentication token using AWS RDS IAM authentication..."
  DATABASE_PASS="$(aws rds generate-db-auth-token --hostname "${DATABASE_HOST}" --port "${DATABASE_PORT:-5432}" --region "${AWS_REGION:-$(aws configure get region)}" --username "${DATABASE_USER}")"
  DATABASE_FLAGS="sslmode=require"
fi

: "${DATABASE_HOST:?DATABASE_HOST must be set}"
: "${DATABASE_NAME:?DATABASE_NAME must be set}"
: "${DATABASE_PASS:?DATABASE_PASS must be set}"
: "${DATABASE_USER:?DATABASE_USER must be set}"

export DATABASE_URL="postgresql+psycopg://${DATABASE_USER}:${DATABASE_PASS}@${DATABASE_HOST}:${DATABASE_PORT:-5432}/${DATABASE_NAME}?${DATABASE_FLAGS:-}"

if [[ "${1:-}" == "--silent" ]]; then
  shift
else
  echo "Working on database at ${DATABASE_HOST}" 1>&2
  read -rp "Press enter to continue..."
fi

mkdir -p "${CURRENT_DIRECTORY}/../worker/generated"
uv run sqlacodegen "${DATABASE_URL}" --generator declarative_snake > "${CURRENT_DIRECTORY}/../worker/generated/models.py"
