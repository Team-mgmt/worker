# QMR Worker

Worker service that processes scanned exam papers for the QMR (Quick Mark Recognition) platform.
It pulls scan jobs from the database, aligns each scan to its template, detects bubble marks and
QR codes, and writes structured results back so the upstream API can produce graded submissions.

## What it does

- Pulls `ScanRequestJob` rows from PostgreSQL and processes them in order
- Downloads the source image and the matching template (`.svg` or raster) from S3
- Aligns the scan to the template using **RoMaV2** dense feature matching
- Reads the rectified bubble grid: per-area binarization, morphology, and fill-ratio scoring
- Detects QR codes (via `zxing-cpp`) for paper / page identification
- Resolves student identifiers through the backend API
- Persists `ExamSubmission` / `DraftSubmission` rows with per-problem answers, plus annotated
  debug images on disk and S3
- Reports liveness via an HTTP health endpoint and a per-row `heartbeatAt` updater
- Cooperates with EC2 Spot interruption notices and ECS `SIGTERM` for graceful shutdown

## Architecture

```text
┌────────────────────────────────────────────────────────────┐
│                       worker/main.py                       │
│  bootstrap → SSM/.env → DB engine → S3 client → ScanWorker │
└──────┬──────────────────────┬───────────────────┬──────────┘
       │                      │                   │
       ▼                      ▼                   ▼
  ┌──────────┐          ┌────────────┐      ┌───────────┐
  │  health  │          │ ScanWorker │      │ heartbeat │
  │  server  │          │   (loop)   │      │   task    │
  └──────────┘          └─────┬──────┘      └───────────┘
                              │
            ┌─────────────────┼──────────────────┐
            ▼                 ▼                  ▼
      ┌──────────┐      ┌──────────┐       ┌──────────┐
      │ Processor│      │  Cache   │       │ Loggers  │
      │   V1     │◄────►│ (SVG→PNG │       │ (DB +    │
      │ (RoMaV2) │      │  thresh) │       │ console) │
      └────┬─────┘      └──────────┘       └──────────┘
           │
           ▼
    DocumentMatcher (RoMaV2, GPU-aware singleton)
```

Key modules under `worker/`:

| Path                       | Responsibility                                                           |
| -------------------------- | ------------------------------------------------------------------------ |
| `main.py`                  | Entrypoint, env/SSM bootstrap, signal handlers, warmup                   |
| `worker/scan.py`           | Job loop: claim → download → process → persist → cleanup                 |
| `worker/spot.py`           | EC2 Spot interruption monitor                                            |
| `worker/disk.py`           | Background disk-cache reaper                                             |
| `processors/v1.py`         | OMR pipeline: alignment, area extraction, bubble scoring                 |
| `matcher.py`               | RoMaV2 model singleton + warmup                                          |
| `cache.py`                 | Content-addressable cache for rasterized SVG templates and thresholds    |
| `api_client.py`, `auth.py` | Worker→API JWT auth (ES512), bastion DB credential creator               |
| `bastion.py`               | RDS bastion-lease session for prod DB access                             |
| `health.py`                | Liveness/readiness HTTP endpoint                                         |
| `ssm.py`                   | Loads parameters from AWS SSM into env                                   |
| `generated/`               | SQLAlchemy models generated via `sqlacodegen_custom`                     |

## Tech stack

