#!/bin/sh
set -eu

/opt/qmr-worker/.venv/bin/python training/src/evaluate_threshold_baseline.py \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --output-dir training/runs/threshold_baseline \
  --s3-backup-uri s3://dev-qmr-assets/qmr-worker/training/runs/threshold_baseline
