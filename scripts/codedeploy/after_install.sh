#!/bin/bash
set -euo pipefail

echo "Starting post-installation..."

# Configuration
APP_DIR="/opt/qmr-worker"
SERVICE_USER="qmr-worker"
SERVICE_GROUP="qmr-worker"
SERVICE_NAME="qmr-worker"

if [[ -f "/opt/app.conf" ]]; then
    echo "Application config found, sourcing /opt/app.conf"
    # shellcheck source=/dev/null
    source /opt/app.conf
fi

if [[ -n "${SSM_PARAMETER_PATH:-}" ]]; then
    echo "Fetching parameters from SSM Parameter Store path: ${SSM_PARAMETER_PATH}"

    # Ensure trailing slash
    if [[ "${SSM_PARAMETER_PATH}" != */ ]]; then
        SSM_PARAMETER_PATH="${SSM_PARAMETER_PATH}/"
    fi

    # Only export params whose leaf name is a valid shell identifier and
    # shell-quote the value. Skips structural params like "otel-config"
    # (dash + multiline YAML) that would otherwise corrupt the worker env.
    aws ssm get-parameters-by-path --path "${SSM_PARAMETER_PATH}" --output json | \
        jq -r '.Parameters[]
            | (.Name | split("/") | last) as $k
            | select($k | test("^[A-Za-z_][A-Za-z0-9_]*$"))
            | "export \($k)=\(.Value | @sh)"' > /tmp/env.sh

    # shellcheck source=/dev/null
    source /tmp/env.sh
    rm /tmp/env.sh
fi

if [[ -n "${INIT_SCRIPT_S3:-}" ]]; then
    echo "Downloading and executing init script from S3: ${INIT_SCRIPT_S3}"
    aws s3 cp "${INIT_SCRIPT_S3}" /tmp/init_script.sh
    chmod +x /tmp/init_script.sh
    /tmp/init_script.sh
    rm /tmp/init_script.sh
fi

if [[ -n "${INIT_SCRIPT_URL:-}" ]]; then
    echo "Downloading and executing init script from URL: ${INIT_SCRIPT_URL}"
    curl -LsSf "${INIT_SCRIPT_URL}" -o /tmp/init_script.sh
    chmod +x /tmp/init_script.sh
    /tmp/init_script.sh
    rm /tmp/init_script.sh
fi

WORKER_STORAGE_DIR="${WORKER_STORAGE_DIR:-/var/lib/qmr-worker}"
MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-/var/cache/qmr-worker/models}"

echo "Setting up application directories..."
mkdir -p "${APP_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}"

mkdir -p "${WORKER_STORAGE_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${WORKER_STORAGE_DIR}"

mkdir -p "${MODEL_CACHE_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${MODEL_CACHE_DIR}"

mkdir -p "${MODEL_CACHE_DIR}/inductor"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${MODEL_CACHE_DIR}/inductor"

mkdir -p "${MODEL_CACHE_DIR}/inductor/qb"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${MODEL_CACHE_DIR}/inductor/qb"

mkdir -p "${MODEL_CACHE_DIR}/inductor/cache"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${MODEL_CACHE_DIR}/inductor/cache"

# Install RDS CA Bundle for SSL connections
echo "Installing RDS CA bundle..."
curl -sSf "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem" \
    -o /usr/local/share/ca-certificates/aws-rds.crt
update-ca-certificates

# Export for envsubst
export APP_DIR SERVICE_USER SERVICE_GROUP SERVICE_NAME MODEL_CACHE_DIR WORKER_STORAGE_DIR SSM_PARAMETER_PATH

echo "Installing application dependencies..."

cd "${APP_DIR}"

# Install uv if not present
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
fi

# Remove old venv if exists (clean slate)
if [[ -d ".venv" ]]; then
    echo "Removing old virtual environment..."
    rm -rf .venv
fi

# Wheel caching - store in persistent location to survive app dir cleanup
WHEEL_CACHE_DIR="/var/cache/qmr-worker/wheels"
S3_BUCKET=$(cat wheels/.s3-bucket)
S3_PREFIX=$(cat wheels/.s3-prefix 2>/dev/null || echo "")
PYPI_CACHE_KEY=$(cat wheels/.pypi-cache-key)
ROMAV2_CACHE_KEY=$(cat wheels/.romav2-cache-key)

# Construct S3 base path with optional prefix
if [[ -n "${S3_PREFIX}" ]]; then
    S3_BASE="s3://${S3_BUCKET}/${S3_PREFIX}"
else
    S3_BASE="s3://${S3_BUCKET}"
fi

echo "S3 wheel source: ${S3_BASE}/wheels/"

mkdir -p "${WHEEL_CACHE_DIR}"

