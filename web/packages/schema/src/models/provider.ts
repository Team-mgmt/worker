import z from "zod";

import type { Provider } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const ProviderSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  config: z.unknown(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  deletedAt: z.iso.datetime().nullable(),
}) satisfies PrismaZodType<Provider>;
