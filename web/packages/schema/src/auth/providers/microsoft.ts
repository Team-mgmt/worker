import z from "zod";

import { ProviderCommonConfigSchema } from "./common.js";
import { CognitoCredentialSchema } from "../credentials/cognito.js";

export const MicrosoftProviderConfigSchema = z
  .object({
    type: z.literal("microsoft"),
    clientId: z.string(),
    tenantId: z.string(),
    domainHint: z.string().optional(),
    credential: z.discriminatedUnion("type", [CognitoCredentialSchema]),
  })
  .extend(ProviderCommonConfigSchema.shape);

export type MicrosoftProviderConfig = z.infer<
  typeof MicrosoftProviderConfigSchema
>;
