import { Injectable } from "@nestjs/common";

import { Prisma } from "@shelfalign/database/client";

import { PrismaService } from "@/providers/database/prisma.service";

@Injectable()
export class AdminLibraryBooksService {
  constructor(private readonly prisma: PrismaService) {}

  async list(options: {
    libraryCode?: string;
    query?: string;
    page: number;
    pageSize: number;
  }) {
    const query = options.query?.trim();
    const where: Prisma.LibraryHoldingWhereInput = {
      ...(options.libraryCode
        ? { libraryCode: options.libraryCode }
        : undefined),
      ...(query
        ? {
            OR: [
              { callNumber: { contains: query, mode: "insensitive" } },
              { bookCode: { contains: query, mode: "insensitive" } },
              { book: { isbn13: { contains: query, mode: "insensitive" } } },
              {
                book: { bookname: { contains: query, mode: "insensitive" } },
              },
              { book: { authors: { contains: query, mode: "insensitive" } } },
            ],
          }
        : undefined),
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
