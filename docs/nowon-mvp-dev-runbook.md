# 노원중앙도서관 MVP 개발 가이드

이 문서는 ShelfAlign MVP를 로컬에서 실행하고, 팀원이 같은 환경을 맞추기 위한 기준 문서입니다.

## 대상 범위

- 대상 도서관: 노원중앙도서관
- 정보나루 `libCode`: `111058`
- MVP 대상 공간: `종합자료실`
- 우선 적재/검수 범위: 한국문학 KDC `810-819`

현재 MVP는 “서가 사진 업로드 -> VLM 책등 인식 -> 청구기호/제목/저자 추출 -> PostgreSQL 장서 DB 매칭 -> 백오피스 검수” 흐름을 기준으로 합니다.

## 로컬 서비스

PostgreSQL은 `web` 레포의 Docker Compose로 실행합니다.

```text
Host: localhost
Port: 5432
Database: shelfalign
User: shelfalign
Password: shelfalign
```

Worker API는 기존 `8000` 포트 프로세스와 충돌하지 않도록 `8001` 포트를 사용합니다.

```powershell
scripts\run_worker_8001.cmd
```

Backoffice는 worker 주소를 아래 값으로 바라보면 됩니다.

```env
VITE_WORKER_BASE_URL=http://localhost:8001
```

## 환경 변수

`worker/.env.example`을 복사해서 `worker/.env`를 만들고, 개인별 키를 로컬에만 넣습니다.

정보나루 API 동기화에 필요합니다.

```env
JUNGBO_NARU_API_KEY=...
```

VLM 이미지 분석에 필요합니다.

```env
OPENAI_API_KEY=...
```

주의: `.env`는 절대 커밋하지 않습니다. GitHub에는 `.env.example`만 올립니다.

## VLM 서가 분석 흐름

백오피스에서 서가 이미지를 업로드하면 worker의 아래 API로 요청합니다.

```text
POST /inference/analyze_vlm
```

처리 순서는 다음과 같습니다.

1. 업로드 이미지를 `outputs/uploads/` 아래에 저장합니다.
2. 설정된 VLM 모델에 이미지를 전달합니다.
3. 책등별 bbox, OCR 원문, 청구기호, 제목, 저자, 신뢰도 값을 JSON으로 파싱합니다.
4. VLM이 반환한 정규화 bbox를 실제 이미지 픽셀 좌표로 변환합니다.
5. OCR/VLM 텍스트를 Prisma 기반 장서 테이블과 매칭합니다.
   - `LibraryBook`
   - `LibraryHolding`
6. 백오피스로 검출 목록과 후보 목록을 반환합니다.

현재 MVP에서는 VLM 분석 결과를 화면 응답으로 반환합니다. 운영 저장은 Prisma의 `ShelfScanSession`/`ShelfDetection` 모델 기준으로 연결합니다.

## 매칭 판정 기준

낮은 점수의 DB 후보를 확정 도서처럼 보여주면 안 됩니다.

현재 기준은 다음과 같습니다.

```text
score >= 75.0 -> 확정 매칭 후보
score < 75.0 -> 검수 필요 또는 매칭 실패
```

상태 구분은 다음 기준으로 봅니다.

- `normal`: 매칭 점수가 충분하고 주변 KDC 맥락에도 어긋나지 않음
- `suspected_misplacement`: 매칭은 됐지만 주변 서가의 KDC 범위와 어긋남
- `needs_review`: OCR/청구기호/제목은 인식됐지만 점수가 낮거나 DB 후보가 불확실함
- `unmatched`: OCR 증거와 DB 후보가 모두 부족해 매칭 자체가 어려움

예를 들어 `740 황19ㅇ`처럼 청구기호가 읽혔지만 현재 MVP 후보 범위가 한국문학 `810-819`라서 DB 후보가 없으면, 단순 `매칭 실패`보다 `검수 필요`로 보는 것이 맞습니다.

## DataGrip 접속

DataGrip에서 아래 정보로 연결합니다.

```text
Host: localhost
Port: 5432
Database: shelfalign
Username: shelfalign
Password: shelfalign
```

전체 테이블 확인:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

도서/소장 데이터 개수:

```sql
SELECT COUNT(*) FROM "LibraryBook";
SELECT COUNT(*) FROM "LibraryHolding";
```

장서 샘플 조회:

```sql
SELECT
  b.bookname,
  b.authors,
  h."callNumber",
  h."classNo",
  h."bookCode",
  h."shelfLocName"
FROM "LibraryHolding" h
JOIN "LibraryBook" b ON b.id = h."bookId"
ORDER BY h."classNoClean", h."bookCode"
LIMIT 50;
```

