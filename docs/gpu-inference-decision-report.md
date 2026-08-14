# GPU inference decision and benchmark report

Date: 2026-08-14

## Purpose

ShelfAlign originally ran YOLO OBB detection and PaddleOCR on the CPU of the AWS worker. This report records why remote GPU inference was introduced, which providers were evaluated, and the first production measurements. It is intended to prevent later infrastructure changes from being judged using only one successful image.

The public API, RDS catalog matching, final decisions, and S3 artifact handling remain on AWS. Only YOLO OBB detection and PaddleOCR are offloaded to the remote GPU. The user-mode endpoint `/inference/find_target_book` and the administrator vision pipeline can use this remote path. A remote failure falls back to the existing local CPU path when `REMOTE_VISION_FALLBACK_LOCAL=true`.

## Baseline: AWS CPU OCR

The existing production worker had no GPU and ran PaddleOCR on CPU. In the 34-spine shelf sample, individual OCR logs commonly showed about 3.9 to 5.8 seconds per spine. This implies roughly 130 to 170 seconds for OCR across all 34 spines before database matching and artifact work. Other observed production runs also exceeded one minute end to end.

This is an operational baseline reconstructed from service logs, not a controlled benchmark suite. It must not be used as a final paper result until the same fixed images and ground truth are executed repeatedly on each infrastructure option.

## Options considered

### Keep inference on the existing AWS CPU worker

Advantages:

- No new provider or network boundary.
- Existing API and failure behavior stay unchanged.
- No GPU idle cost.

Disadvantages:

- OCR dominates latency.
- A shelf containing 30 or more books can take over one minute.
- The small worker instance is vulnerable to memory pressure and swap thrashing.

Decision: retain only as a fallback path.

### AWS GPU EC2

Advantages:

- Predictable warm latency when the instance remains running.
- Full control over CUDA, model files, networking, and process lifetime.
- Can be kept inside AWS alongside the API and database.

Disadvantages:

- The GPU instance is billed while running, including idle time.
- Requires GPU quota, instance provisioning, CUDA/driver maintenance, security-group configuration, deployment automation, and start/stop operations.
- Replacing the current combined web instance would increase operational risk; a separate inference instance would be safer.

Decision: defer until traffic or latency requirements justify an always-warm inference service.

### fal.ai serverless GPU

A fal.ai implementation was prototyped, but custom serverless deployment returned `Insufficient permissions`. fal.ai support subsequently stated that this capability is available to Enterprise or high-usage customers with expected monthly usage around USD 5,000 to 10,000 or more.

Decision: rejected for the current prototype and pilot scale. No fal.ai credential is required by the active implementation.

### Modal serverless GPU

Modal allowed immediate deployment of the custom YOLO and PaddleOCR container on an NVIDIA L4. It supports per-second billing, scale-to-zero, persistent model volumes, private proxy-token authentication, and a maximum-container limit.

Decision: selected for the current prototype and presentation environment.

## Implemented architecture

```text
Mobile or backoffice client
  -> AWS EC2 FastAPI worker
  -> private Modal L4 endpoint
       -> YOLO OBB detection
       -> perspective crops
       -> PaddleOCR
  -> AWS EC2 parsing and target/catalog matching
  -> response and optional S3 artifacts
```

The GPU path does not replace OCR with a VLM. It accelerates the existing deterministic YOLO and PaddleOCR pipeline. A VLM remains a possible conditional fallback for difficult crops, but it is not part of these measurements.

Active Modal controls:

- GPU: one NVIDIA L4
- `min_containers=0`: scale to zero when unused
- `max_containers=1`: cap GPU concurrency and cost
- `scaledown_window=600`: keep the container warm for 10 minutes after the last request
- private endpoint protected by `Modal-Key` and `Modal-Secret`
- persistent Paddle model cache in a Modal Volume
- local CPU fallback remains enabled on AWS

`scaledown_window=600` is an idle shutdown delay, not a recurring timer. With no requests, no GPU container is created. After a request, the container remains billable for up to 10 idle minutes and then scales to zero. Every new request during that interval resets the idle window.

## Production measurements

Test workload:

- Endpoint: `/inference/find_target_book`
- Shelf image: 35 detected spines
- First target: `콩가루 수사단 : 주영하 장편소설`
- Second target: `사막으로 떠난 인어 : 지병림 소설집`
- Model SHA256: `ca5325892bc9f9437f0bbcd9a99b89c1b5ff8d0a0e8b17bb815b384b251255d4`

| Time | Container state | Spines | Detection | OCR | Round trip | Result |
|---|---|---:|---:|---:|---:|---|
| 00:57:58 | cold, before persistent-cache verification | 35 | 8.4 s | 4.5 s | 47.6 s | target 1 found at order 13, score 93.3 |
| 01:38:59 | cold, more than 10 minutes after prior request | 35 | 8.6 s | 5.0 s | 37.1 s | target 1 found at order 13, score 93.3 |
| 01:40:52 | warm, 113 seconds after prior completion | 35 | 0.1 s | 2.2 s | 4.7 s | target 2 found at order 26, score 87.7 |

Interpretation:

- The two requests separated by about 41 minutes were cold starts.
- Persistent model caching reduced the observed cold round trip from 47.6 to 37.1 seconds, but did not remove container and model initialization.
- The warm request completed end to end in 4.7 seconds, including transfer and target matching.
- Warm YOLO detection dropped to 0.1 seconds and OCR for all 35 detected spines took 2.2 seconds.
- Detection count stayed at 35 and both requested books were found. No remote failure or CPU fallback appeared in these logs.
- Compared with the reconstructed CPU OCR baseline of 130 to 170 seconds for 34 spines, the 2.2-second warm OCR measurement indicates a large acceleration. This comparison is directional because the CPU and GPU data were not collected by a single controlled harness.

## Current conclusion

Modal L4 meets the presentation target when warm: the measured user-mode response was 4.7 seconds, below the 10-second target. The remaining user-visible issue is cold-start latency, not steady-state GPU inference.

For demonstrations, send one warm-up image before participants begin and keep subsequent requests within 10 minutes. For production, do not claim a guaranteed 4.7-second response until repeated benchmarks report cold and warm latency separately.

AWS GPU EC2 should be reconsidered when at least one of these conditions is true:

- the first request must always meet a strict latency target;
- requests are frequent enough that the Modal container stays warm most of the day;
- measured Modal idle and compute cost approaches an always-on GPU instance;
- provider/network constraints require inference to remain within AWS.

## Required follow-up evaluation

Run the same fixed dataset separately for user and administrator modes, and separately for Nowon Central Library and Dobong Ainara Library. Record at least:

- 10 or more cold requests and 30 or more warm requests;
- total latency, remote round trip, detection, OCR, parsing, DB query, reranking, and S3 upload latency;
- median, P90, P95, minimum, and maximum latency;
- detected-spine count and peak worker memory;
- OCR CER/WER and call-number exact accuracy;
- target-book Top-1 accuracy and location-order accuracy;
- administrator matching Top-1/Top-3 accuracy and false-confirmation rate;
- Modal GPU seconds and cost per successful scan;
- accuracy comparison against the unchanged CPU fallback using identical model SHA and OCR settings.

The current measurements establish feasibility and a presentation configuration. They are not a replacement for the ground-truth evaluation harness.
