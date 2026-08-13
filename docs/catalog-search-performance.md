# 도서 데이터셋 검색 성능 개선 및 운영 가이드

## 배경

노원중앙도서관(`libraryCode=111058`)의 소장 데이터를 기존 50,698건에서
121,831건으로 교체한 뒤 백오피스의 도서 데이터셋 검색에서 요청 시간 초과가
발생했다.

문제가 발생한 API는 다음과 같다.

```text
GET /api/admin/library-books
```

예시 요청:

```text
/api/admin/library-books?libraryCode=111058&query=어리석은&page=1&pageSize=25
```

## 원인

기존 검색은 검색어 하나를 다음 다섯 필드에 동시에 부분 일치 검색했다.

- `LibraryHolding.callNumber`
- `LibraryHolding.bookCode`
- `LibraryBook.isbn13`
- `LibraryBook.bookname`
- `LibraryBook.authors`

Prisma의 `contains`와 case-insensitive 검색은 PostgreSQL에서 대체로 다음 형태가
된다.

```sql
ILIKE '%검색어%'
```

문자열 앞에 `%`가 있는 검색은 일반 B-tree 인덱스를 효율적으로 사용할 수 없다.
여기에 `LibraryHolding`과 `LibraryBook`을 넘나드는 여러 `OR` 조건, 목록 조회와
전체 결과 수 계산이 함께 실행되면서 대량 장서에서 full scan과 비싼 join이
발생했다.

백오피스에 `1 / 4874 페이지`가 남아 있던 것은 검색 결과가 아니라 직전에 성공한
전체 목록 응답이었다. `121831 / 25`를 올림하면 4,874페이지다.

## 적용한 개선

관련 커밋:

```text
39e6872 perf(database): optimize catalog search
6b57939 fix(database): make search indexes idempotent
```

### 1. 검색어 유형별 쿼리 분리

수정 파일:

```text
web/apps/backend/src/routes/admin/library-books/library-books.service.ts
```

이전처럼 모든 검색어를 다섯 필드에 동시에 적용하지 않고 다음처럼 분기한다.

| 검색어 유형 | 검색 필드 | 예시 |
|---|---|---|
| 일반 문자 | `normalizedBookname`, `normalizedAuthors` | `어리석은`, `김영하` |
| 8~13자리 숫자 | `isbn13` prefix | `9791171831708` |
| 숫자와 문자가 섞인 값 | `normalizedCallNumber`, `bookCode` | `813.6 김12ㄱ` |

이 변경으로 일반 제목 검색에서 청구기호 테이블까지 포함한 광범위한 `OR`를
제거했다. API 응답 구조, 페이지 크기, 전체 결과 수와 페이지네이션 방식은
변경하지 않았다.

### 2. 애플리케이션과 동일한 정규화

검색어는 앞뒤 공백을 제거하고 소문자화하며, 정규화 필드 검색에는 Unicode
NFKC를 적용한다.

호환 자모는 NFKC 적용 시 조합용 자모로 변환될 수 있다. 따라서 청구기호 검색은
다음 두 값을 구분한다.

- `normalizedCallNumber`: NFKC 적용 검색어
- `bookCode`: 사용자가 입력한 원본 검색어

이 구분 없이 NFKC 결과를 원본 `bookCode`에 그대로 사용하면 `ㄱ` 같은 호환
자모가 포함된 도서기호를 놓칠 수 있다.

### 3. 부분검색용 trigram 인덱스

추가 migration:

```text
web/packages/database/prisma/migrations/
  20260813023000_add_library_search_trigram_indexes/migration.sql
```

생성하는 인덱스:

```text
LibraryBook_normalizedBookname_trgm_idx
LibraryBook_normalizedAuthors_trgm_idx
LibraryHolding_normalizedCallNumber_trgm_idx
LibraryHolding_bookCode_trgm_idx
```

PostgreSQL `pg_trgm` 확장과 GIN 인덱스를 사용한다. 모든 생성문에
`IF NOT EXISTS`가 있어 SQL을 먼저 수동 적용한 뒤 나중에 migration deploy가
실행되어도 동일 인덱스 때문에 실패하지 않는다.

## 배포 절차

### 1. 코드 갱신

```bash
cd /opt/shelfalign
git status --short
sudo git pull --ff-only origin main
git log -1 --oneline
```

작업 트리에 변경이 있으면 pull 전에 원인을 확인한다. 운영 파일을 임의로
되돌리지 않는다.

