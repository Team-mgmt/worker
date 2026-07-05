#!/usr/bin/env bash

set -euo pipefail

mkdir -p "$RUNNER_TEMP/e2e-logs"
worker_dir="$RUNNER_TEMP/qmr-worker"
worker_location="$WORKER_CODEDEPLOY_S3_LOCATION"

rm -rf "$worker_dir"
mkdir -p "$worker_dir"

if [[ "$worker_location" == s3://* ]]; then
  worker_location="${worker_location#s3://}"
fi

aws s3 cp "s3://${worker_location}" worker.zip
unzip -q worker.zip -d "$worker_dir"

printf 'worker_dir=%s\n' "$worker_dir" >> "$GITHUB_OUTPUT"
