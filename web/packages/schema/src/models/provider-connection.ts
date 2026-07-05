import z from "zod";

import type { ProviderConnection } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const ProviderConnectionSchema = z.object({
  id: z.uuid(),
  email: z.email(),
  userId: z.uuid(),
  primary: z.boolean(),
  emailVerifiedAt: z.iso.datetime().nullable(),
  providerId: z.uuid(),
  providerUniqueId: z.string(),
  data: z.unknown(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
}) satisfies PrismaZodType<ProviderConnection>;
