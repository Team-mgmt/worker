import z from "zod";

import { ProviderCommonConfigSchema } from "./common.js";
import { StaticCredentialSchema } from "../credentials/static.js";

export const GoogleProviderConfigSchema = z
  .object({
    type: z.literal("google"),
    clientId: z.string(),
    credential: z.discriminatedUnion("type", [StaticCredentialSchema]),
    domainHint: z.string().optional(),
  })
  .extend(ProviderCommonConfigSchema.shape);

export type GoogleProviderConfig = z.infer<typeof GoogleProviderConfigSchema>;
