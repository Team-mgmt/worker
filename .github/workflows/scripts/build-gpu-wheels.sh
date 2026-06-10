#!/usr/bin/env bash
set -euo pipefail

: "${ARCH:?ARCH must be set}"
: "${PYPI_HASH:?PYPI_HASH must be set}"
: "${ROMAV2_HASH:?ROMAV2_HASH must be set}"

mkdir -p wheels/pypi wheels/romav2

PYPI_CACHE_KEY="pypi-${ARCH}-${PYPI_HASH}"
if [[ ! -f "wheels/.pypi-cache-key" ]] || [[ "$(cat wheels/.pypi-cache-key)" != "${PYPI_CACHE_KEY}" ]]; then
  echo "Building PyPI wheels..."
  rm -rf wheels/pypi/*
  pip wheel --wheel-dir wheels/pypi -r requirements.txt
  echo "${PYPI_CACHE_KEY}" > wheels/.pypi-cache-key
else
  echo "PyPI wheels cache hit, skipping build"
fi

ROMAV2_CACHE_KEY="romav2-${ARCH}-${ROMAV2_HASH}"
if [[ ! -f "wheels/.romav2-cache-key" ]] || [[ "$(cat wheels/.romav2-cache-key)" != "${ROMAV2_CACHE_KEY}" ]]; then
  echo "Building romav2 wheel..."
  rm -rf wheels/romav2/*
  pip wheel --no-deps --wheel-dir wheels/romav2 ./vendor/romav2
  echo "${ROMAV2_CACHE_KEY}" > wheels/.romav2-cache-key
else
  echo "romav2 wheel cache hit, skipping build"
fi

ROMAV2_GIT_HASH="$(cd vendor/romav2 && git rev-parse --short HEAD)"
echo "${ROMAV2_GIT_HASH}" > wheels/.romav2-git-hash
echo "romav2 git hash: ${ROMAV2_GIT_HASH}"
