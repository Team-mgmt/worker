#!/bin/bash
set -euo pipefail

SERVICE_NAME="qmr-worker"

echo "Starting ${SERVICE_NAME} service..."

systemctl enable "${SERVICE_NAME}"
systemctl start "${SERVICE_NAME}"

echo "${SERVICE_NAME} service started."
exit 0
