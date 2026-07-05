import z from "zod";

export const ProviderCommonConfigSchema = z.object({
  disableSignUp: z.boolean().optional(),
  disableInvite: z.boolean().optional(),
});
