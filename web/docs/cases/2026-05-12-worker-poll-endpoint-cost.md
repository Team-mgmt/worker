# Worker poll endpoint — WebSocket vs long-polling cost comparison

Date: 2026-05-12
Branch: `feat/worker-poll-endpoint`

## What we are pricing

Two new ways for a worker to claim a `ScanRequest` from the backend
(`apps/backend/src/routes/worker/jobs/`), so workers that cannot reach the
RDS instance directly — i.e. anything running outside our VPC — can still
participate in scan processing:

1. **WebSocket** — `GET /worker/jobs/ws` upgraded to a persistent WS
   connection. The backend polls Postgres every 2 s while the client is
   "ready" and pushes one `{type:"job", data:…}` frame per claim.
2. **HTTP long-poll** — `GET /worker/jobs/long-poll?wait=25`. Backend retries
   the same claim every 1 s for up to 25 s. Returns `200` + JSON body if a
   job was claimed, `204` otherwise. The client reconnects immediately.

Both reach the backend through the existing public ALB. The cost question
is whether either protocol moves the LCU (Load Balancer Capacity Unit) or
data-transfer needle enough to matter.

## Pricing inputs (Seoul, `ap-northeast-2`, list price, 2026)

| Resource                              | Unit                | Price    |
| ------------------------------------- | ------------------- | -------- |
| ALB — hourly                          | per ALB-hour        | $0.0225  |
| ALB — LCU                             | per LCU-hour        | $0.008   |
| Data transfer — out to Internet (≤10 TB/mo) | per GB        | $0.126   |
| Data transfer — out to same region    | per GB              | $0.020   |
| Data transfer — within same AZ        | per GB              | $0.000   |

One LCU is whichever of these is highest within the same hour:

| Dimension          | 1 LCU equals             |
| ------------------ | ------------------------ |
| New connections    | 25 new conns / second    |
| Active connections | 3,000 concurrent conns   |
| Processed bytes    | 1 GB / hour              |
| Rule evaluations   | 1,000 / second           |

Workers run outside AWS in this scenario, so all egress is priced at the
**Internet** rate. If we ever co-locate workers in the same region the
egress collapses to $0.02 / GB and intra-AZ traffic is free.

## Scenarios

We model three realistic worker counts. Numbers below are per month
(720 h). The workload assumption: workers spend most of their time idle
waiting for jobs (peak load is bursty), so "idle hours" dominate the bill.

### Per-attempt traffic accounting

Each *long-poll iteration* costs roughly:

- Request line + headers (Authorization, Cookie, sentry-trace, etc.): ~700 B
- Response status + headers: ~250 B
- TLS overhead amortised over keep-alive: ~50 B / req
- Empty 204 body: 0 B; populated 200 body (`ClaimedJob`): ~400 B

Treat an empty round trip as **~1 KB**, a job dispatch as **~1.4 KB**.
At `wait=25` an idle worker triggers one round trip every 26 s.

Each *WebSocket "no job" cycle* costs roughly:

- One ping frame (2 B header + 4 B mask + 0 B payload from client; server
  pong is symmetric): ~12 B every 30 s
- One DB-side claim attempt per 2 s **happens entirely in the VPC**, so it
  does **not** transit the ALB. Only the WS frame to the worker counts.

A WS job dispatch frame is a single `{type:"job", data:{…}}` message:
~370 B payload + 2–4 B frame header. Plus the one-time HTTP upgrade
(~1.2 KB request, 200 B response).

### 10 workers, ~95 % idle

Assume each worker processes 60 jobs/day → ~50,400 jobs/month total
across 10 workers; the rest of the time they are waiting.

#### Long-poll

- Iterations / sec: 10 workers / 26 s ≈ **0.385 new conns/s**
- Active connections (during the 25 s hold): ~**10** average
- Processed bytes / hr: 0.385 conns/s × 3,600 s × 1,000 B ≈ **1.39 MB/hr** ≈ 1.0 GB/mo
  - plus 50,400 jobs × 400 B = ~20 MB/mo job payloads (negligible)
- LCU dimension max:
  - new_conns: 0.385 / 25 = **0.0154 LCU**
  - active_conns: 10 / 3,000 = 0.0033 LCU
  - processed_bytes: 1.39 MB/hr ÷ 1 GB = 0.0014 LCU
  - → **0.0154 LCU**
- ALB cost: $0.0225 × 720 + $0.008 × 0.0154 × 720 = $16.20 + **$0.09**
- DT (Internet): ~1 GB × $0.126 = **$0.13**
- **Total marginal: $0.22 / mo**

#### WebSocket

- New connections / sec: workers reconnect only on ALB idle (~3,600 s if
  we bump the timeout, default 60 s otherwise). Assume operator raises
  idle timeout to 3,600 s once they see the WS gateway: 10 / 3,600 ≈
  **0.003 new conns/s**.
- Active connections: **10** (persistent)
- Processed bytes / hr: 10 × (12 B every 30 s) × 120 = ~14 KB/hr; plus the
  ~50,400 job frames / mo × 374 B ≈ 18 MB/mo total. Effectively zero.
- LCU dimension max:
  - new_conns: 0.003 / 25 = 0.00012 LCU
  - active_conns: 10 / 3,000 = **0.0033 LCU**
  - processed_bytes: ~0
  - → **0.0033 LCU**
- ALB cost: $0.0225 × 720 + $0.008 × 0.0033 × 720 = $16.20 + **$0.019**
- DT (Internet): ~20 MB ≈ **$0.0025**
- **Total marginal: $0.022 / mo**

