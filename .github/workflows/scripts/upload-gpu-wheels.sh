#!/usr/bin/env bash
set -euo pipefail

: "${CODEDEPLOY_S3_LOCATION:?CODEDEPLOY_S3_LOCATION must be set}"

PYPI_CACHE_KEY="$(cat wheels/.pypi-cache-key)"
ROMAV2_CACHE_KEY="$(cat wheels/.romav2-cache-key)"

CODEDEPLOY_S3_BUCKET="${CODEDEPLOY_S3_LOCATION%%/*}"
if [[ "${CODEDEPLOY_S3_LOCATION}" == *"/"* ]]; then
  CODEDEPLOY_S3_PREFIX="${CODEDEPLOY_S3_LOCATION#*/}"
  S3_BASE="s3://${CODEDEPLOY_S3_BUCKET}/${CODEDEPLOY_S3_PREFIX}"
else
  CODEDEPLOY_S3_PREFIX=""
  S3_BASE="s3://${CODEDEPLOY_S3_BUCKET}"
fi

echo "Local wheel directories:"
find wheels/pypi -maxdepth 1 -mindepth 1 -print | sed -n '1,5p'
find wheels/romav2 -maxdepth 1 -mindepth 1 -print | sed -n '1,5p'

if ! aws s3 ls "${S3_BASE}/wheels/${PYPI_CACHE_KEY}/" &>/dev/null; then
  echo "Uploading PyPI wheels to S3..."
  aws s3 sync wheels/pypi/ "${S3_BASE}/wheels/${PYPI_CACHE_KEY}/"
else
  echo "PyPI wheels already exist in S3, skipping upload"
fi

if ! aws s3 ls "${S3_BASE}/wheels/${ROMAV2_CACHE_KEY}/" &>/dev/null; then
  echo "Uploading romav2 wheel to S3..."
  aws s3 sync wheels/romav2/ "${S3_BASE}/wheels/${ROMAV2_CACHE_KEY}/"
else
  echo "romav2 wheel already exists in S3, skipping upload"
fi

echo "${CODEDEPLOY_S3_BUCKET}" > wheels/.s3-bucket
echo "${CODEDEPLOY_S3_PREFIX}" > wheels/.s3-prefix

echo "Wheel S3 locations:"
echo "  PyPI: ${S3_BASE}/wheels/${PYPI_CACHE_KEY}/"
echo "  romav2: ${S3_BASE}/wheels/${ROMAV2_CACHE_KEY}/"
