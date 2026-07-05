import z from "zod";

import type { UploadFile } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const UploadFileSchema = z.object({
  id: z.uuid(),
  organizationId: z.uuid(),
  createdById: z.uuid().nullable(),
  key: z.string(),
  filename: z.string(),
  contentType: z.string(),
  size: z.number().int().nullable(),
  hash: z.string().nullable(),
  createdAt: z.iso.datetime(),
  finalizedAt: z.iso.datetime().nullable(),
}) satisfies PrismaZodType<UploadFile>;

export type UploadFileType = z.infer<typeof UploadFileSchema>;