- **Python 3.12**, managed by [`uv`](https://github.com/astral-sh/uv)
- **FastAPI** (health server), **SQLAlchemy 2 (async)** + `psycopg`
- **OpenCV**, **Pillow**, **cairosvg**, **zxing-cpp**
- **RoMaV2** (`vendor/romav2`, editable local wheel) on PyTorch — optional GPU
- **aioboto3** for S3, **PyJWT** (ES512) for worker→API auth
- **Sentry** + custom OTel-style metric instrumentation
- **pytest** + `pytest-asyncio`, `ruff`, `mypy`

## Project layout

```text
.
├── worker/              # application package
│   ├── main.py
│   ├── processors/      # versioned OMR pipelines (v1 = RoMaV2)
│   ├── worker/          # scan loop, spot/disk monitors
│   ├── loggers/         # console + database loggers
│   └── generated/       # sqlacodegen output (do not edit by hand)
├── tests/               # pytest suite (mirrors worker/ layout)
├── stubs/               # mypy stubs
├── vendor/romav2/       # local editable wheel for the matcher
├── sqlacodegen_custom/  # custom sqlacodegen generator (snake_case declarative)
├── scripts/             # build, deploy, hash, schema-regen utilities
├── assets/warmup/       # GPU model warmup images
├── docs/                # design + handoff docs (see below)
├── audit/               # security/architecture audit notes
├── Dockerfile           # CPU image
├── Dockerfile.gpu       # CUDA image used in prod
├── docker-compose.yml   # local stack
├── appspec.yml          # AWS CodeDeploy spec
└── pyproject.toml
```

## Setup

```bash
uv sync                    # runtime deps only
uv sync --group dev        # + ruff, mypy, type stubs, opencv-python (GUI build)
uv sync --group test       # + pytest, pytest-asyncio, pytest-cov, respx, aioresponses
uv sync --group gpu        # + torch, torchvision, einops (CUDA build of the matcher)
uv sync --group schema     # + sqlacodegen + inflect (DB → SQLAlchemy model regen)
```

Groups can be combined, e.g. `uv sync --group dev --group test`.

### Dependency groups

| Group    | When you need it                                                                         |
| -------- | ---------------------------------------------------------------------------------------- |
| `dev`    | Local development — linting (`ruff`), type-checking (`mypy`), and IDE-friendly OpenCV    |
| `test`   | Running the `pytest` suite, including async HTTP/AWS mocks                               |
| `gpu`    | Building/running the CUDA flavor of RoMaV2; required for `Dockerfile.gpu` and prod GPU   |
| `schema` | Regenerating `worker/generated/models.py` from the live DB via `scripts/generate.sh`, which drives `sqlacodegen` with the project-local `declarative_snake` generator from `sqlacodegen_custom/` |

Add new packages with `uv add <pkg>` (or `uv add --group <group> <pkg>`); do not hand-edit
`pyproject.toml`.

## Configuration

The worker reads config from AWS SSM first (when `SSM_PARAMETER_PATH` is set), then `.env`.
Required variables:

| Variable             | Purpose                                                  |
| -------------------- | -------------------------------------------------------- |
| `DATABASE_URL`       | PostgreSQL DSN (`postgres://` / `postgresql://` accepted) |
| `S3_BUCKET_NAME`     | Bucket for scan images and templates                     |
| `API_BASE_URL`       | Backend API base URL (used for student-ID resolution)    |
| `AWS_REGION`         | AWS region for S3/SSM                                    |
| `SENTRY_DSN`         | Optional Sentry DSN                                      |
| `BASTION_*`          | Optional RDS bastion lease config                        |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | Heartbeat cadence (default in `consts.py`) |

Do not commit real credentials — `.env` is gitignored for a reason.

## Running

Long-running worker (consumes jobs from the DB):

```bash
uv run -m worker.main
```

One-shot local processing of a single image or directory (useful for debugging):

```bash
uv run -m worker.main local path/to/image_or_dir
```

Annotated debug outputs (`annotated_*.png`, `thresh_*.png`, …) are written next to the input.

### Docker

```bash
docker compose up --build           # CPU
QMR_WORKER_DOCKERFILE=Dockerfile.gpu docker compose up --build   # GPU
```

The compose stack also provisions writable cache volumes for HuggingFace/Inductor/Triton.

## Testing & quality gates

Per `AGENTS.md`, both must pass before committing:

```bash
uv run -m ruff check worker/
uv run -m mypy worker/
uv run -m pytest                    # add --cov for coverage
```

Use conventional commit messages (`feat:`, `fix:`, `chore:`, …).

## Related docs

- [OMR Downscale README (Korean)](docs/omr_downscale_readme_ko.md)
- [OMR Recognition Downscale Handoff](docs/omr_recognition_downscale_handoff_en.md)
- [Before/After Evaluation Template](docs/omr_downscale_before_after_eval_template_en.md)
- [Team Review Checklist](docs/omr_downscale_team_review_checklist_en.md)
- [Risks and Safeguards](docs/omr_downscale_risks_and_safeguards_en.md)
- [`AGENTS.md`](AGENTS.md) — committing & dependency rules (also linked as `CLAUDE.md`)
