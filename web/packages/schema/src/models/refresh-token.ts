import z from "zod";

import type { RefreshToken } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const RefreshTokenSchema = z.object({
  id: z.uuid(),
  sessionId: z.uuid(),
  familyId: z.uuid(),
  tokenHash: z.string(),
  expiresAt: z.iso.datetime(),
  rotatedAt: z.iso.datetime().nullable(),
  rotatedFromId: z.uuid().nullable(),
  createdAt: z.iso.datetime(),
  revokedAt: z.iso.datetime().nullable(),
  revokedReason: z.string().nullable(),
  metadata: z.unknown(),
}) satisfies PrismaZodType<RefreshToken>;