> At 10 workers, both protocols ride the fixed $16.20 ALB-hour fee; the
> difference is **$0.20 / mo** — meaningless.

### 100 workers, ~95 % idle

#### Long-poll

- new_conns: 100 / 26 ≈ 3.85/s → 3.85 / 25 = **0.154 LCU**
- active_conns: 100 / 3,000 ≈ 0.033 LCU
- processed_bytes: 3.85 × 1,000 B/s × 3,600 = 13.9 MB/hr ≈ 0.014 LCU
- → **0.154 LCU**
- ALB LCU cost: $0.008 × 0.154 × 720 = **$0.89**
- DT: ~10 GB × $0.126 = **$1.26**
- **Total marginal: $2.15 / mo**

#### WebSocket

- new_conns: 100 / 3,600 ≈ 0.028 → 0.028 / 25 = 0.0011 LCU
- active_conns: 100 / 3,000 = **0.033 LCU**
- processed_bytes: ~0
- → **0.033 LCU**
- ALB LCU cost: $0.008 × 0.033 × 720 = **$0.19**
- DT: ~180 MB × $0.126 = **$0.023**
- **Total marginal: $0.22 / mo**

> WS is ~10× cheaper at 100 workers, but the absolute gap is **<$2/mo**.

### 1,000 workers, ~95 % idle

#### Long-poll

- new_conns: 1,000 / 26 ≈ 38.5/s → **1.54 LCU**
- active_conns: 1,000 / 3,000 = 0.33 LCU
- processed_bytes: 138 MB/hr ≈ 0.14 LCU
- → **1.54 LCU**
- ALB LCU cost: $0.008 × 1.54 × 720 = **$8.86**
- DT: ~100 GB × $0.126 = **$12.60**
- **Total marginal: $21.50 / mo**

#### WebSocket

- new_conns: 1,000 / 3,600 ≈ 0.28 → 0.011 LCU
- active_conns: 1,000 / 3,000 = **0.33 LCU**
- processed_bytes: ~negligible
- → **0.33 LCU**
- ALB LCU cost: $0.008 × 0.33 × 720 = **$1.90**
- DT: ~1.8 GB × $0.126 = **$0.23**
- **Total marginal: $2.13 / mo**

## Side-by-side

|                       | 10 workers | 100 workers | 1,000 workers |
| --------------------- | ---------- | ----------- | ------------- |
| Long-poll ALB LCU     | $0.09      | $0.89       | $8.86         |
| Long-poll DT          | $0.13      | $1.26       | $12.60        |
| **Long-poll total**   | **$0.22**  | **$2.15**   | **$21.50**    |
| WebSocket ALB LCU     | $0.02      | $0.19       | $1.90         |
| WebSocket DT          | $0.003     | $0.02       | $0.23         |
| **WebSocket total**   | **$0.02**  | **$0.22**   | **$2.13**     |
| WS savings vs LP      | $0.20      | $1.93       | $19.37        |

The fixed $16.20/mo ALB-hour fee dominates either way — we are paying it
regardless of whether the worker job endpoint exists.

## What actually moves cost at scale

1. **HTTP headers**, not WS payloads. Long-poll burns ~700 B of headers
   per attempt; WS amortises that across the lifetime of the connection.
2. **New-connection LCU**. Long-poll generates a fresh TCP+TLS handshake
   every 26 s. WS only pays this on first connect (and on reconnects after
   ALB idle / network blip). At 1,000+ workers, this becomes the dominant
   LCU dimension for long-poll.
3. **ALB idle timeout**. The WS savings above assume the operator bumps
   the ALB idle timeout to 3,600 s (max 4,000 s). At the default 60 s the
   WS new-connection rate increases ~60×; LCU jumps to ~0.026 → ~$0.15/mo
   at 1,000 workers. Still cheaper than long-poll, but the gap narrows.

## What does *not* move cost meaningfully

- **DB load** is unaffected by transport choice. Both protocols issue the
  same `UPDATE … RETURNING (SELECT … FOR UPDATE SKIP LOCKED)` statement
  at the same cadence per active worker. The WS gateway polls every 2 s
  (vs. long-poll's 1 s), so WS is actually a touch *gentler* on Postgres.
- **Compute (Fargate/EC2)**. The backend's per-connection overhead is a
  few KB of heap state and a Node.js timer for either path.

## Practical recommendation

- For ≤100 external workers, the dollar gap is < $2/mo. Either protocol
  is fine — pick whichever has a better client-library story for the
  worker runtime. Long-poll is easier to debug (every request shows up
  in ALB / access logs), works through restrictive HTTP proxies, and
  needs no special framing.
- Past ~500 workers, prefer WebSocket. The LCU / DT cost diverges
  roughly linearly with worker count, and at 1,000 workers WS comes out
  ~10× cheaper.
- If the deployment terminates TLS on Cloudflare or another edge in
  front of the ALB, double-check the upstream's idle-timeout and
  per-connection pricing — those can dominate either AWS cost.

## Implementation notes (for follow-up)

- Stale-job cleanup currently lives in the Python worker
  (`_run_loop` in `shelfalign-worker/worker/worker/scan.py`). If we ever rely
  *only* on external workers, we will need a backend cron (e.g. via
  `@nestjs/schedule`) that runs the same `UPDATE` against
  `ScanRequestJob` and `ScanRequest`.
- `Postgres LISTEN/NOTIFY` from `ScanRequest` insert triggers would
  remove the 2-second polling tail-latency at the cost of one
  dedicated `pg` connection per backend process. Worth revisiting if
  job arrival-rate variance starts to matter.
