import { Injectable } from "@nestjs/common";

import { Prisma } from "@shelfalign/database/client";

import { PrismaService } from "@/providers/database/prisma.service";

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
  constructor(private readonly prisma: PrismaService) {}

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

    const [holdings, count] = await this.prisma.$transaction([
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
      this.prisma.libraryHolding.count({ where }),
    ]);

    return { holdings, count };
  }
}
