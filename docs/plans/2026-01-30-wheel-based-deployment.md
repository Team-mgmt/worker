# Wheel-Based Deployment Design

## Overview

Migrate CodeDeploy deployment from shipping `.venv` directory to pre-built wheels, similar to the Dockerfile pattern.

## Goals

1. **Faster deployments** - Install from local wheels instead of downloading from PyPI
2. **Smaller artifacts** - ~2-3GB (wheels) vs ~7GB (.venv)
3. **Reproducibility** - Target servers install exact same binaries tested in CI

## Architecture

### Build Phase (CI)

```
uv sync → build wheels → cache wheels → export requirements.txt → zip (wheels + source)
```

1. Export requirements from lockfile
2. Build PyPI wheels (cached by arch + uv.lock hash)
3. Build romav2 wheel (cached by arch + vendor source hash)
4. Update requirements.txt with wheel hashes
5. Zip artifact excluding `.venv`

### Deploy Phase (Target)

```
destroy old venv → create fresh venv → pip install from wheels
```

1. Remove existing `.venv` (clean slate)
2. Create fresh Python venv
3. Install from pre-built wheels with `--no-index --find-links`
4. No network access required for dependencies

## Caching Strategy

Two separate caches, both architecture-aware:

| Cache | Key Pattern | Contents |
|-------|-------------|----------|
| PyPI wheels | `pypi-${ARCH}-${hash(uv.lock)}` | Third-party dependency wheels |
| romav2 wheel | `romav2-${ARCH}-${hash(vendor/romav2/**)}` | Vendored romav2 wheel |

Cache keys stored in `wheels/.pypi-cache-key` and `wheels/.romav2-cache-key` to determine rebuild necessity.

## File Changes

### 1. `.github/workflows/build-develop-gpu.yaml`

Add architecture detection:
```yaml
- name: Get architecture
  id: arch
  run: echo "arch=$(uname -m)" >> $GITHUB_OUTPUT
```

Add wheels to cache:
```yaml
- name: Set up cache
  uses: namespacelabs/nscloud-cache-action@v1
  with:
    cache: |
      pnpm
      uv
      wheels
```

Add wheel build step:
```yaml
- name: Export requirements
  run: |
    uv sync --locked --no-dev --group gpu --no-editable
    uv export --no-emit-project --no-dev --group gpu \
      --no-editable --no-emit-package romav2 > requirements.txt

- name: Build wheels
  env:
    ARCH: ${{ steps.arch.outputs.arch }}
  run: |
    mkdir -p wheels/pypi wheels/romav2

    # Check PyPI wheels cache
    PYPI_CACHE_KEY="pypi-${ARCH}-${{ hashFiles('uv.lock') }}"
    if [ ! -f "wheels/.pypi-cache-key" ] || [ "$(cat wheels/.pypi-cache-key)" != "${PYPI_CACHE_KEY}" ]; then
      echo "Building PyPI wheels..."
      rm -rf wheels/pypi/*
      pip wheel --no-cache-dir --wheel-dir wheels/pypi -r requirements.txt
      echo "${PYPI_CACHE_KEY}" > wheels/.pypi-cache-key
    else
      echo "PyPI wheels cache hit, skipping build"
    fi

    # Check romav2 cache
    ROMAV2_CACHE_KEY="romav2-${ARCH}-${{ hashFiles('vendor/romav2/**') }}"
    if [ ! -f "wheels/.romav2-cache-key" ] || [ "$(cat wheels/.romav2-cache-key)" != "${ROMAV2_CACHE_KEY}" ]; then
      echo "Building romav2 wheel..."
      rm -rf wheels/romav2/*
      pip wheel --no-deps --wheel-dir wheels/romav2 ./vendor/romav2
      echo "${ROMAV2_CACHE_KEY}" > wheels/.romav2-cache-key
    else
      echo "romav2 wheel cache hit, skipping build"
    fi

- name: Update requirements with wheel hashes
  run: bash scripts/update-hashes.sh "wheels/pypi" "requirements.txt"
```

Exclude `.venv` from zip:
```yaml
- name: Create deployment revision
  run: |
    zip -r "${REVISION_NAME}" . \
      -x ".git/*" \
      -x ".github/*" \
      -x ".venv/*" \
      -x "*.pyc" \
      ...
```

### 2. `scripts/codedeploy/after_install.sh`

Replace uv sync with wheel-based install:
```bash
echo "Installing application dependencies..."

cd "${APP_DIR}"

# Remove old venv if exists (clean slate)
if [ -d ".venv" ]; then
    echo "Removing old virtual environment..."
    rm -rf .venv
fi

# Create fresh venv
echo "Creating virtual environment..."
python3 -m venv .venv

# Install from pre-built wheels (no network needed)
echo "Installing from wheels..."
.venv/bin/pip install --no-cache-dir --no-index \
    --find-links="${APP_DIR}/wheels/pypi" \
    --find-links="${APP_DIR}/wheels/romav2" \
    -r "${APP_DIR}/requirements.txt"

# Install romav2 separately (no deps, already satisfied)
.venv/bin/pip install --no-cache-dir --no-index --no-deps \
    --find-links="${APP_DIR}/wheels/romav2" \
    romav2

echo "Dependencies installed successfully"
```

### 3. `scripts/codedeploy/templates/shelfalign-worker.service`

Update ExecStart to use venv Python:
```ini
ExecStart=/opt/shelfalign-worker/.venv/bin/python -m worker
```

## Performance Comparison

| Metric | Current | New |
|--------|---------|-----|
| Artifact size | ~7GB | ~2-3GB |
| Target install time | 5-10min (network) | ~1min (local) |
| Network required | Yes (PyPI) | No |
| CI build (cold) | ~5min | ~10min (wheel build) |
| CI build (cached) | ~2min | ~1min (skip wheel build) |

## Rollback

If issues occur, revert to the previous approach by:
1. Reverting workflow changes
2. Reverting after_install.sh changes
3. Reverting systemd service template
