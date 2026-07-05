import z from "zod";

export const ForgotPasswordRequestSchema = z.object({
  email: z.email(),
});
export type ForgotPasswordRequest = z.infer<typeof ForgotPasswordRequestSchema>;

export const ForgotPasswordResponseSchema = z.object({
  result: z.literal(true),
});
export type ForgotPasswordResponse = z.infer<
  typeof ForgotPasswordResponseSchema
>;

export const ResetPasswordRequestSchema = z.object({
  token: z.string().min(10),
  password: z.string().min(8),
});
export type ResetPasswordRequest = z.infer<typeof ResetPasswordRequestSchema>;

export const ResetPasswordResponseSchema = z.object({
  result: z.literal(true),
});
export type ResetPasswordResponse = z.infer<typeof ResetPasswordResponseSchema>;