# Check if local cache matches, download only if needed
download_wheels() {
    local cache_name="$1"
    local cache_key="$2"
    local local_cache_dir="${WHEEL_CACHE_DIR}/${cache_name}"
    local local_cache_key_file="${WHEEL_CACHE_DIR}/.${cache_name}-cache-key"
    local existing_cache_key=""

    if [[ -f "${local_cache_key_file}" ]]; then
        read -r existing_cache_key < "${local_cache_key_file}"
    fi

    if [[ "${existing_cache_key}" == "${cache_key}" ]]; then
        echo "${cache_name} wheels cache hit, skipping download"
    else
        echo "Downloading ${cache_name} wheels from ${S3_BASE}/wheels/${cache_key}/"
        rm -rf "${local_cache_dir}"
        mkdir -p "${local_cache_dir}"
        aws s3 sync "${S3_BASE}/wheels/${cache_key}/" "${local_cache_dir}/"
        echo "${cache_key}" > "${local_cache_key_file}"
    fi
}

download_wheels "pypi" "${PYPI_CACHE_KEY}"
download_wheels "romav2" "${ROMAV2_CACHE_KEY}"
echo "Wheels ready"

# Link cached wheels to app directory (symlinks avoid slow copy of large files)
echo "Linking wheels from cache..."
rm -rf wheels/pypi wheels/romav2
ln -sf "${WHEEL_CACHE_DIR}/pypi" wheels/pypi
ln -sf "${WHEEL_CACHE_DIR}/romav2" wheels/romav2
wheel_cache_size="$(du -sh "${WHEEL_CACHE_DIR}" | cut -f1)"
echo "Wheels linked (cache: ${wheel_cache_size})"

# Download inductor cache if available (speeds up torch.compile warmup)
download_inductor_cache() {
    if [[ ! -f "wheels/.romav2-git-hash" ]]; then
        echo "No romav2 git hash found, skipping inductor cache download"
        return 0
    fi

    ROMAV2_GIT_HASH=$(cat wheels/.romav2-git-hash)
    GPU_ARCH=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d '.' | sed 's/^/sm_/')

    if [[ -z "${GPU_ARCH}" || "${GPU_ARCH}" == "sm_" ]]; then
        echo "No GPU detected, skipping inductor cache download"
        return 0
    fi

    INDUCTOR_CACHE_KEY="inductor-${ROMAV2_GIT_HASH}-${GPU_ARCH}"
    INDUCTOR_CACHE_DIR="${MODEL_CACHE_DIR}/inductor"
    mkdir -p "${INDUCTOR_CACHE_DIR}"
    chown "${SERVICE_USER}:${SERVICE_GROUP}" "${INDUCTOR_CACHE_DIR}"

    # Write cache key for Python to know what to upload later
    echo "${INDUCTOR_CACHE_KEY}" > "${INDUCTOR_CACHE_DIR}/.cache-key"

    echo "Checking for inductor cache: ${INDUCTOR_CACHE_KEY}"

    # Try to download from S3 (non-fatal if missing)
    if aws s3 cp "${S3_BASE}/inductor-cache/${INDUCTOR_CACHE_KEY}.tar.gz" /tmp/inductor-cache.tar.gz 2>/dev/null; then
        echo "Inductor cache found, extracting..."
        tar -xzf /tmp/inductor-cache.tar.gz -C "${INDUCTOR_CACHE_DIR}"
        rm /tmp/inductor-cache.tar.gz
        touch "${INDUCTOR_CACHE_DIR}/.downloaded"  # Marker: don't upload later
        echo "Inductor cache extracted successfully"
    else
        echo "No inductor cache found for ${INDUCTOR_CACHE_KEY}, will compile on first run"
    fi

    # This script runs as root, but torch.compile runs as SERVICE_USER. Keep
    # downloaded/extracted cache files and marker files writable at runtime.
    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INDUCTOR_CACHE_DIR}"
}

download_inductor_cache

# Create fresh venv
echo "Creating virtual environment..."
uv venv .venv
echo "Virtual environment created"

# Install from pre-built wheels (no network needed for PyPI)
echo "Installing from wheels (this may take several minutes for large packages like torch)..."
uv pip install --no-cache --no-index \
    --find-links="${APP_DIR}/wheels/pypi" \
    --find-links="${APP_DIR}/wheels/romav2" \
    -r "${APP_DIR}/requirements.txt"
echo "Main dependencies installed"

# Install romav2 separately (no deps, already satisfied)
echo "Installing romav2..."
uv pip install --no-cache --no-index --no-deps \
    --find-links="${APP_DIR}/wheels/romav2" \
    romav2

echo "Dependencies installed successfully"

# Set correct ownership
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}"

