# Transient IAM auth failure on ElastiCache caused multi-hour client wedge

## Summary

A single transient `ERR IAM Authentication service is not available` response from ElastiCache during a routine IAM token rotation (12-hour mark) caused our backend's iovalkey cluster client to enter a non-recoverable reconnect loop for 18 hours. We are seeking AWS-side confirmation of what happened to the auth backend at that moment, and clarification on AWS's recommended client behavior.

## What happened

### Timeline (UTC)

| Time | Hours after task start | Event |
|---|---|---|
| 2026-05-04 11:40:48 | T+0 | ECS task starts; cluster connects successfully on first AUTH with a fresh IAM-presigned token. |
| 2026-05-04 21:16:48 | T+9h36m | First scheduled reauth fires (we rotate at 12h × 0.8 = 9.6h, before the AWS 12h drop). Fresh presigned token sent to `AUTH dev-iam-shelfalign <presigned-url>`. |
| 2026-05-04 21:16:50 | T+9h36m | ElastiCache replies `ERR IAM Authentication service is not available.` to that AUTH command. **Single occurrence.** |
| 2026-05-04 23:58:33 | T+12h18m | The original token (still in use because reauth failed) is now rejected: `WRONGPASS invalid username-password pair or user is disabled.` iovalkey's `reconnectOnError` triggers reconnect. |
| 2026-05-04 23:58:33 → 2026-05-05 05:44:56 | T+12h18m → T+18h4m | Tight reconnect loop. ~1,800 `ClusterAllFailedError: Failed to refresh slots cache` events per hour. The cluster object never recovers `CLUSTER SLOTS` even though the password is rotated to a fresh IAM token on every reconnect attempt. |
| 2026-05-05 05:44:56 | T+18h4m | Manual deploy starts a new ECS task with a fresh `iovalkey.Cluster` instance — connects successfully on first try, no errors since. |

See `logs/06-error-histogram.txt` for the hourly distribution.

### Smoking gun

`logs/02-reauth-iam-unavailable.log`:

```
2026-05-04 21:16:48 UTC LOG   [CacheService] Reauthenticating cache connection
2026-05-04 21:16:48 UTC LOG   [CacheService] Using IAM token as password for cache connection
2026-05-04 21:16:50 UTC ERROR [CacheService] Error during cache reauthentication
2026-05-04 21:16:50 UTC ERROR [CacheService] ReplyError: ERR IAM Authentication service is not available.
  command: { name: 'auth', args: [ 'dev-iam-shelfalign', '[REDACTED: presigned IAM URL]' ] }
```

The presigned URL is freshly signed (`X-Amz-Date=20260504T211648Z`, `X-Amz-Expires=900`) so it is well within the 15-minute validity window when AWS rejects it.

### Cascade

`logs/03-token-expiry-cascade.log` shows the WRONGPASS at 23:58:33 followed immediately by the cluster losing slot discovery. From that point onward iovalkey loops:

1. Receives WRONGPASS on a node connection
2. `reconnectOnError` returns `1` (matching `/\b(WRONGPASS|NOAUTH)\b/i`)
3. `reconnecting` event fires; we call `getPassword()` → fresh AWS-signed token (verified by the `Using IAM token...` log on every cycle)
4. `client.options.redisOptions.password = newToken` is set
5. `CLUSTER SLOTS` fails on every seed node → `ClusterAllFailedError`
6. Loop repeats every ~2 seconds for 5 hours 46 minutes

Recovery only happened when we cycled the entire `Cluster` object via redeploy.

## What we have already verified