한국문학 KDC `810-819` 조회:

```sql
SELECT
  h."callNumber",
  h."classNo",
  h."bookCode",
  h."shelfLocName",
  b.bookname,
  b.authors,
  b.publisher,
  b."publicationYear"
FROM "LibraryHolding" h
JOIN "LibraryBook" b ON b.id = h."bookId"
WHERE h."classNoNum" >= 810
  AND h."classNoNum" < 820
ORDER BY h."classNoNum", h."bookCode"
LIMIT 300;
```

특정 책/저자/청구기호 확인:

```sql
SELECT
  b.bookname,
  b.authors,
  h."callNumber",
  h."classNo",
  h."bookCode",
  h."shelfLocName",
  b.publisher,
  b."publicationYear",
  b.isbn13
FROM "LibraryBook" b
JOIN "LibraryHolding" h ON h."bookId" = b.id
WHERE b.bookname ILIKE '%조귀인%'
   OR b.authors ILIKE '%박영주%'
   OR h."callNumber" ILIKE '%813.6 박64ㅈ%'
ORDER BY h."callNumber", b.bookname;
```

## 팀원에게 DB 데이터 공유하기

현재 로컬 DB 데이터는 Dockerfile 안에 들어있는 것이 아니라, 내 PC의 Docker PostgreSQL volume에 저장됩니다. PC를 껐다 켜도 volume을 지우지 않으면 유지됩니다.

아래 명령은 데이터를 지울 수 있으니 주의합니다.

```powershell
docker compose down -v
docker system prune --volumes
docker volume rm ...
```

팀원에게 같은 DB 데이터를 전달하려면 dump 파일을 만드는 방식이 가장 안전합니다.

DB dump 생성:

```powershell
docker exec shelfalign-postgres pg_dump -U shelfalign -d shelfalign -Fc -f /tmp/shelfalign.dump
docker cp shelfalign-postgres:/tmp/shelfalign.dump C:\dev\comp_lib\shelfalign.dump
```

팀원 PC에서 복원:

```powershell
docker cp C:\dev\comp_lib\shelfalign.dump shelfalign-postgres:/tmp/shelfalign.dump
docker exec shelfalign-postgres pg_restore -U shelfalign -d shelfalign --clean --if-exists /tmp/shelfalign.dump
```

복원 확인:

```powershell
docker exec shelfalign-postgres psql -U shelfalign -d shelfalign -c "SELECT COUNT(*) FROM \"LibraryBook\";"
docker exec shelfalign-postgres psql -U shelfalign -d shelfalign -c "SELECT COUNT(*) FROM \"LibraryHolding\";"
```

## dump가 없을 때 CSV로 데이터 확인/적재하기

DB dump가 가장 안전한 공유 방식입니다. 다만 dump 파일이 없고, 엑셀처럼 확인 가능한 파일만 있는 경우에는 `exports/` 아래 CSV를 별도로 팀원에게 전달할 수 있습니다.

현재 로컬에 생성된 CSV 예시는 다음과 같습니다.

```text
exports/노원중앙도서관_API추출 3천건정도.csv
```

주의: `exports/`는 생성 산출물이므로 GitHub에 커밋하지 않습니다. 필요한 경우 파일만 따로 전달합니다.

CSV는 두 가지 용도로 사용할 수 있습니다.

1. DataGrip에서 데이터 확인용으로 열기
2. 임시 테이블에 import한 뒤 `LibraryBook`, `LibraryHolding`으로 적재하기

DataGrip에서 확인만 할 때는 CSV 파일을 DataGrip으로 열거나, PostgreSQL에 임시 테이블을 만들고 Import Data from File을 사용합니다.

예시 임시 테이블:

```sql
CREATE TABLE IF NOT EXISTS "NowonCatalogImport" (
  isbn13 TEXT,
  bookname TEXT,
  authors TEXT,
  publisher TEXT,
  publication_year TEXT,
  library_code TEXT,
  shelf_loc_code TEXT,
  shelf_loc_name TEXT,
  call_number TEXT,
  class_no TEXT,
  book_code TEXT
);
```

DataGrip에서 `"NowonCatalogImport"` 테이블을 우클릭한 뒤 `Import Data from File`로 CSV를 넣습니다. CSV 컬럼명이 다르면 DataGrip의 column mapping 화면에서 맞춰줍니다.

그 다음 실제 Prisma 테이블로 옮기는 방식은 CSV 컬럼명과 현재 schema에 맞춰 별도 insert 쿼리를 작성해야 합니다. 이 단계는 실수하면 중복 데이터가 생기기 쉬워서, 팀원 환경 세팅 목적이라면 CSV import보다 dump 복원을 우선 사용합니다.
