import z from "zod";

export const VerifyEmailSendResponseSchema = z.object({
  result: z.literal(true),
});
export type VerifyEmailSendResponse = z.infer<
  typeof VerifyEmailSendResponseSchema
>;

export const VerifyEmailConfirmRequestSchema = z.object({
  token: z.string().min(10),
});
export type VerifyEmailConfirmRequest = z.infer<
  typeof VerifyEmailConfirmRequestSchema
>;

export const VerifyEmailConfirmResponseSchema = z.object({
  result: z.literal(true),
});
export type VerifyEmailConfirmResponse = z.infer<
  typeof VerifyEmailConfirmResponseSchema
>;
