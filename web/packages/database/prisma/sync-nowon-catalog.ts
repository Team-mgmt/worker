import { randomUUID } from "node:crypto";

import { PrismaPg } from "@prisma/adapter-pg";
import { Pool } from "pg";

import { PrismaClient } from "../src/generated/prisma/client.js";

const DATA4LIBRARY_ITEM_SEARCH_URL = "http://data4library.kr/api/itemSrch";
const NOWON_JUNGANG_LIBRARY_CODE = "111058";
const NOWON_JUNGANG_LIBRARY_NAME = "노원중앙도서관";
const DEFAULT_SHELF_LOC_CONTAINS = "종합자료실";
const MAX_FETCH_ATTEMPTS = 3;
const FETCH_RETRY_DELAY_MS = 3000;

type Data4LibraryCallNumber = {
  book_code?: string;
  shelf_loc_code?: string;
  shelf_loc_name?: string;
  separate_shelf_code?: string;
  separate_shelf_name?: string;
  copy_code?: string;
};

type Data4LibraryItem = {
  isbn13?: string;
  bookname?: string;
  authors?: string;
  publisher?: string;
  publication_year?: string;
  bookImageURL?: string;
  class_no?: string;
  book_code?: string;
  shelf_loc_code?: string;
  shelf_loc_name?: string;
  separate_shelf_code?: string;
  separate_shelf_name?: string;
  copy_code?: string;
  reg_date?: string;
  callNumbers?: Array<{ callNumber?: Data4LibraryCallNumber }>;
};

type Args = {
  authKey: string;
  libCode: string;
  libraryName: string;
  libraryAddress: string | null;
  kdc: string | null;
  shelfLocContains: string | null;
  classNoMin: number | null;
  classNoMax: number | null;
  pageSize: number;
  startPage: number;
  maxPages: number | null;
};

function getArgValue(name: string): string | undefined {
  const prefix = `--${name}=`;
  const found = process.argv.find((arg) => arg.startsWith(prefix));
  if (found) {
    return found.slice(prefix.length);
  }

  const index = process.argv.indexOf(`--${name}`);
  if (index >= 0) {
    return process.argv[index + 1];
  }

  return undefined;
}

function parseArgs(): Args {
  const authKey = getArgValue("auth-key") ?? process.env.JUNGBO_NARU_API_KEY ?? process.env.DATA4LIBRARY_API_KEY;
  if (!authKey) {
    throw new Error("JUNGBO_NARU_API_KEY or DATA4LIBRARY_API_KEY is required.");
  }

  const shelfLocContains = getArgValue("shelf-loc-contains") ?? DEFAULT_SHELF_LOC_CONTAINS;
  const classNoMinRaw = getArgValue("class-no-min");
  const classNoMaxRaw = getArgValue("class-no-max");
  const maxPagesRaw = getArgValue("max-pages");

  const libCode = getArgValue("lib-code") ?? NOWON_JUNGANG_LIBRARY_CODE;
  const knownLibraryNames: Record<string, string> = {
    [NOWON_JUNGANG_LIBRARY_CODE]: NOWON_JUNGANG_LIBRARY_NAME,
    "111189": "도봉아이나라도서관",
  };

  return {
    authKey,
    libCode,
    libraryName: getArgValue("library-name") ?? knownLibraryNames[libCode] ?? libCode,
    libraryAddress: getArgValue("library-address") ?? null,
    kdc: getArgValue("kdc") ?? null,
    shelfLocContains: shelfLocContains === "" ? null : shelfLocContains,
    classNoMin: classNoMinRaw ? Number(classNoMinRaw) : null,
    classNoMax: classNoMaxRaw ? Number(classNoMaxRaw) : null,
    pageSize: Number(getArgValue("page-size") ?? 100),
    startPage: Number(getArgValue("start-page") ?? 1),
    maxPages: maxPagesRaw ? Number(maxPagesRaw) : null,
  };
}

function normalizeText(value: string | null | undefined): string {
  return (value ?? "").normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
}

function normalizeKdc(value: string | null | undefined): string {
  return (value ?? "").normalize("NFKC").trim();
}

