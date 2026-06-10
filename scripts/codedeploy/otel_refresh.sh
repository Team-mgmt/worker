#!/bin/bash
# Fetch the OTel Collector config + OTEL_* env vars from SSM and reload the
# collector only when something actually changed. Installed to
# /usr/local/bin/qmr-otel-refresh and driven both from after_install.sh (once,
# at deploy time) and from a systemd timer (every 5 min at runtime).
#
# Runtime config is read from /etc/qmr-otel/refresh.conf so the script is fully
# self-contained and does not depend on the (wiped-on-deploy) app directory.
set -euo pipefail

CONF_FILE="/etc/qmr-otel/refresh.conf"
COLLECTOR_CONFIG="/etc/otelcol-contrib/config.yaml"
COLLECTOR_ENV="/etc/qmr-otel/otel.env"
COLLECTOR_SERVICE="otelcol-contrib"

if [[ ! -f "${CONF_FILE}" ]]; then
    echo "qmr-otel-refresh: ${CONF_FILE} missing; nothing to do" >&2
    exit 0
fi
# shellcheck source=/dev/null
source "${CONF_FILE}"

: "${SSM_PARAMETER_PATH:?refresh.conf must set SSM_PARAMETER_PATH}"
: "${OTEL_CONFIG_PARAM:?refresh.conf must set OTEL_CONFIG_PARAM}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-}}"

changed=0

# 1. Collector config (single multiline YAML param, fetched explicitly).
new_config="$(mktemp)"
trap 'rm -f "${new_config}" "${new_env:-}" "${ssm_json:-}"' EXIT
if aws ssm get-parameter --name "${OTEL_CONFIG_PARAM}" --with-decryption \
        --query 'Parameter.Value' --output text > "${new_config}"; then
    if [[ ! -f "${COLLECTOR_CONFIG}" ]] || \
       ! cmp -s "${new_config}" "${COLLECTOR_CONFIG}"; then
        install -m 644 "${new_config}" "${COLLECTOR_CONFIG}"
        echo "qmr-otel-refresh: collector config updated from ${OTEL_CONFIG_PARAM}"
        changed=1
    fi
else
    echo "qmr-otel-refresh: failed to fetch ${OTEL_CONFIG_PARAM}; keeping existing config" >&2
fi

# 2. OTEL_* scalar params -> systemd EnvironmentFile. A transient SSM/API
#    error must not abort the deploy (after_install.sh runs this): warn and
#    keep the existing env, mirroring the config fallback above.
new_env="$(mktemp)"
ssm_json="$(mktemp)"
if aws ssm get-parameters-by-path --path "${SSM_PARAMETER_PATH}" --recursive \
        --with-decryption --output json > "${ssm_json}"; then
    jq -r '.Parameters[]
        | (.Name | split("/") | last) as $k
        | select($k | test("^OTEL_[A-Za-z0-9_]+$"))
        | "\($k)=\(.Value)"' < "${ssm_json}" \
        | LC_ALL=C sort > "${new_env}"

    if [[ ! -f "${COLLECTOR_ENV}" ]] || ! cmp -s "${new_env}" "${COLLECTOR_ENV}"; then
        install -m 644 "${new_env}" "${COLLECTOR_ENV}"
        echo "qmr-otel-refresh: collector env updated ($(wc -l < "${new_env}") OTEL_* vars)"
        changed=1
    fi
else
    echo "qmr-otel-refresh: failed to fetch OTEL_* params from ${SSM_PARAMETER_PATH}; keeping existing env" >&2
fi

# 3. Reload only when active and only on change. try-restart is a no-op when
#    the unit is inactive (deploy-time: after_install starts it explicitly
#    afterwards), so this never races the initial enable --now.
if [[ "${changed}" -eq 1 ]]; then
    systemctl try-restart "${COLLECTOR_SERVICE}" || true
    echo "qmr-otel-refresh: ${COLLECTOR_SERVICE} reloaded"
else
    echo "qmr-otel-refresh: no changes"
fi
