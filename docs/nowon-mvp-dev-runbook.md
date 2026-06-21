# Nowon Jungang MVP Dev Runbook

This runbook documents the local MVP environment for ShelfAlign.

## Target

- Library: Nowon Jungang Library
- Data4Library `libCode`: `111058`
- MVP room: `종합자료실`
- MVP catalog range: Korean literature, KDC `810-819`

## Local Services

PostgreSQL is expected to run from the web repo Docker Compose.

```text
Host: localhost
Port: 5432
Database: shelfalign
User: shelfalign
Password: shelfalign
```

Worker API runs on port `8001` so it does not collide with older worker processes on `8000`.

```powershell
scripts\run_worker_8001.cmd
```

Backoffice should point at the worker with:

```env
VITE_WORKER_BASE_URL=http://localhost:8001
```

## Environment

Copy `.env.example` to `.env` and fill in secrets locally.

Required for catalog sync:

```env
JUNGBO_NARU_API_KEY=...
```

Required for VLM image analysis:

```env
OPENAI_API_KEY=...
```

Do not commit `.env`.

## VLM Shelf Analysis

Backoffice uploads a shelf image to:

```text
POST /inference/analyze_vlm
```

The worker flow is:

1. Save uploaded image under `outputs/uploads/`.
2. Send the image to the configured VLM.
3. Parse a strict JSON response with detected spines, OCR text, call number, title, author, confidence, and normalized bbox.
4. Convert bboxes to image pixels.
5. Match OCR/VLM text against Prisma catalog tables:
   - `LibraryBook`
   - `LibraryHolding`
6. Return detections to the backoffice.

Current MVP intentionally does not persist VLM analysis sessions. The endpoint uses `persist=False` until worker persistence is moved from the legacy `scan_sessions/detections` tables to Prisma `ShelfScanSession/ShelfDetection`.

## Matching Rule

Low-confidence candidates must not be displayed as confirmed books.

Current threshold:

```text
score >= 75.0 -> confirmed match candidate
score < 75.0 -> needs review / unmatched
```

For `needs_review` items, the UI should display:

- OCR/VLM-recognized book text
- recognized call number
- top candidate score
- DB candidates as candidates only

## DataGrip

Use this connection:

```text
Host: localhost
Port: 5432
Database: shelfalign
Username: shelfalign
Password: shelfalign
```

Useful queries:

```sql
SELECT COUNT(*) FROM "LibraryBook";
SELECT COUNT(*) FROM "LibraryHolding";

SELECT
  b.bookname,
  b.authors,
  h."callNumber",
  h."shelfLocName"
FROM "LibraryHolding" h
JOIN "LibraryBook" b ON b.id = h."bookId"
ORDER BY h."classNoClean", h."bookCode"
LIMIT 50;
```

## Sharing DB Data With Teammates

The local DB data is stored in a Docker PostgreSQL volume, not in the Dockerfile.
It survives PC reboot as long as the volume is not removed.

Avoid:

```powershell
docker compose down -v
docker system prune --volumes
docker volume rm ...
```

Create a DB dump:

```powershell
docker exec shelfalign-postgres pg_dump -U shelfalign -d shelfalign -Fc -f /tmp/shelfalign.dump
docker cp shelfalign-postgres:/tmp/shelfalign.dump C:\dev\comp_lib\shelfalign.dump
```

Restore on a teammate machine:

```powershell
docker cp C:\dev\comp_lib\shelfalign.dump shelfalign-postgres:/tmp/shelfalign.dump
docker exec shelfalign-postgres pg_restore -U shelfalign -d shelfalign --clean --if-exists /tmp/shelfalign.dump
```

For quick spreadsheet inspection, export CSVs under `exports/`, but do not commit generated exports.
