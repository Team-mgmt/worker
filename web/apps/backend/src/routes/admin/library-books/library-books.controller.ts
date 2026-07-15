import { Controller, Get, Query, UseGuards } from "@nestjs/common";

import { AuthGuard } from "@/common/guards/auth.guard";

import { AdminLibraryBooksService } from "./library-books.service";

@UseGuards(AuthGuard({ roles: ["ADMIN"] }))
@Controller("/admin/library-books")
export class AdminLibraryBooksController {
  constructor(private readonly libraryBooks: AdminLibraryBooksService) {}

  @Get()
  async list(
    @Query("libraryCode") libraryCode?: string,
    @Query("query") query?: string,
    @Query("page") pageValue?: string,
    @Query("pageSize") pageSizeValue?: string,
  ) {
    const page = Math.max(1, Number.parseInt(pageValue ?? "1", 10) || 1);
    const pageSize = Math.min(
      100,
      Math.max(1, Number.parseInt(pageSizeValue ?? "25", 10) || 25),
    );
    const { holdings, count } = await this.libraryBooks.list({
      libraryCode: libraryCode || undefined,
      query: query || undefined,
      page,
      pageSize,
    });

    return { result: true, data: holdings, count, page, pageSize };
  }
}
