import { createReadStream } from "node:fs";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

import { Pool, type PoolClient } from "pg";

const LIBRARY_CODE = "111058";
const LIBRARY_NAME = "노원중앙도서관";
const BATCH_SIZE = 1_000;

type CsvRow = Record<string, string>;

type ImportRow = {
  id: string;
  ordinal: number;
  bookname: string;
  authors: string | null;
  publisher: string | null;
  publication_year: string | null;
  isbn13: string;
  normalized_bookname: string;
  normalized_authors: string;
  class_no: string | null;
  class_no_num: string | null;
  book_code: string | null;
  shelf_loc_code: string | null;
  shelf_loc_name: string | null;
  copy_code: string | null;
  reg_date: string | null;
  normalized_call_number: string;
  raw: CsvRow;
};

function arg(name: string): string | undefined {
  const exact = process.argv.indexOf(`--${name}`);
  if (exact >= 0) return process.argv[exact + 1];
  return process.argv.find((value) => value.startsWith(`--${name}=`))?.slice(name.length + 3);
}

function normalizeText(value: string | null | undefined): string {
  return (value ?? "").normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
}

function normalizeKdc(value: string | null | undefined): string {
  return (value ?? "").normalize("NFKC").trim();
}

function classNoNumber(value: string | null): string | null {
  const match = value?.replace(",", ".").match(/\d+(?:\.\d+)?/);
  return match?.[0] ?? null;
}

async function* parseCsv(path: string): AsyncGenerator<string[]> {
  const stream = createReadStream(path, { encoding: "utf8" });
  let row: string[] = [];
  let field = "";
  let quoted = false;
  let pendingQuote = false;

  for await (const chunk of stream) {
    for (const char of chunk) {
      if (pendingQuote) {
        if (char === '"') {
          field += '"';
          pendingQuote = false;
          continue;
        }
        quoted = false;
        pendingQuote = false;
      }
      if (quoted) {
        if (char === '"') pendingQuote = true;
        else field += char;
        continue;
      }
      if (char === '"' && field.length === 0) quoted = true;
      else if (char === ",") {
        row.push(field);
        field = "";
      } else if (char === "\n") {
        row.push(field.endsWith("\r") ? field.slice(0, -1) : field);
        yield row;
        row = [];
        field = "";
      } else {
        field += char;
      }
    }
  }
  if (pendingQuote) quoted = false;
  if (quoted) throw new Error("CSV ended inside a quoted field.");
  if (field || row.length) {
    row.push(field.endsWith("\r") ? field.slice(0, -1) : field);
    yield row;
  }
}

function requireHeaders(headers: string[]): void {
  const required = ["bookname", "authors", "publisher", "publication_year", "isbn13", "class_no", "reg_date", "book_code", "shelf_loc_code", "shelf_loc_name", "copy_code"];
  const missing = required.filter((header) => !headers.includes(header));
  if (missing.length) throw new Error(`Missing CSV columns: ${missing.join(", ")}`);
}

async function insertBatch(client: PoolClient, rows: ImportRow[]): Promise<void> {
  await client.query(
    `INSERT INTO nowon_catalog_stage
      (id, ordinal, bookname, authors, publisher, publication_year, isbn13,
       normalized_bookname, normalized_authors, class_no, class_no_num,
       book_code, shelf_loc_code, shelf_loc_name, copy_code, reg_date,
       normalized_call_number, raw)
     SELECT x.id::uuid, x.ordinal, x.bookname, x.authors, x.publisher,
            x.publication_year, x.isbn13, x.normalized_bookname, x.normalized_authors,
            x.class_no, x.class_no_num::numeric, x.book_code,
            x.shelf_loc_code, x.shelf_loc_name, x.copy_code,
            CASE WHEN x.reg_date = '' THEN NULL ELSE x.reg_date::date END,
            x.normalized_call_number, x.raw
     FROM jsonb_to_recordset($1::jsonb) AS x(
       id text, ordinal integer, bookname text, authors text, publisher text,
       publication_year text, isbn13 text, normalized_bookname text, normalized_authors text,
       class_no text, class_no_num text, book_code text,
       shelf_loc_code text, shelf_loc_name text, copy_code text, reg_date text, raw jsonb
       , normalized_call_number text
     )`,
    [JSON.stringify(rows)],
  );
}

async function loadStage(client: PoolClient, csvPath: string): Promise<number> {
  await client.query(`CREATE TEMP TABLE nowon_catalog_stage (
    id uuid PRIMARY KEY, ordinal integer NOT NULL, bookname text NOT NULL,
    authors text, publisher text, publication_year text, isbn13 text NOT NULL,
    normalized_bookname text NOT NULL, normalized_authors text NOT NULL,
    class_no text, class_no_num numeric(10,3), book_code text,
    shelf_loc_code text, shelf_loc_name text, copy_code text, reg_date date,
    normalized_call_number text NOT NULL, raw jsonb NOT NULL
  ) ON COMMIT PRESERVE ROWS`);

  let headers: string[] | null = null;
  let batch: ImportRow[] = [];
  let ordinal = 0;
  for await (const values of parseCsv(csvPath)) {
    if (!headers) {
      headers = values.map((value, index) => index === 0 ? value.replace(/^\uFEFF/, "") : value);
      requireHeaders(headers);
      continue;
    }
    if (values.length !== headers.length) throw new Error(`CSV row ${ordinal + 2} has ${values.length} fields; expected ${headers.length}.`);
    const raw = Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
    ordinal += 1;
    if (!raw.bookname.trim()) throw new Error(`CSV row ${ordinal + 1} has no bookname.`);
    if (!raw.isbn13.trim()) throw new Error(`CSV row ${ordinal + 1} has no isbn13.`);
    const classNo = normalizeKdc(raw.class_no) || null;
    const bookCode = raw.book_code.trim() || null;
    batch.push({
      id: randomUUID(), ordinal, bookname: raw.bookname.trim(),
      authors: raw.authors.trim() || null, publisher: raw.publisher.trim() || null,
      publication_year: raw.publication_year.trim() || null, isbn13: raw.isbn13.trim(),
      normalized_bookname: normalizeText(raw.bookname), normalized_authors: normalizeText(raw.authors),
      class_no: classNo, class_no_num: classNoNumber(classNo), book_code: bookCode,
      shelf_loc_code: raw.shelf_loc_code.trim() || null, shelf_loc_name: raw.shelf_loc_name.trim() || null,
      copy_code: raw.copy_code.trim() || null, reg_date: raw.reg_date.trim() || null,
      normalized_call_number: normalizeText([classNo, bookCode].filter(Boolean).join(" ")), raw,
    });
    if (batch.length === BATCH_SIZE) {
      await insertBatch(client, batch);
      batch = [];
    }
  }
  if (batch.length) await insertBatch(client, batch);
  return ordinal;
}

