import z from "zod";

export const OIDCWellKnownConfigSchema = z.object({
  issuer: z.url(),
  authorization_endpoint: z.url(),
  token_endpoint: z.url().optional(),
  jwks_uri: z.url(),
  registration_endpoint: z.url().optional(),
  scopes_supported: z.array(z.string()).optional(),
  response_types_supported: z.array(z.string()),
  response_modes_supported: z.array(z.string()).optional(),
  grant_types_supported: z.array(z.string()).optional(),
  acr_values_supported: z.array(z.string()).optional(),
  subject_types_supported: z.array(z.string()),
  id_token_signing_alg_values_supported: z.array(z.string()),
  id_token_encryption_alg_values_supported: z.array(z.string()).optional(),
  id_token_encryption_enc_values_supported: z.array(z.string()).optional(),
  userinfo_signing_alg_values_supported: z.array(z.string()).optional(),
  userinfo_encryption_alg_values_supported: z.array(z.string()).optional(),
  userinfo_encryption_enc_values_supported: z.array(z.string()).optional(),
  request_object_signing_alg_values_supported: z.array(z.string()).optional(),
  request_object_encryption_alg_values_supported: z
    .array(z.string())
    .optional(),
  request_object_encryption_enc_values_supported: z
    .array(z.string())
    .optional(),
  token_endpoint_auth_methods_supported: z.array(z.string()).optional(),
  token_endpoint_auth_signing_alg_values_supported: z
    .array(z.string())
    .optional(),
  display_values_supported: z.array(z.string()).optional(),
  claim_types_supported: z.array(z.string()).optional(),
  claims_supported: z.array(z.string()).optional(),
  service_documentation: z.url().optional(),
  claims_locales_supported: z.array(z.string()).optional(),
  ui_locales_supported: z.array(z.string()).optional(),
  claims_parameter_supported: z.boolean().optional(),
  request_parameter_supported: z.boolean().optional(),
  request_uri_parameter_supported: z.boolean().optional(),
  require_request_uri_registration: z.boolean().optional(),
  op_policy_uri: z.url().optional(),
  op_tos_uri: z.url().optional(),
});

export type OIDCWellKnownConfig = z.infer<typeof OIDCWellKnownConfigSchema>;

export const BaseOIDCProviderConfigSchema = z.object({
  wellKnownUrl: z.url(),
  clientId: z.string(),
});

export type BaseOIDCProviderConfig = z.infer<
  typeof BaseOIDCProviderConfigSchema
>;
