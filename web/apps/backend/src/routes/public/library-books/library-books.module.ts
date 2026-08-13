import { Module } from "@nestjs/common";

import { AdminLibraryBooksService } from "@/routes/admin/library-books/library-books.service";

import { PublicLibraryBooksController } from "./library-books.controller";

@Module({
  controllers: [PublicLibraryBooksController],
  providers: [AdminLibraryBooksService],
})
export class PublicLibraryBooksModule {}
