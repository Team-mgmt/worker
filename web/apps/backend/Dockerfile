ARG NODE_VERSION=24
FROM public.ecr.aws/docker/library/node:${NODE_VERSION}-slim AS base

ARG TURBO_VERSION

WORKDIR /app

ENV COREPACK_HOME=/corepack
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME/node_modules/.bin:/pnpm:/pnpm/bin:$PATH

RUN test -n "${TURBO_VERSION}" || (echo "TURBO_VERSION build arg is required" >&2; exit 1) && \
  npm install -g corepack@latest && \
  corepack enable && \
  pnpm install -g turbo@${TURBO_VERSION} && \
  mkdir -p /corepack

ARG TARGETARCH

RUN --mount=type=cache,target=/var/cache/apt,id=apt-${TARGETARCH},sharing=locked \
  apt-get update && \
  apt-get install -qy openssl curl unzip jq ca-certificates yq \
  poppler-utils \
  libcairo2 libpango-1.0-0 libjpeg62-turbo \
  libgif7 librsvg2-2 && \
  apt-get clean

FROM base AS source

COPY . /app/

# The prisma typed SQL client is pre-generated on the CI runner (where
# postgres is reachable) and lives under the package's gitignored
# src/generated/prisma/ directory. turbo prune respects .gitignore and
# would strip these files, so we snapshot and restore them around prune.
RUN mkdir -p /tmp/prisma-client && \
  if [ -d /app/packages/database/src/generated/prisma ]; then \
  cp -a /app/packages/database/src/generated/prisma/. /tmp/prisma-client/; \
  fi

RUN turbo prune @shelfalign/backend --docker && \
  mv /app/out /out && \
  rm -rf /app && \
  mv /out /app

RUN if [ -n "$(ls -A /tmp/prisma-client 2>/dev/null)" ]; then \
  mkdir -p /app/full/packages/database/src/generated/prisma && \
  cp -a /tmp/prisma-client/. /app/full/packages/database/src/generated/prisma/; \
  touch /app/full/packages/database/src/generated/.docker; \
  fi && rm -rf /tmp/prisma-client

FROM base AS build

ARG TARGETARCH

RUN --mount=type=cache,target=/var/cache/apt,id=apt-${TARGETARCH},sharing=locked \
  apt-get update && \
  apt-get install -qy build-essential libcairo2-dev libpango1.0-dev \
  libjpeg-dev libgif-dev librsvg2-dev && \
  apt-get clean

COPY --from=source /app/json .
COPY --from=source /app/full/turbo.json .

RUN --mount=type=cache,target=/pnpm/store,id=pnpm-${TARGETARCH},sharing=locked \
  pnpm install --frozen-lockfile

# Pre-build canvas to speed up final image build
RUN mkdir -p /canvas-prebuilt && \
  CANVAS_DIR=$(find /app/node_modules/.pnpm -maxdepth 2 -type d -name "canvas@*") && \
  cp -r "$CANVAS_DIR" /canvas-prebuilt/contents && \
  basename "$CANVAS_DIR" > /canvas-prebuilt/dirname.txt

COPY --from=source /app/full .

RUN --mount=type=secret,id=SENTRY_AUTH_TOKEN,env=SENTRY_AUTH_TOKEN pnpm build

FROM base AS runner

RUN addgroup --system --gid 1001 runner && \
  adduser --system --uid 1001 runner && \
  chown -R runner:runner /app /pnpm /corepack

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
RUN curl "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem" -o /usr/local/share/ca-certificates/aws-rds.crt

# Copy pre-built canvas from build stage
COPY --from=build --chown=runner:runner /canvas-prebuilt /canvas-prebuilt

# Move pre-built canvas to the correct location
RUN CANVAS_DIRNAME=$(cat /canvas-prebuilt/dirname.txt) && \
  mkdir -p /app/node_modules/.pnpm/$CANVAS_DIRNAME && \
  mv /canvas-prebuilt/contents "/app/node_modules/.pnpm/$CANVAS_DIRNAME" && \
  rm -rf /canvas-prebuilt && \
  chown -R runner:runner "/app/node_modules"

USER runner

COPY --from=source --chown=runner:runner /app/json .

# Explicitly deny canvas's build script in the runner stage — the prebuilt
# canvas is copied in from the build stage above. `false` (rather than
# deleting the entry) keeps strictDepBuilds protection for any future package
# that's added without a build-policy decision.
RUN yq -i -y '.allowBuilds.canvas = false' pnpm-workspace.yaml

RUN --mount=type=cache,target=/pnpm/store,id=pnpm-${TARGETARCH},sharing=locked,uid=1001,gid=1001 \
  pnpm install --frozen-lockfile --prod

COPY --from=build --chown=runner:runner /app/apps/backend/dist/ /app/apps/backend/dist/
COPY --from=build --chown=runner:runner /app/packages/schema/dist/ /app/packages/schema/dist/
COPY --from=build --chown=runner:runner /app/packages/database/dist/ /app/packages/database/dist/

COPY apps/backend/scripts/docker-entrypoint.sh /app/docker-entrypoint.sh

ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/aws-rds.crt

# When the ECS task definition does not specify a healthCheck, Fargate honors
# this directive. Reports "unhealthy" if /health (which exercises the cache)
# does not return 2xx within the timeout. The CMD form runs via /bin/sh, so
# ${PORT} expands at runtime to match the port the app actually listens on
# (apps/backend/src/main.ts: env.PORT ?? 4000).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl --fail --silent --max-time 4 "http://127.0.0.1:${PORT:-4000}/health" || exit 1

CMD ["bash", "/app/docker-entrypoint.sh"]
