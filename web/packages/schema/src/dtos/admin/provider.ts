import z from "zod";

import { ProviderSchema } from "@/models/provider.js";

import { BaseSuccessSchema } from "../base.js";

export const AdminProviderResponseSchema = z.object({
  result: z.literal(true),
  data: ProviderSchema,
});
export type AdminProviderResponse = z.infer<typeof AdminProviderResponseSchema>;

export const AdminListProvidersResponseSchema = z.object({
  result: z.literal(true),
  data: z.array(ProviderSchema),
  count: z.number(),
});
export type AdminListProvidersResponse = z.infer<
  typeof AdminListProvidersResponseSchema
>;

export const AdminDeleteProviderResponseSchema = BaseSuccessSchema;
export type AdminDeleteProviderResponse = z.infer<
  typeof AdminDeleteProviderResponseSchema
>;
