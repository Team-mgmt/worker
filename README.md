# ShelfAlign Worker

FastAPI worker for ShelfAlign library shelf analysis.

## Responsibilities

- Analyze shelf photos with a VLM and return book-spine candidates.
- Optionally run local OCR fallback for selected spines.
- Match OCR/title/call-number evidence against the library catalog tables.
- Sync catalog records from Data4Library for target libraries.

## Local Run

```bash
uv venv
uv pip install -r requirements.txt
python -m fastapi dev worker/api/server.py --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Main endpoint:

```text
POST /inference/analyze_vlm
```

## Environment

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
OPENAI_API_KEY=...
VLM_MODEL=gpt-4o-mini
JUNGBO_NARU_API_KEY=...
```

`PADDLE_FALLBACK_MAX_SPINES` defaults to `0`; set it only when PaddleOCR is installed and you want per-spine OCR fallback.
