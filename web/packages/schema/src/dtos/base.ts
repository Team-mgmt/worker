import z from "zod";

export const BaseSuccessSchema = z.object({
  result: z.literal(true),
});

export const BaseErrorResponse = z.object({
  result: z.literal(false),
  error: z.object({
    code: z.string(),
    params: z.record(z.string(), z.string()).optional(),
  }),
});

export const SlimBaseErrorResponse = z.object({
  code: z.string(),
  params: z.record(z.string(), z.string()).optional(),
});

export const ServicesSchema = z.enum(["backoffice"]);
export type Services = z.infer<typeof ServicesSchema>;
