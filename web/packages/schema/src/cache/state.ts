import z from "zod";

import { ServicesSchema } from "@/dtos/base";

export const StateCacheSchema = z.object({
  codeVerifier: z.string(),
  userAgent: z.string(),
  requestIp: z.string(),
  oauthSession: z.uuidv7(),
  initiatedFrom: ServicesSchema,
  provider: z.uuid(),
  inviteId: z.string().optional(),
});
export type StateCache = z.infer<typeof StateCacheSchema>;
