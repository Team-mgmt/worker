import z from "zod";

import { OrganizationSchema } from "@/models/organization";

import { BaseSuccessSchema } from "../base.js";

export const AdminUpdateOrganizationRequestSchema = z.object({
  name: z.string().min(1).optional(),
});
export type AdminUpdateOrganizationRequest = z.infer<
  typeof AdminUpdateOrganizationRequestSchema
>;

export const AdminOrganizationResponseSchema = z.object({
  result: z.literal(true),
  data: OrganizationSchema,
});
export type AdminOrganizationResponse = z.infer<
  typeof AdminOrganizationResponseSchema
>;

export const AdminListOrganizationsResponseSchema = z.object({
  result: z.literal(true),
  data: z.array(OrganizationSchema),
  count: z.number(),
});
export type AdminListOrganizationsResponse = z.infer<
  typeof AdminListOrganizationsResponseSchema
>;

export const AdminDeleteOrganizationResponseSchema = BaseSuccessSchema;
export type AdminDeleteOrganizationResponse = z.infer<
  typeof AdminDeleteOrganizationResponseSchema
>;
