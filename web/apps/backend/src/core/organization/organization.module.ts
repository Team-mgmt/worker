import { Module } from "@nestjs/common";

import { OrganizationOwnershipService } from "./organization-ownership.service";

@Module({
  imports: [],
  providers: [OrganizationOwnershipService],
  exports: [OrganizationOwnershipService],
})
export class OrganizationModule {}
