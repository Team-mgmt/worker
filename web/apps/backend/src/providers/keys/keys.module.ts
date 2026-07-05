import { Module } from "@nestjs/common";

import { KeyService } from "./keys.service";

@Module({
  providers: [KeyService],
  exports: [KeyService],
})
export class KeyModule {}
