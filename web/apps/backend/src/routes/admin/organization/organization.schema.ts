import { createZodDto } from "nestjs-zod";

import {
  AdminDeleteOrganizationResponseSchema,
  AdminListOrganizationsResponseSchema,
  AdminOrganizationResponseSchema,
  AdminUpdateOrganizationRequestSchema,
} from "@shelfalign/schema/dtos/admin/organization";

export class UpdateOrganizationDto extends createZodDto(
  AdminUpdateOrganizationRequestSchema,
) {}

export class OrganizationResponseDto extends createZodDto(
  AdminOrganizationResponseSchema,
) {}

export class ListOrganizationsResponseDto extends createZodDto(
  AdminListOrganizationsResponseSchema,
) {}

export class DeleteOrganizationResponseDto extends createZodDto(
  AdminDeleteOrganizationResponseSchema,
) {}
