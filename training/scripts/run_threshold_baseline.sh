#!/bin/sh
set -eu

/opt/shelfalign-worker/.venv/bin/python training/src/evaluate_threshold_baseline.py \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --output-dir training/runs/threshold_baseline \
  --s3-backup-uri s3://dev-shelfalign-assets/shelfalign-worker/training/runs/threshold_baseline
