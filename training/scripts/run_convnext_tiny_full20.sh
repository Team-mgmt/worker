#!/bin/sh
set -eu

/opt/qmr-worker/.venv/bin/python training/src/train.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache \
  --output-dir training/runs/convnext_tiny_full20 \
  --model convnext_tiny \
  --epochs 20 \
  --batch-size 16 \
  --num-workers 2 \
  --s3-backup-uri s3://dev-qmr-assets/qmr-worker/training/runs/convnext_tiny_full20
