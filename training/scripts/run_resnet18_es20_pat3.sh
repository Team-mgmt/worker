#!/bin/sh
set -eu

/opt/shelfalign-worker/.venv/bin/python training/src/train.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --cache-dir training/cache \
  --output-dir training/runs/resnet18_es20_pat3 \
  --model resnet18 \
  --epochs 20 \
  --early-stopping-patience 3 \
  --early-stopping-min-delta 0.001 \
  --batch-size 32 \
  --num-workers 2 \
  --s3-backup-uri s3://dev-shelfalign-assets/shelfalign-worker/training/runs/resnet18_es20_pat3