function parseClassNoNum(classNo: string | null | undefined): string | null {
  const normalized = normalizeKdc(classNo).replace(",", ".");
  const match = normalized.match(/\d+(?:\.\d+)?/);
  return match ? match[0] : null;
}

function isInClassNoRange(classNo: string | null | undefined, min: number | null, max: number | null): boolean {
  if (min === null && max === null) {
    return true;
  }

  const parsed = parseClassNoNum(classNo);
  if (!parsed) {
    return false;
  }

  const classNoNum = Number(parsed);
  if (Number.isNaN(classNoNum)) {
    return false;
  }

  return (min === null || classNoNum >= min) && (max === null || classNoNum < max);
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }

  const normalized = value.replaceAll(".", "-").replaceAll("/", "-");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function buildCallNumber(classNo: string, bookCode: string): string {
  return [classNo, bookCode].filter(Boolean).join(" ");
}

function getCallNumbers(item: Data4LibraryItem): Data4LibraryCallNumber[] {
  const callNumbers = item.callNumbers?.map((wrapper) => wrapper.callNumber).filter((callNumber): callNumber is Data4LibraryCallNumber => Boolean(callNumber));
  if (callNumbers?.length) {
    return callNumbers;
  }

  return [
    {
      book_code: item.book_code,
      shelf_loc_code: item.shelf_loc_code,
      shelf_loc_name: item.shelf_loc_name,
      separate_shelf_code: item.separate_shelf_code,
      separate_shelf_name: item.separate_shelf_name,
      copy_code: item.copy_code,
    },
  ];
}

