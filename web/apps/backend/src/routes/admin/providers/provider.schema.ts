import { createZodDto } from "nestjs-zod";

import {
  AdminDeleteProviderResponseSchema,
  AdminListProvidersResponseSchema,
  AdminProviderResponseSchema,
} from "@shelfalign/schema/dtos/admin/provider";

export class ProviderResponseDto extends createZodDto(
  AdminProviderResponseSchema,
) {}

export class ListProvidersResponseDto extends createZodDto(
  AdminListProvidersResponseSchema,
) {}

export class DeleteProviderResponseDto extends createZodDto(
  AdminDeleteProviderResponseSchema,
) {}
