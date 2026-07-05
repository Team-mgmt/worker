import z from "zod";

export const SessionCacheSchema = z.object({
  sessionId: z.uuid(),
  userId: z.uuid(),
});
export type SessionCacheType = z.infer<typeof SessionCacheSchema>;
