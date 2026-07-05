import z from "zod";

import type { PermissionTuple } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const PermissionTupleSchema = z.object({
  id: z.uuid(),
  label: z.string(),
  namespace: z.uuid(),
  objectId: z.uuid(),
  relationId: z.uuid(),
  memberId: z.uuid().nullable(),
  targetId: z.uuid().nullable(),
  organizationId: z.uuid(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  revokedAt: z.iso.datetime().nullable(),
  revokeReason: z.string().nullable(),
}) satisfies PrismaZodType<PermissionTuple>;
