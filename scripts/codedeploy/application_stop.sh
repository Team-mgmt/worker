#!/bin/bash
set -euo pipefail

SERVICE_NAME="shelfalign-worker"

echo "Stopping ${SERVICE_NAME} service..."

# Check if service unit exists (may not on initial deployment)
if ! systemctl cat "${SERVICE_NAME}" &>/dev/null; then
    echo "${SERVICE_NAME} service not installed yet (initial deployment)."
    exit 0
fi

if systemctl is-active --quiet "${SERVICE_NAME}"; then
    systemctl stop "${SERVICE_NAME}"
    echo "${SERVICE_NAME} service stopped."
else
    echo "${SERVICE_NAME} service is not running."
fi

exit 0
