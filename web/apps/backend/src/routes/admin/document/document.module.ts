import { Module } from "@nestjs/common";

import { AdminDocumentController } from "./document.controller";
import { AdminDocumentService } from "./document.service";

@Module({
  controllers: [AdminDocumentController],
  providers: [AdminDocumentService],
})
export class AdminDocumentModule {}
