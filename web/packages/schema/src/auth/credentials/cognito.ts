import z from "zod";

export const CognitoCredentialSchema = z.object({
  type: z.literal("cognito"),
  identityPoolId: z.string(),
  providerName: z.string(),
  loginName: z.string(),
});
export type CognitoCredential = z.infer<typeof CognitoCredentialSchema>;
