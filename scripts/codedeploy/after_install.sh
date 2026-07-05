#!/bin/bash
set -euo pipefail

APP_DIR="/opt/shelfalign-worker"
SERVICE_USER="shelfalign-worker"
SERVICE_GROUP="shelfalign-worker"
SERVICE_NAME="shelfalign-worker"
WORKER_STORAGE_DIR="${WORKER_STORAGE_DIR:-/var/lib/shelfalign-worker}"

if [[ -f "/opt/app.conf" ]]; then
    # shellcheck source=/dev/null
    source /opt/app.conf
fi

if [[ -n "${SSM_PARAMETER_PATH:-}" ]]; then
    export SSM_PARAMETER_PATH
fi

mkdir -p "${APP_DIR}" "${WORKER_STORAGE_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}" "${WORKER_STORAGE_DIR}"

cd "${APP_DIR}"

rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --no-cache-dir -r "${APP_DIR}/requirements.txt"

touch /var/log/shelfalign-worker.log
chown "${SERVICE_USER}:${SERVICE_GROUP}" /var/log/shelfalign-worker.log
chmod 644 /var/log/shelfalign-worker.log

export APP_DIR SERVICE_USER SERVICE_GROUP SERVICE_NAME WORKER_STORAGE_DIR SSM_PARAMETER_PATH
envsubst < "${APP_DIR}/scripts/codedeploy/templates/shelfalign-worker.service" \
    > "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload

echo "ShelfAlign worker post-installation complete."
