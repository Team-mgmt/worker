Use otelcol-contrib, not ADOT

ADOT bundles a curated component set centered on AMP/X-Ray and does not include the awss3 exporter. Use the upstream contrib distro from open-telemetry/opentelemetry-collector-releases (otelcol-contrib_*_linux_amd64.rpm).

Steps

1. Install in before_install.sh:
OTELCOL_VERSION=0.110.0  # pin; check releases page for current
rpm -Uvh "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OTELCOL_VERSION}/otelcol-contrib_${OTELCOL_VERSION}_linux_amd64.rpm"
Pinning version matters — awss3 exporter is still alpha/beta and config schema changes between releases.

2. Pull the config from SSM in after_install.sh:
aws ssm get-parameter --region ap-northeast-2 --name /dev/qmr/otel-config \
  --with-decryption --query 'Parameter.Value' --output text \
  > /etc/otelcol-contrib/config.yaml
chown otelcol-contrib:otelcol-contrib /etc/otelcol-contrib/config.yaml
chmod 640 /etc/otelcol-contrib/config.yaml
Don't bake the config into the CodeDeploy bundle — it's already centralized in SSM. Reloading config = SSM put + systemctl restart otelcol-contrib.

3. Set env vars via a systemd drop-in /etc/systemd/system/otelcol-contrib.service.d/override.conf:
[Service]
Environment=OTEL_S3_BUCKET=qmr-otel-dev
Environment=OTEL_SERVICE_NAME=qmr-worker
Environment=AWS_REGION=ap-northeast-2
The config references ${env:OTEL_S3_BUCKET} and ${env:OTEL_SERVICE_NAME} — both must be exported into the collector's process env or the exporter will fail to start. Heads-up: /dev/qmr/otel-bucket (or similar) isn't in SSM yet — you'll need to create the bucket and either hardcode in the drop-in or add an SSM param.

4. IAM — the EC2 instance role needs s3:PutObject (and s3:PutObjectAcl if the bucket enforces ACLs) scoped to arn:aws:s3:::qmr-otel-dev/*. The awss3 exporter signs with the default credentials chain, which on EC2 = IMDSv2 instance role.

5. Wire the worker in qmr-worker.service:
After=network.target otelcol-contrib.service
Environment=OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
Environment=OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
Environment=OTEL_SERVICE_NAME=qmr-worker

6. Validate in validate_service.sh: curl -fsS http://127.0.0.1:13133/ (health_check is already in the SSM config).

Two gaps in the current SSM config to flag

- resourcedetection: detectors: [env, ecs] — ecs is wrong for EC2; it'll silently no-op against the ECS metadata endpoint. Change to [env, ec2] (or [env, ec2, ecs] if you also run this elsewhere) so instance-id/AZ/region resource attrs actually get attached.
- No bucket param in SSM — /dev/qmr/otel-bucket doesn't exist, so the OTEL_S3_BUCKET env has no source of truth yet. Worth adding now to match the SSM-driven pattern the rest of the worker uses.

Want me to draft the CodeDeploy hook edits, systemd drop-in, and the SSM put-parameter for the bucket name?