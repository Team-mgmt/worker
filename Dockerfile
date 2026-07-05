FROM python:3.12-slim AS base

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  apt-get update && \
  apt-get install -qy curl unzip jq && \
  apt-get clean

FROM base AS builder

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  apt-get update && \
  apt-get install -qy --no-install-recommends \
  build-essential cmake python3-dev && \
  apt-get clean

COPY ./requirements.txt /app/requirements.txt

RUN mkdir /app/wheels && \
  pip wheel --no-cache-dir --wheel-dir /app/wheels -r /app/requirements.txt

FROM base AS runner

RUN addgroup --gid 2026 runner && \
  adduser --uid 2026 --gid 2026 --disabled-password runner && \
  chown runner:runner /app -R

ARG TARGETARCH

# Install AWS CLI v2
RUN if [ "${TARGETARCH}" = "amd64" ]; then \
  ARCH="x86_64"; \
  elif [ "${TARGETARCH}" = "arm64" ]; then \
  ARCH="aarch64"; \
  else \
  echo "Unsupported architecture: ${TARGETARCH}"; \
  exit 1; \
  fi && \
  curl "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o "awscliv2.zip" && \
  unzip -qq awscliv2.zip && \
  ./aws/install && \
  rm -rf awscliv2.zip aws

# Install RDS CA Bundle
RUN curl "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem" -o /usr/local/share/ca-certificates/aws-rds.crt && \
  update-ca-certificates

USER runner

COPY --chown=runner:runner --from=builder /app/wheels /app/wheels
COPY --chown=runner:runner --from=builder /app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --no-index --break-system-packages --find-links=/app/wheels -r /app/requirements.txt && \
  rm -rf /app/wheels /app/requirements.txt

COPY --chown=runner:runner ./scripts/docker-entrypoint.sh /docker-entrypoint.sh
COPY --chown=runner:runner ./worker /app/worker
COPY --chown=runner:runner ./assets/warmup /app/assets/warmup

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

ARG BUILD_VERSION=unknown
ENV SENTRY_RELEASE=${BUILD_VERSION}
ENV WORKER_MODE=cpu
ENV TORCH_FLOAT32_MATMUL_PRECISION=highest

ENTRYPOINT ["/docker-entrypoint.sh"]
