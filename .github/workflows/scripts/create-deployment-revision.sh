#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must be set}"
: "${REVISION_PREFIX:?REVISION_PREFIX must be set}"
: "${SHA_SHORT:?SHA_SHORT must be set}"

REVISION_NAME="${REVISION_PREFIX}-${SHA_SHORT}.zip"
echo "revision_name=${REVISION_NAME}" >> "$GITHUB_OUTPUT"
rm -rf qmr-web

mkdir -p /tmp/deploy
rsync_args=(-a --exclude-from=.dockerignore)
if [[ "${EXCLUDE_WHEELS:-false}" == "true" ]]; then
  rsync_args+=(
    "--exclude=wheels/pypi/*.whl"
    "--exclude=wheels/romav2/*.whl"
  )
fi
rsync "${rsync_args[@]}" . /tmp/deploy/

cd /tmp/deploy
zip -r "${GITHUB_WORKSPACE}/${REVISION_NAME}" .
