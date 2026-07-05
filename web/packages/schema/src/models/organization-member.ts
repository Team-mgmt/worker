import z from "zod";

import { UserType, type OrganizationMember } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const OrganizationMemberSchema = z.object({
  id: z.uuid(),
  userId: z.uuid(),
  organizationId: z.uuid(),
  type: z.enum(UserType),
  name: z.string(),
}) satisfies PrismaZodType<OrganizationMember>;