function filterCallNumbers(item: Data4LibraryItem, shelfLocContains: string | null): Data4LibraryCallNumber[] {
  const callNumbers = getCallNumbers(item);
  if (!shelfLocContains) {
    return callNumbers;
  }

  return callNumbers.filter((callNumber) => callNumber.shelf_loc_name?.includes(shelfLocContains));
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchItems(args: Args, pageNo: number): Promise<Data4LibraryItem[]> {
  const url = new URL(DATA4LIBRARY_ITEM_SEARCH_URL);
  url.searchParams.set("authKey", args.authKey);
  url.searchParams.set("libCode", args.libCode);
  url.searchParams.set("type", "ALL");
  if (args.kdc) {
    url.searchParams.set("kdc", args.kdc);
  }
  url.searchParams.set("pageNo", String(pageNo));
  url.searchParams.set("pageSize", String(args.pageSize));
  url.searchParams.set("format", "json");

  for (let attempt = 1; attempt <= MAX_FETCH_ATTEMPTS; attempt += 1) {
    const response = await fetch(url);
    if (response.ok) {
      const data = await response.json();
      const apiResponse = data?.response;
      if (apiResponse?.errCode) {
        throw new Error(`Data4Library error: ${apiResponse.errCode} ${apiResponse.error ?? ""}`.trim());
      }

      const docs = apiResponse?.docs;
      if (!Array.isArray(docs)) {
        return [];
      }

      return docs.map((entry) => entry.doc).filter(Boolean);
    }

    if (attempt === MAX_FETCH_ATTEMPTS) {
      throw new Error(`Data4Library request failed: ${response.status} ${response.statusText}`);
    }

    console.warn(`Data4Library page ${pageNo} failed: ${response.status} ${response.statusText}. retry=${attempt}`);
    await sleep(FETCH_RETRY_DELAY_MS * attempt);
  }

  return [];
}

async function upsertBook(prisma: PrismaClient, item: Data4LibraryItem) {
  const isbn13 = item.isbn13?.trim() || null;
  const data = {
    bookname: item.bookname ?? "",
    normalizedBookname: normalizeText(item.bookname),
    authors: item.authors ?? null,
    normalizedAuthors: normalizeText(item.authors),
    publisher: item.publisher ?? null,
    publicationYear: item.publication_year ?? null,
    bookImageUrl: item.bookImageURL ?? null,
  };

  if (isbn13) {
    return prisma.libraryBook.upsert({
      where: { isbn13 },
      create: {
        id: randomUUID(),
        isbn13,
        ...data,
      },
      update: data,
    });
  }

  return prisma.libraryBook.create({
    data: {
      id: randomUUID(),
      isbn13: null,
      ...data,
    },
  });
}

async function upsertHolding(
  prisma: PrismaClient,
  libraryId: string,
  libCode: string,
  item: Data4LibraryItem,
  bookId: string,
  callNumber: Data4LibraryCallNumber,
) {
  const classNo = item.class_no ?? "";
  const classNoClean = normalizeKdc(classNo);
  const bookCode = callNumber.book_code ?? item.book_code ?? "";
  const fullCallNumber = buildCallNumber(classNoClean, bookCode);
  const shelfLocName = callNumber.shelf_loc_name ?? item.shelf_loc_name ?? null;
  const copyCode = callNumber.copy_code ?? item.copy_code ?? null;

  const existing = await prisma.libraryHolding.findFirst({
    where: {
      libraryCode: libCode,
      bookId,
      callNumber: fullCallNumber,
      shelfLocName,
      copyCode,
    },
  });

  const data = {
    bookId,
    libraryId,
    libraryCode: libCode,
    classNo: classNo || null,
    classNoClean: classNoClean || null,
    classNoNum: parseClassNoNum(classNo),
    bookCode: bookCode || null,
    callNumber: fullCallNumber || null,
    normalizedCallNumber: normalizeText(fullCallNumber),
    shelfLocCode: callNumber.shelf_loc_code ?? item.shelf_loc_code ?? null,
    shelfLocName,
    separateShelfCode: callNumber.separate_shelf_code ?? item.separate_shelf_code ?? null,
    separateShelfName: callNumber.separate_shelf_name ?? item.separate_shelf_name ?? null,
    copyCode,
    regDate: parseDate(item.reg_date),
    raw: item,
  };

  if (existing) {
    await prisma.libraryHolding.update({
      where: { id: existing.id },
      data,
    });
    return "updated";
  }

  await prisma.libraryHolding.create({
    data: {
      id: randomUUID(),
      ...data,
    },
  });
  return "created";
}

async function main() {
  const args = parseArgs();
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("DATABASE_URL is required.");
  }

  const pool = new Pool({ connectionString: databaseUrl });
  const prisma = new PrismaClient({ adapter: new PrismaPg(pool) });

  try {
    const library = await prisma.library.upsert({
      where: { code: args.libCode },
      create: {
        id: randomUUID(),
        code: args.libCode,
        name: args.libraryName,
        address: args.libraryAddress,
      },
      update: {
        name: args.libraryName,
        ...(args.libraryAddress ? { address: args.libraryAddress } : {}),
      },
    });

    let pageNo = args.startPage;
    let fetchedPages = 0;
    let scanned = 0;
    let loaded = 0;
    let created = 0;
    let updated = 0;

    while (args.maxPages === null || fetchedPages < args.maxPages) {
      const items = await fetchItems(args, pageNo);
      if (!items.length) {
        break;
      }

      for (const item of items) {
        scanned += 1;
        if (!isInClassNoRange(item.class_no, args.classNoMin, args.classNoMax)) {
          continue;
        }

        const callNumbers = filterCallNumbers(item, args.shelfLocContains);
        if (!callNumbers.length || !item.bookname) {
          continue;
        }

        const book = await upsertBook(prisma, item);
        for (const callNumber of callNumbers) {
          const result = await upsertHolding(prisma, library.id, args.libCode, item, book.id, callNumber);
          loaded += 1;
          if (result === "created") {
            created += 1;
          } else {
            updated += 1;
          }
        }
      }

      fetchedPages += 1;
      console.log(`Page ${pageNo} done. scanned=${scanned} loadedHoldings=${loaded} created=${created} updated=${updated}`);
      pageNo += 1;
    }

    const shelfFilterMessage = args.shelfLocContains ? ` shelf contains "${args.shelfLocContains}"` : " all shelves";
    const classNoFilterMessage =
      args.classNoMin === null && args.classNoMax === null ? "" : ` classNo=[${args.classNoMin ?? "-inf"}, ${args.classNoMax ?? "inf"})`;
    console.log(`Done.${shelfFilterMessage}${classNoFilterMessage}. scanned=${scanned} loadedHoldings=${loaded} created=${created} updated=${updated}`);
  } finally {
    await prisma.$disconnect();
    await pool.end();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
