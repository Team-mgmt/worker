import z from "zod";

import type { User } from "@shelfalign/database/types";

import type { PrismaZodType } from "./base.js";

export const UserSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  phone: z.string().nullable(),
  nickname: z.string().nullable(),
  picture: z.string().nullable(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  deletedAt: z.iso.datetime().nullable(),
}) satisfies PrismaZodType<User>;