async function main(): Promise<void> {
  const csvPath = resolve(arg("file") ?? "../노원중앙도서관_전체 데이터셋(12만건).csv");
  const apply = process.argv.includes("--apply");
  if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is required.");
  const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 1 });
  const client = await pool.connect();
  try {
    const loaded = await loadStage(client, csvPath);
    const validation = await client.query(`SELECT
      count(*)::int rows,
      count(DISTINCT isbn13)::int distinct_isbn,
      count(*) FILTER (WHERE class_no IS NULL)::int missing_class_no,
      count(*) FILTER (WHERE book_code IS NULL)::int missing_book_code,
      count(*) FILTER (WHERE shelf_loc_name IS NULL)::int missing_shelf
      FROM nowon_catalog_stage`);
    const current = await client.query(`SELECT
      (SELECT count(*)::int FROM "LibraryHolding" WHERE "libraryCode" = $1) AS holdings,
      (SELECT count(*)::int FROM "ShelfDetection" d JOIN "LibraryHolding" h ON h.id = d."matchedHoldingId" WHERE h."libraryCode" = $1) AS referenced_detections,
      (SELECT count(*)::int FROM "LibraryHolding" WHERE "libraryCode" <> $1) AS other_library_holdings`, [LIBRARY_CODE]);
    console.log({ csvPath, loaded, validation: validation.rows[0], current: current.rows[0], mode: apply ? "apply" : "dry-run" });
    if (!apply) return;
    if (loaded < 100_000) throw new Error(`Refusing replacement: expected at least 100000 rows, got ${loaded}.`);

    await client.query("BEGIN");
    try {
      const library = await client.query(`INSERT INTO "Library" (id, code, name, "createdAt", "updatedAt")
        VALUES ($1, $2, $3, now(), now())
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, "updatedAt" = now()
        RETURNING id`, [randomUUID(), LIBRARY_CODE, LIBRARY_NAME]);
      const libraryId = library.rows[0].id as string;

      await client.query(`UPDATE "ShelfDetection" d SET "matchedHoldingId" = NULL, "updatedAt" = now()
        FROM "LibraryHolding" h WHERE d."matchedHoldingId" = h.id AND h."libraryCode" = $1`, [LIBRARY_CODE]);
      await client.query(`DELETE FROM "LibraryHolding" WHERE "libraryCode" = $1`, [LIBRARY_CODE]);

      await client.query(`INSERT INTO "LibraryBook"
        (id, isbn13, bookname, "normalizedBookname", authors, "normalizedAuthors", publisher, "publicationYear", "createdAt", "updatedAt")
        SELECT DISTINCT ON (isbn13) id, isbn13, bookname, normalized_bookname, authors,
          normalized_authors, publisher, publication_year, now(), now()
        FROM nowon_catalog_stage ORDER BY isbn13, ordinal DESC
        ON CONFLICT (isbn13) DO UPDATE SET
          bookname = EXCLUDED.bookname, "normalizedBookname" = EXCLUDED."normalizedBookname",
          authors = EXCLUDED.authors, "normalizedAuthors" = EXCLUDED."normalizedAuthors",
          publisher = EXCLUDED.publisher, "publicationYear" = EXCLUDED."publicationYear", "updatedAt" = now()`);

      const inserted = await client.query(`WITH inserted AS (INSERT INTO "LibraryHolding"
        (id, "bookId", "libraryId", "libraryCode", "classNo", "classNoClean", "classNoNum",
         "bookCode", "callNumber", "normalizedCallNumber", "shelfLocCode", "shelfLocName",
         "copyCode", "regDate", raw, "createdAt", "updatedAt")
        SELECT s.id, b.id, $1, $2, s.class_no, s.class_no,
          s.class_no_num,
          s.book_code, concat_ws(' ', s.class_no, s.book_code),
          s.normalized_call_number,
          s.shelf_loc_code, s.shelf_loc_name, s.copy_code, s.reg_date, s.raw, now(), now()
        FROM nowon_catalog_stage s JOIN "LibraryBook" b ON b.isbn13 = s.isbn13
        RETURNING id) SELECT count(*)::int AS count FROM inserted`, [libraryId, LIBRARY_CODE]);
      const insertedCount = inserted.rows[0].count as number;
      if (insertedCount !== loaded) throw new Error(`Inserted ${insertedCount} holdings, expected ${loaded}.`);
      await client.query("COMMIT");
      console.log({ replaced: true, insertedHoldings: insertedCount });
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    }
  } finally {
    client.release();
    await pool.end();
  }
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
