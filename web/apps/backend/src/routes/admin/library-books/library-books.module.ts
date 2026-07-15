import { Module } from "@nestjs/common";

import { AdminLibraryBooksController } from "./library-books.controller";
import { AdminLibraryBooksService } from "./library-books.service";

@Module({
  controllers: [AdminLibraryBooksController],
  providers: [AdminLibraryBooksService],
})
export class AdminLibraryBooksModule {}
