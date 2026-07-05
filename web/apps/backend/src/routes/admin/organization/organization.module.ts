import { Module } from "@nestjs/common";

import { AdminOrganizationController } from "./organization.controller";
import { AdminOrganizationService } from "./organization.service";

@Module({
  controllers: [AdminOrganizationController],
  providers: [AdminOrganizationService],
})
export class AdminOrganizationModule {}
