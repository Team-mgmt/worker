import z from "zod";

import type { Organization } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const OrganizationSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  deletedAt: z.iso.datetime().nullable(),
}) satisfies PrismaZodType<Organization>;
