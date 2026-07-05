import z from "zod";

export const StaticCredentialSchema = z.object({
  type: z.literal("static"),
  clientSecret: z.string(),
});
export type StaticCredential = z.infer<typeof StaticCredentialSchema>;
