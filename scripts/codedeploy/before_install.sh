#!/bin/bash
set -euo pipefail

echo "Preparing for installation..."

APP_DIR="/opt/shelfalign-worker"
SERVICE_USER="shelfalign-worker"
SERVICE_GROUP="shelfalign-worker"

# Create service user if not exists
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    echo "Creating service user: ${SERVICE_USER}"
    useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

# Create application directory
if [[ -d "${APP_DIR}" ]]; then
    echo "Cleaning existing application directory..."
    rm -rf "${APP_DIR}"
fi

mkdir -p "${APP_DIR}"
chown "${SERVICE_USER}:${SERVICE_GROUP}" "${APP_DIR}"

# Resolve the EC2 region (IMDSv2, falling back to v1) so SSM calls work even
# when the instance profile has no default region configured.
resolve_region() {
    local token region
    token="$(curl -sS -m 2 -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
    if [[ -n "${token}" ]]; then
        region="$(curl -sS -m 2 -H "X-aws-ec2-metadata-token: ${token}" \
            http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || true)"
    else
        region="$(curl -sS -m 2 \
            http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || true)"
    fi
    echo "${region}"
}

# Install the OpenTelemetry Collector (contrib distribution -- the awss3
# exporter the config uses is NOT in AWS ADOT). Version is pinned in SSM so it
# can be rolled forward without a redeploy.
install_otel_collector() {
    # SSM_PARAMETER_PATH is provisioned via /opt/app.conf (same source
    # after_install.sh uses for the bulk param fetch).
    if [[ -f "/opt/app.conf" ]]; then
        # shellcheck source=/dev/null
        source /opt/app.conf
    fi
    if [[ -z "${SSM_PARAMETER_PATH:-}" ]]; then
        echo "SSM_PARAMETER_PATH unset; skipping OTel Collector install"
        return 0
    fi
    local base="${SSM_PARAMETER_PATH%/}"

    local region
    region="$(resolve_region)"
    [[ -n "${region}" ]] && export AWS_DEFAULT_REGION="${region}"

    # The instance role only grants ssm:GetParametersByPath on the worker
    # path (not ssm:GetParameter), so resolve the version via a path query
    # rather than a direct get-parameter call.
    # SSM auto-paginates and the CLI applies --query per page, so the list
    # projection emits one line per page: an empty line for pages lacking the
    # key and the value for the page that has it (param order across pages is
    # not guaranteed). Split on whitespace and take the first non-empty token
    # -- head -n1 would grab the empty line when the param is not on page 1.
    local version
    version="$(aws ssm get-parameters-by-path --path "${base}" --recursive \
        --query "Parameters[?ends_with(Name, '/OTEL_COLLECTOR_VERSION')].Value" \
        --output text 2>/dev/null | tr -s '[:space:]' '\n' | grep -m1 . || true)"
    if [[ -z "${version}" || "${version}" == "None" ]]; then
        # OTel is optional: an env that hasn't provisioned the version param
        # (or intentionally disables telemetry) must still deploy. Skip the
        # collector install; after_install.sh's command -v otelcol-contrib
        # guard then skips collector config too.
        echo "${base}/OTEL_COLLECTOR_VERSION not set; skipping OTel Collector install"
        return 0
    fi
    version="${version#v}"

    if command -v otelcol-contrib >/dev/null 2>&1; then
        local current
        current="$(otelcol-contrib --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
        if [[ "${current}" == "${version}" ]]; then
            echo "OTel Collector ${version} already installed"
            return 0
        fi
        echo "OTel Collector ${current:-unknown} -> ${version}"
    fi

    local arch
    case "$(uname -m)" in
        x86_64) arch="amd64" ;;
        aarch64) arch="arm64" ;;
        *) echo "ERROR: unsupported arch $(uname -m)" >&2; exit 1 ;;
    esac

    local rel="https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${version}"
    local tmp
    tmp="$(mktemp -d)"
    if command -v rpm >/dev/null 2>&1 && (command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1); then
        curl -fLsS "${rel}/otelcol-contrib_${version}_linux_${arch}.rpm" -o "${tmp}/otelcol.rpm"
        rpm -Uvh --replacepkgs "${tmp}/otelcol.rpm"
    elif command -v apt-get >/dev/null 2>&1; then
        curl -fLsS "${rel}/otelcol-contrib_${version}_linux_${arch}.deb" -o "${tmp}/otelcol.deb"
        dpkg -i "${tmp}/otelcol.deb"
    else
        echo "ERROR: no supported package manager (rpm/dpkg) found" >&2
        exit 1
    fi
    rm -rf "${tmp}"
    # The package enables+starts otelcol-contrib with its stub config; stop it
    # so after_install can lay down the real SSM config before first start.
    systemctl stop otelcol-contrib 2>/dev/null || true
    echo "OTel Collector ${version} installed"
}

install_otel_collector

echo "Pre-installation complete."
exit 0
