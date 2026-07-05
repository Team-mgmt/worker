import z from "zod";

import type { PermissionRelation } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const PermissionRelationSchema = z.object({
  id: z.uuid(),
  name: z.string(),
}) satisfies PrismaZodType<PermissionRelation>;
