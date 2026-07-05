import {
  BadRequestException,
  createParamDecorator,
  ExecutionContext,
} from "@nestjs/common";

import { z } from "zod";

import { base64UrlToUuid } from "@/common/utils/string";

const IdSchema = z.union([
  z.uuid(),
  z
    .base64url()
    .refine((val) => val.length === 22, "base64url uuid must be 22 characters")
    .transform((val) => base64UrlToUuid(val))
    .pipe(z.uuid()),
]);

/**
 * Custom parameter decorator that extracts and validates UUID from route params.
 * Accepts both raw UUID format (36 chars with dashes) and base64url-encoded UUID (22 chars).
 *
 * @param paramName - The name of the route parameter to extract
 *
 * @example
 * ```typescript
 * @Get(':userId')
 * async getUser(@ParamId('userId') userId: string) {
 *   // userId is guaranteed to be a valid UUID
 * }
 * ```
 */
export const ParamId = createParamDecorator(
  (paramName: string, ctx: ExecutionContext): string => {
    const request = ctx.switchToHttp().getRequest();
    const value = request.params[paramName];

    if (!value || typeof value !== "string") {
      throw new BadRequestException({
        code: "MISSING_PARAM",
        message: `Parameter '${paramName}' is required`,
        params: { paramName },
      });
    }

    const result = IdSchema.safeParse(value);
    if (!result.success) {
      throw new BadRequestException({
        code: "INVALID_ID_FORMAT",
        message: `Validation failed (uuid or base64url uuid expected) for parameter '${paramName}'`,
        params: { paramName },
      });
    }

    return result.data.toLowerCase();
  },
);
