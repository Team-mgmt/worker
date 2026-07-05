import {
  type ArgumentsHost,
  Catch,
  type ExceptionFilter,
  Logger,
} from "@nestjs/common";

import { Response } from "express";

import { redactErrorForLog } from "../utils/redact-error";

// Catches anything the typed filters (HttpExceptionFilter, RedirectFilter)
// didn't claim. Registered first in app.module.ts so NestJS's reverse ordering
// puts it at the bottom of the match chain. Without this, NestJS's default
// ExceptionsHandler logs the full error object — and iovalkey's ReplyError
// carries the failing command's arguments, so an AUTH failure leaks the
// presigned IAM URL.
@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  private readonly logger = new Logger("AllExceptionsFilter");

  catch(exception: unknown, host: ArgumentsHost) {
    const safe = redactErrorForLog(exception);
    this.logger.error(`Unhandled exception: ${safe.message}`, safe.stack);

    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    response.status(500).json({
      result: false,
      error: { code: "INTERNAL_SERVER_ERROR" },
    });
  }
}