- **It is not network**. ECS ENI `eni-07593ca4ca024c49e` (10.81.96.96 / IPv6 2406:da12:d3e:9a80:9421:a403:4752:c2af) and the cache nodes are in the same VPC `vpc-087c61e36e52fb1da`. Security group `sg-06dd3b10fb4c62f95` allows TCP 6379 ingress from the ECS security group `sg-02eae498fe4708fb3`. Default NACL allows all. The connection worked for 9.5 hours before the reauth event and would have continued working on the original token; the failure is exclusively in the AUTH path.
- **It is not token age or signature**. The token is signed with `expiresIn: 900` and the AUTH command is sent in the same async tick. The `X-Amz-Date` in the rejected request is `20260504T211648Z` and AWS rejected it 2 seconds later.
- **It is not IAM permissions**. The task role `dev-web-backend@ecs-task` has `elasticache:Connect` on both `arn:aws:elasticache:ap-northeast-2:580148408737:replicationgroup:dev-shelfalign-cache` and `arn:aws:elasticache:ap-northeast-2:580148408737:user:dev-iam-shelfalign`. The task had been authenticating successfully every time for 9.5 hours and continued to do so for another 2.7 hours after the failed reauth.
- **It is not the cache user**. `dev-iam-shelfalign` is `Status=active`, `Authentication.Type=iam`, member of the user group attached to the replication group.
- **It is not a regional/AZ-wide issue**. Our prd backend is in the same region using the same IAM-auth pattern against a separate cluster `prd-shelfalign-cache` (user `prd-iam-shelfalign`, type=iam). prd's reauth landed at 2026-05-04T22:31:25Z (75 minutes after the dev failure) and **succeeded with no error logs** — see `logs/05-prd-control-reauth-success.log`. AWS Health Dashboard public `currentevents` shows nothing for ap-northeast-2 in this window. ElastiCache events on both clusters are empty.
- **It is reproducible-shaped, not random**. `ERR IAM Authentication service is not available` appeared exactly once across the 18-hour window. WRONGPASS appeared exactly once. Both at the deterministic time points predicted by AWS's documented IAM token TTL.

## Questions for AWS support

1. **What was the state of the IAM authentication backend serving `dev-shelfalign-cache` at 2026-05-04T21:16:50Z UTC?** Was there an internal disruption (control plane, throttle, transient validator failure) that we wouldn't see surfaced on the public Health Dashboard?

2. **Are there server-side logs/metrics available on AWS's side for this specific AUTH attempt** (the request landed on either `dev-shelfalign-cache-0001-001` or `0001-002`)? We could correlate against the request ID if your logs surface one.

3. **What is the official client-side guidance when receiving `ERR IAM Authentication service is not available`?** The ElastiCache documentation flags it as transient and recommends retry, but does not specify:
   - How many retries are appropriate?
   - What backoff?
   - Should clients keep the existing connection alive on the old (still-valid) token while retrying, or fail closed?

4. **Is there a documented AWS-side cause for the cluster being unable to recover `CLUSTER SLOTS` discovery once a node connection has been rejected with WRONGPASS, even with a freshly signed token on every reconnect attempt?** We are unsure whether this is solely an iovalkey/ioredis client-side state issue or whether the cache nodes are returning something during slot refresh that prevents recovery (we did not see node-side error logs in `/aws/elasticache/cluster/dev-shelfalign-cache/engine` during this period).

5. **Is there a way to reduce the blast radius of a single transient AUTH failure?** For example, does ElastiCache support a retry hint header, a known idempotency window, or a per-node "stale-but-still-accepted" grace period for IAM tokens that are within the AWS 12-hour active connection window?

## Workarounds we have applied client-side

(For reference, in case AWS has additional recommendations.)

1. **Auto-recreate of the iovalkey Cluster object** after N consecutive `ClusterAllFailedError` events — implemented at `apps/backend/src/providers/cache/cache.service.ts`. This terminates the wedged loop in seconds rather than 18 hours.
2. **Container-level health check** that exercises the cache via `GET /health` (returns 503 when PING does not return PONG within 3 s), so ECS replaces a wedged task instead of letting the ALB consider it healthy on a route that does not touch cache.
3. **Pending**: retry the `client.auth()` call with exponential backoff (3 attempts, 1s/2s/4s) keyed on `/IAM Authentication service is not available/`, so a single transient response does not waste the next 9.6-hour reauth window.
