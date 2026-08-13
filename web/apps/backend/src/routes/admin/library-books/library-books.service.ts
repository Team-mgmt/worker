import { Injectable } from "@nestjs/common";

import { Prisma } from "@shelfalign/database/client";

import { PrismaService } from "@/providers/database/prisma.service";

const COUNT_CACHE_TTL_MS = 60_000;
const MAX_COUNT_CACHE_ENTRIES = 256;

type CountCacheEntry = {
  value: number;
  expiresAt: number;
};

export function buildLibraryBookCountCacheKey(options: {
  libraryCode?: string;
  query?: string;
}) {
  return `${options.libraryCode ?? "*"}\u0000${options.query?.trim().normalize("NFKC").toLowerCase() ?? ""}`;
}

export function buildLibraryBookSearchWhere(
  queryValue: string | undefined,
): Prisma.LibraryHoldingWhereInput | undefined {
  const rawQuery = queryValue?.trim().toLowerCase();
  if (!rawQuery) return undefined;
  const normalizedQuery = rawQuery.normalize("NFKC");

  const hasDigit = /\d/.test(rawQuery);
  const hasLetter = /[a-zA-Z가-힣ㄱ-ㅎㅏ-ㅣ]/.test(rawQuery);

  if (!hasDigit && hasLetter) {
    return {
      book: {
        OR: [
          { normalizedBookname: { contains: normalizedQuery } },
          { normalizedAuthors: { contains: normalizedQuery } },
        ],
      },
    };
  }

  if (hasDigit && !hasLetter && /^\d{8,13}$/.test(rawQuery)) {
    return { book: { isbn13: { startsWith: rawQuery } } };
  }

  return {
    OR: [
      { normalizedCallNumber: { contains: normalizedQuery } },
      { bookCode: { contains: rawQuery, mode: "insensitive" } },
    ],
  };
}

@Injectable()
export class AdminLibraryBooksService {
  private readonly countCache = new Map<string, CountCacheEntry>();

  constructor(private readonly prisma: PrismaService) {}

  private getCachedCount(key: string) {
    const entry = this.countCache.get(key);
    if (!entry) return undefined;
    if (entry.expiresAt <= Date.now()) {
      this.countCache.delete(key);
      return undefined;
    }
    return entry.value;
  }

  private cacheCount(key: string, value: number) {
    if (this.countCache.size >= MAX_COUNT_CACHE_ENTRIES) {
      const oldestKey = this.countCache.keys().next().value as string | undefined;
      if (oldestKey) this.countCache.delete(oldestKey);
    }
    this.countCache.set(key, {
      value,
      expiresAt: Date.now() + COUNT_CACHE_TTL_MS,
    });
  }

  async list(options: {
    libraryCode?: string;
    query?: string;
    page: number;
    pageSize: number;
  }) {
    const searchWhere = buildLibraryBookSearchWhere(options.query);
    const where: Prisma.LibraryHoldingWhereInput = {
      ...(options.libraryCode
        ? { libraryCode: options.libraryCode }
        : undefined),
      ...searchWhere,
    };
    const skip = (options.page - 1) * options.pageSize;

    const countCacheKey = buildLibraryBookCountCacheKey(options);
    const cachedCount = this.getCachedCount(countCacheKey);
    const countPromise = cachedCount === undefined
      ? this.prisma.libraryHolding.count({ where })
      : Promise.resolve(cachedCount);

    // These are independent read queries. Running them concurrently avoids
    // making every page wait for the exact COUNT query first, while the short
    // cache prevents repeated counts during pagination.
    const [holdings, count] = await Promise.all([
      this.prisma.libraryHolding.findMany({
        where,
        skip,
        take: options.pageSize,
        orderBy: [{ libraryCode: "asc" }, { callNumber: "asc" }],
        include: {
          library: { select: { code: true, name: true } },
          book: {
            select: {
              id: true,
              isbn13: true,
              bookname: true,
              authors: true,
              publisher: true,
              publicationYear: true,
              bookImageUrl: true,
            },
          },
        },
      }),
      countPromise,
    ]);

    if (cachedCount === undefined) this.cacheCount(countCacheKey, count);

    return { holdings, count };
  }
}
