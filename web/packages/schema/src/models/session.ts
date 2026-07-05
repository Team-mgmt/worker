import z from "zod";

import type { Session } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const SessionSchema = z.object({
  id: z.uuid(),
  userId: z.uuid(),
  providerConnectionId: z.uuid(),
  metadata: z.unknown(),
  createdAt: z.iso.datetime(),
  expiresAt: z.iso.datetime(),
}) satisfies PrismaZodType<Session>;
