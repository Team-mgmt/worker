import { createZodDto } from "nestjs-zod";

import {
  GeneratePresignedUrlRequestSchema,
  GeneratePresignedUrlResponseSchema,
} from "@shelfalign/schema/dtos/service/upload";

export class GeneratePresignedUrlRequestDto extends createZodDto(
  GeneratePresignedUrlRequestSchema,
) {}
export class GeneratePresignedUrlResponseDto extends createZodDto(
  GeneratePresignedUrlResponseSchema,
) {}
