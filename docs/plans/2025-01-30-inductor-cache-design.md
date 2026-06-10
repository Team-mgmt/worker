# Inductor Cache Design

## Problem

`torch.compile()` with `torch._inductor` compiles CUDA kernels on first inference. For RoMaV2, this takes ~8 minutes, causing CodeDeploy validation timeouts and slow instance startup.

## Solution

Cache compiled kernels in S3, keyed by RoMaV2 version and GPU architecture. Download on deploy, upload after first warmup.

## Cache Key

```
inductor-{romav2_git_hash}-{gpu_arch}.tar.gz
```

Examples:
- `inductor-a1b2c3d-sm_86.tar.gz` (A10G)
- `inductor-a1b2c3d-sm_75.tar.gz` (T4)

## S3 Location

```
s3://{bucket}/{prefix}/inductor-cache/{cache_key}.tar.gz
```

Reuses existing bucket/prefix from `wheels/.s3-bucket` and `wheels/.s3-prefix`.

## Local Cache Location

```
${MODEL_CACHE_DIR}/inductor/
```

Service template already sets `TORCHINDUCTOR_CACHE_DIR` to this path. No changes needed.

## Flow

### Build Time (CI Workflow)

In `.github/workflows/build-develop-gpu.yaml`, generate `wheels/.romav2-git-hash` alongside wheel cache keys:

```bash
# Get romav2 git hash for inductor cache
ROMAV2_GIT_HASH=$(cd vendor/romav2 && git rev-parse --short HEAD)
echo "${ROMAV2_GIT_HASH}" > wheels/.romav2-git-hash
```

### Deploy Time (after_install.sh)

```bash
# Get cache key components for S3
ROMAV2_GIT_HASH=$(cat wheels/.romav2-git-hash)
GPU_ARCH=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '.' | sed 's/^/sm_/')
INDUCTOR_CACHE_KEY="inductor-${ROMAV2_GIT_HASH}-${GPU_ARCH}"

# Local path (service template already sets TORCHINDUCTOR_CACHE_DIR here)
INDUCTOR_CACHE_DIR="${MODEL_CACHE_DIR}/inductor"
mkdir -p "${INDUCTOR_CACHE_DIR}"
chown "${SERVICE_USER}:${SERVICE_GROUP}" "${INDUCTOR_CACHE_DIR}"

# Write cache key for Python to know what to upload later
echo "${INDUCTOR_CACHE_KEY}" > "${INDUCTOR_CACHE_DIR}/.cache-key"

# Try to download from S3 (non-fatal if missing)
if aws s3 cp "${S3_BASE}/inductor-cache/${INDUCTOR_CACHE_KEY}.tar.gz" /tmp/inductor-cache.tar.gz 2>/dev/null; then
    echo "Inductor cache found, extracting..."
    tar -xzf /tmp/inductor-cache.tar.gz -C "${INDUCTOR_CACHE_DIR}"
    rm /tmp/inductor-cache.tar.gz
    touch "${INDUCTOR_CACHE_DIR}/.downloaded"  # Marker: don't upload later
else
    echo "No inductor cache found for ${INDUCTOR_CACHE_KEY}, will compile on first run"
fi

# Runtime torch.compile writes into this directory as SERVICE_USER
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INDUCTOR_CACHE_DIR}"
```

### Runtime (worker/main.py)

After successful warmup, upload cache if it was freshly compiled. Uses async subprocess for non-blocking execution:

```python
async def upload_inductor_cache_if_needed() -> None:
    """Upload inductor cache to S3 if it was just compiled (not downloaded)."""
    cache_dir = os.environ.get("TORCHINDUCTOR_CACHE_DIR")
    if not cache_dir:
        return

    # Skip if cache was downloaded (not freshly compiled)
    if (Path(cache_dir) / ".downloaded").exists():
        return

    cache_key = (Path(cache_dir) / ".cache-key").read_text().strip()
    # ... build s3_path from wheels/.s3-bucket and .s3-prefix ...

    # Create tarball and upload using async subprocess
    tar_proc = await asyncio.create_subprocess_exec("tar", "-czf", tarball, "-C", cache_dir, ".")
    await tar_proc.wait()

    s3_proc = await asyncio.create_subprocess_exec("aws", "s3", "cp", tarball, s3_path)
    await s3_proc.wait()
```

Called after warmup as a background task:

```python
if warmup_matcher(str(WARMUP_IMAGE_A), str(WARMUP_IMAGE_B)):
    print("[Matcher] Warmup completed successfully")
    asyncio.create_task(upload_inductor_cache_if_needed())
```

## Concurrency

Simple first-write-wins. Multiple instances may upload simultaneously for the same cache key. This wastes some bandwidth but is harmless since content is identical.

## Files Changed

| File | Change |
|------|--------|
| `wheels/.romav2-git-hash` | New file (build time) |
| `scripts/codedeploy/after_install.sh` | Add inductor cache download |
| `worker/main.py` | Add `upload_inductor_cache_if_needed()` |

## Expected Results

- **First deployment per GPU arch**: ~8 min warmup (unchanged), then cache uploaded
- **Subsequent deployments**: Cache downloaded, warmup ~seconds instead of ~8 min
