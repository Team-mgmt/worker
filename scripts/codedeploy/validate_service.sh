#!/bin/bash
set -euo pipefail

SERVICE_NAME="qmr-worker"
HEALTH_ENDPOINT="http://localhost:8080/health"
MAX_RETRIES=150
RETRY_INTERVAL=2

echo "Validating ${SERVICE_NAME} service..."

# Check if service is running
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "ERROR: ${SERVICE_NAME} service is not running."
    systemctl status "${SERVICE_NAME}" || true
    exit 1
fi

# Wait for health endpoint
echo "Waiting for health endpoint..."
for ((i = 1; i <= MAX_RETRIES; i++)); do
    if curl -sf "${HEALTH_ENDPOINT}" >/dev/null 2>&1; then
        echo "Health check passed after ${i} attempts."
        exit 0
    fi
    echo "Attempt ${i}/${MAX_RETRIES}: Health check failed, retrying in ${RETRY_INTERVAL}s..."
    sleep "${RETRY_INTERVAL}"
done

echo "ERROR: Health check failed after ${MAX_RETRIES} attempts."
systemctl status "${SERVICE_NAME}" || true
journalctl -u "${SERVICE_NAME}" --no-pager -n 50 || true
exit 1