# Create log file with correct permissions
touch /var/log/qmr-worker.log
chown "${SERVICE_USER}:${SERVICE_GROUP}" /var/log/qmr-worker.log
chmod 644 /var/log/qmr-worker.log

# Install systemd service file from template
echo "Installing systemd service..."
envsubst < "${APP_DIR}/scripts/codedeploy/templates/qmr-worker.service" \
    > "/etc/systemd/system/${SERVICE_NAME}.service"

# Configure CloudWatch Agent for journald log collection
configure_cloudwatch_agent() {
    echo "Configuring CloudWatch Agent..."

    if ! command -v amazon-cloudwatch-agent-ctl &>/dev/null; then
        echo "CloudWatch Agent not installed, skipping configuration."
        echo "Install with: yum install -y amazon-cloudwatch-agent (Amazon Linux) or apt install amazon-cloudwatch-agent (Ubuntu)"
        return 0
    fi

    mkdir -p /opt/aws/amazon-cloudwatch-agent/etc

    # Get instance metadata and export for envsubst
    INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id || echo "unknown")
    export INSTANCE_ID

    # Install CloudWatch Agent config from template
    envsubst < "${APP_DIR}/scripts/codedeploy/templates/amazon-cloudwatch-agent.json" \
        > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

    # Start CloudWatch Agent
    amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s \
        -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

    echo "CloudWatch Agent configured successfully"
}

configure_cloudwatch_agent

# Provision the OTel Collector: lay down the SSM-sourced config + OTEL_* env,
# wire a 5-min refresh timer, then start it. The collector binary itself is
# installed in before_install.sh (version pinned in SSM).
configure_otel_collector() {
    if ! command -v otelcol-contrib >/dev/null 2>&1; then
        echo "OTel Collector not installed, skipping configuration."
        return 0
    fi
    if [[ -z "${SSM_PARAMETER_PATH:-}" ]]; then
        echo "SSM_PARAMETER_PATH unset, skipping OTel Collector configuration."
        return 0
    fi
    # otel-config is shared across apps, so its full SSM param name is provided
    # independently via /opt/app.conf (sourced at the top of this script) --
    # NOT derived from the per-app SSM_PARAMETER_PATH.
    if [[ -z "${OTEL_CONFIG_PARAM:-}" ]]; then
        # OTel is optional. An already-installed otelcol-contrib can survive a
        # version-param removal (before_install skips reinstall but doesn't
        # uninstall), so this branch is reachable during a telemetry
        # disable/misprovision. Skip configuration instead of failing the deploy.
        echo "OTEL_CONFIG_PARAM not set in /opt/app.conf; skipping OTel Collector configuration."
        return 0
    fi
    echo "Configuring OTel Collector..."

    local region token
    token="$(curl -sS -m 2 -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
    if [[ -n "${token}" ]]; then
        region="$(curl -sS -m 2 -H "X-aws-ec2-metadata-token: ${token}" \
            http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || true)"
    else
        region="$(curl -sS -m 2 \
            http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || true)"
    fi

    mkdir -p /etc/qmr-otel /etc/otelcol-contrib

    # Self-contained runtime config for the refresh script + timer (the app
    # dir is wiped on every deploy, so this must live outside it).
    umask 077
    cat > /etc/qmr-otel/refresh.conf <<EOF
SSM_PARAMETER_PATH=${SSM_PARAMETER_PATH}
OTEL_CONFIG_PARAM=${OTEL_CONFIG_PARAM}
AWS_REGION=${region}
AWS_DEFAULT_REGION=${region}
EOF
    umask 022

    install -m 755 "${APP_DIR}/scripts/codedeploy/otel_refresh.sh" \
        /usr/local/bin/qmr-otel-refresh

    mkdir -p /etc/systemd/system/otelcol-contrib.service.d
    install -m 644 "${APP_DIR}/scripts/codedeploy/templates/otelcol-contrib-override.conf" \
        /etc/systemd/system/otelcol-contrib.service.d/qmr.conf
    install -m 644 "${APP_DIR}/scripts/codedeploy/templates/qmr-otel-refresh.service" \
        /etc/systemd/system/qmr-otel-refresh.service
    install -m 644 "${APP_DIR}/scripts/codedeploy/templates/qmr-otel-refresh.timer" \
        /etc/systemd/system/qmr-otel-refresh.timer

    systemctl daemon-reload

    # Initial fetch (collector still inactive: try-restart inside is a no-op).
    /usr/local/bin/qmr-otel-refresh

    systemctl enable --now otelcol-contrib
    systemctl enable --now qmr-otel-refresh.timer

    echo "OTel Collector configured successfully"
}

configure_otel_collector

# Reload systemd
systemctl daemon-reload

echo "Post-installation complete."
exit 0
