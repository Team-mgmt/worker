#!/bin/sh
set -eu

./ml-venv/bin/python training/src/plot_experiment_comparison.py \
  --test-csv training/manifests/splits/project-2-problem-test.csv \
  --experiment-metrics resnet18=s3://dev-shelfalign-assets/shelfalign-worker/training/runs/resnet18/metrics.json \
  --experiment-metrics logistic_regression=s3://dev-shelfalign-assets/shelfalign-worker/training/runs/logistic_regression_no_worker_verdict/metrics.json \
  --experiment-metrics random_forest=s3://dev-shelfalign-assets/shelfalign-worker/training/runs/random_forest_no_worker_verdict/metrics.json \
  --experiment-metrics convnext_tiny=s3://dev-shelfalign-assets/shelfalign-worker/training/runs/convnext_tiny_es20_pat3/metrics.json \
  --threshold-metrics s3://dev-shelfalign-assets/shelfalign-worker/training/runs/threshold_baseline/metrics.json \
  --output-dir training/reports/experiment_comparison \
  --s3-backup-uri s3://dev-shelfalign-assets/shelfalign-worker/training/reports/experiment_comparison
