#!/bin/sh
set -eu

/opt/shelfalign-worker/.venv/bin/python training/src/train_tabular_ml.py \
  --train-csv training/manifests/splits/project-2-problem-train.csv \
  --val-csv training/manifests/splits/project-2-problem-val.csv \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --output-dir training/runs/random_forest \
  --model random_forest \
  --s3-backup-uri s3://dev-shelfalign-assets/shelfalign-worker/training/runs/random_forest
