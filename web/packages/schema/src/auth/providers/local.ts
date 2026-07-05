import z from "zod";

export const LocalProviderDataSchema = z.object({
  password: z.string(),
});
