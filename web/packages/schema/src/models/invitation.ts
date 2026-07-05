import z from "zod";

import type { Invitation } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const InvitationSchema = z.object({
  id: z.uuid(),
  email: z.string(),
  organizationId: z.uuid(),
  invitedById: z.uuid(),
  acceptedAt: z.iso.datetime().nullable(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  revokedAt: z.iso.datetime().nullable(),
}) satisfies PrismaZodType<Invitation>;
