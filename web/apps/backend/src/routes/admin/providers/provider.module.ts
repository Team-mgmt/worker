import { Module } from "@nestjs/common";

import { AdminProviderController } from "./provider.controller";
import { AdminProviderService } from "./provider.service";

@Module({
  controllers: [AdminProviderController],
  providers: [AdminProviderService],
})
export class AdminProviderModule {}
