import { createZodDto } from "nestjs-zod";
import { z } from "zod";

export const PaginationQuerySchema = z.object({
  page: z.coerce.number().int().positive().default(1),
  pageSize: z.coerce.number().int().positive().default(10),
});

export class PaginationQueryDto extends createZodDto(PaginationQuerySchema) {}