### 2. 검색 인덱스 적용

다음 작업은 DB schema를 변경하므로 운영자가 직접 실행한다.

```bash
psql -W \
  "host=<RDS_HOST> port=5432 dbname=<DB_NAME> user=<DB_USER> sslmode=require" \
  -f /opt/shelfalign/web/packages/database/prisma/migrations/20260813023000_add_library_search_trigram_indexes/migration.sql
```

비밀번호는 명령행이나 GitHub에 넣지 않고 `psql` 프롬프트에서 입력한다.

정상 출력은 extension 1개와 index 4개 생성이다. 이미 존재하는 항목은 notice와
함께 건너뛸 수 있다.

### 3. Backend만 재시작

```bash
sudo systemctl restart shelfalign-backend.service
sleep 5
sudo systemctl is-active shelfalign-backend.service
```

이번 변경은 Python worker에 영향을 주지 않으므로 worker 재시작은 필요하지 않다.

DB 연결 확인:

```bash
sudo journalctl -u shelfalign-backend.service \
  --since "2 minutes ago" \
  --no-pager | \
  grep -Ei 'connected to|authentication failed|connection error|error'
```

## 검증

### 자동 검증

로컬 또는 CI에서:

```bash
cd web
pnpm --filter @shelfalign/backend test --runTestsByPath \
  src/routes/admin/library-books/library-books.service.spec.ts \
  --runInBand
pnpm --filter @shelfalign/backend check-types
```

테스트 범위:

- 일반 한글 검색이 정규화 제목·저자로 분기되는지
- 긴 숫자가 ISBN prefix 검색으로 분기되는지
- 청구기호가 정규화 청구기호·도서기호로 분기되는지
- 빈 검색어가 검색 필터를 만들지 않는지

### 운영 DB 인덱스 확인

```sql
SELECT indexname
FROM pg_indexes
WHERE indexname LIKE '%trgm_idx'
ORDER BY indexname;
```

네 개의 검색 인덱스가 출력되어야 한다.

### 기능 검증

백오피스에서 최소 다음 검색을 확인한다.

- 제목: `어리석은`
- 저자: 실제 저자명
- ISBN: 13자리 ISBN
- 청구기호: `813.6 김12ㄱ` 형태

성공 기준:

- request timeout이 발생하지 않는다.
- 검색 결과 수에 맞는 페이지 수가 표시된다.
- 일반 검색이 반복 실행 시 안정적으로 응답한다.
- ISBN과 청구기호 검색 결과가 기존 API 형식으로 반환된다.

### 쿼리 계획 확인

성능 문제가 재발하면 운영 DB에서 실제 검색어로 다음을 실행한다.

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT b.id
FROM "LibraryBook" b
WHERE b."normalizedBookname" ILIKE '%어리석은%';
```

GIN trigram 인덱스가 사용되는지, 실제 실행 시간과 buffer read가 비정상적으로
증가하지 않는지 확인한다.

## 롤백

애플리케이션 문제가 있으면 이전 커밋으로 코드를 되돌리는 새 커밋을 만들고
backend를 재배포한다. 운영 서버에서 `git reset --hard`를 사용하지 않는다.

인덱스는 검색 결과 의미를 바꾸지 않으므로 일반적으로 유지해도 된다. 반드시
제거해야 할 때만 운영자가 다음을 실행한다.

```sql
DROP INDEX IF EXISTS "LibraryBook_normalizedBookname_trgm_idx";
DROP INDEX IF EXISTS "LibraryBook_normalizedAuthors_trgm_idx";
DROP INDEX IF EXISTS "LibraryHolding_normalizedCallNumber_trgm_idx";
DROP INDEX IF EXISTS "LibraryHolding_bookCode_trgm_idx";
```

`pg_trgm` 확장은 다른 기능에서도 사용할 수 있으므로 임의로 삭제하지 않는다.

## 관련 운영 주의사항

- 데이터 적재 건수와 검색 성능은 별도 지표다. 적재 성공만으로 검색 성능이
  보장되지 않는다.
- 장서 교체 후 `ANALYZE "LibraryBook";`와 `ANALYZE "LibraryHolding";`를 실행해
  query planner 통계를 갱신한다.
- 백오피스의 HTTP timeout을 무작정 늘리기 전에 SQL 실행 계획과 인덱스를 먼저
  확인한다.
- RDS 비밀번호, `.env`, AWS credential은 문서나 GitHub에 기록하지 않는다.
