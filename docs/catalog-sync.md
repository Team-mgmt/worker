# Library catalog synchronization

The catalog schema is shared by every library:

- `Library`: one row per library code.
- `LibraryBook`: shared bibliographic records, deduplicated by ISBN-13.
- `LibraryHolding`: call number, shelf, copy, and library-specific ownership.

Creating a separate table per library is intentionally avoided. Matching queries
select holdings with `libraryCode`, so multiple libraries can share the same book
record without mixing their call numbers or shelf locations.

## Dobong Children's Library

Data4Library metadata:

- Library code: `111189`
- Name: `도봉아이나라도서관`
- Address: `서울특별시 도봉구 노해로69길 151`

Load the backend and API-key environment variables before running the command.
The `DATABASE_URL` must point to the production PostgreSQL database with SSL.

```bash
NODE_TLS_REJECT_UNAUTHORIZED=0 \
pnpm --filter @shelfalign/database sync:catalog -- \
  --auth-key="$DATA4LIBRARY_API_KEY_3" \
  --lib-code=111189 \
  --library-name="도봉아이나라도서관" \
  --library-address="서울특별시 도봉구 노해로69길 151" \
  --shelf-loc-contains="" \
  --page-size=200 \
  --start-page=1
```

No KDC range is supplied, so every catalog classification returned for the
library is stored. Re-running a completed page updates existing ISBN and holding
records. To resume, use the page after the last `Page N done` message with the
same arguments.

Verify the result:

```sql
SELECT
  l.code,
  l.name,
  COUNT(h.id) AS holdings,
  COUNT(DISTINCT h."bookId") AS books
FROM "Library" l
LEFT JOIN "LibraryHolding" h ON h."libraryId" = l.id
WHERE l.code = '111189'
GROUP BY l.code, l.name;
```
