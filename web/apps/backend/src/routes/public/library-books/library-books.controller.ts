import { BadRequestException, Controller, Get, Query } from "@nestjs/common";

import { AdminLibraryBooksService } from "@/routes/admin/library-books/library-books.service";

const SUPPORTED_LIBRARY_CODES = new Set(["111058", "111189"]);

@Controller("/public/library-books")
export class PublicLibraryBooksController {
  constructor(private readonly libraryBooks: AdminLibraryBooksService) {}

  @Get()
  async search(
    @Query("libraryCode") libraryCode?: string,
    @Query("query") queryValue?: string,
  ) {
    const query = queryValue?.trim() ?? "";
    if (!libraryCode || !SUPPORTED_LIBRARY_CODES.has(libraryCode)) {
      throw new BadRequestException("지원하지 않는 도서관 코드입니다.");
    }
    if (query.length < 2) {
      throw new BadRequestException("검색어를 두 글자 이상 입력하세요.");
    }

    const { holdings } = await this.libraryBooks.list({
      libraryCode,
      query,
      page: 1,
      pageSize: 10,
    });
    return {
      result: true,
      data: holdings.map((holding) => ({
        id: holding.id,
        libraryCode: holding.libraryCode,
        callNumber: holding.callNumber,
        shelfLocName: holding.shelfLocName,
        book: holding.book
          ? {
              id: holding.book.id,
              isbn13: holding.book.isbn13,
              bookname: holding.book.bookname,
              authors: holding.book.authors,
              bookImageUrl: holding.book.bookImageUrl,
            }
          : null,
      })),
    };
  }
}
