# Affected resources

## Account
- AWS Account: `580148408737`
- Region: `ap-northeast-2`

## ElastiCache (server side)
- Replication group: `dev-shelfalign-cache`
- ARN: `arn:aws:elasticache:ap-northeast-2:580148408737:replicationgroup:dev-shelfalign-cache`
- Configuration endpoint: `clustercfg.dev-shelfalign-cache.gdmobq.apn2.cache.amazonaws.com:6379`
- Engine: Valkey 8.2.0, cluster mode enabled, transit encryption required
- Cluster nodes:
  - `dev-shelfalign-cache-0001-001` (ap-northeast-2a)
  - `dev-shelfalign-cache-0001-002` (ap-northeast-2c)
- IAM auth user: `dev-iam-shelfalign` (`Authentication.Type=iam`, AccessString `on ~* +@all`)
- User group: `dev-shelfalign-usergroup`

## ECS (client side)
- Cluster: `shelfalign`
- Service: `dev-web-backend`
- Task that exhibited the failure: `0aad4fcf1ca84b47a8af308115c331df`
  - Task definition: `dev-web-backend-taskdef:7`
  - Image digest: `sha256:e2675cdb47fb83c1b69e94a2b719f7c61810c3544b3ea0f9bf07490405e32ccb`
  - ENI: `eni-07593ca4ca024c49e`
  - Subnet: `subnet-0da69efb78e176e7f` (ap-northeast-2a)
  - Started: 2026-05-04T11:40:08Z
  - Stopped (manual replacement): 2026-05-05T05:44:56Z
- IAM task role: `dev-web-backend@ecs-task` (has `elasticache:Connect` on the replication group and on the user)

## Control resource (unaffected)
- Replication group: `prd-shelfalign-cache` (same region, same IAM auth pattern, separate cluster)
- IAM auth user: `prd-iam-shelfalign` (Type=iam)
- ECS service: `prd-web-backend` reauthed successfully at 2026-05-04T22:31:25Z (75 minutes after dev's failed reauth) — see `logs/05-prd-control-reauth-success.log`.

## Client library
- `iovalkey@0.3.3` (Node.js, ioredis-compatible fork) in cluster mode
- AWS signing: `@aws-sdk/signature-v4-crt` with `defaultProvider()` credentials, presigned URL with `expiresIn: 900` seconds (15 min)
