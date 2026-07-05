import {
  type ArgumentsHost,
  Catch,
  HttpException,
  Inject,
  Logger,
} from "@nestjs/common";
import { BaseExceptionFilter } from "@nestjs/core";

import * as Sentry from "@sentry/nestjs";
import { ZodSerializationException } from "nestjs-zod";
import { ZodError } from "zod";

import {
  BaseErrorResponse,
  SlimBaseErrorResponse,
} from "@shelfalign/schema/dtos/base";

import { EnvType, registerEnv } from "@/common/utils/env";

const STATUS_CODE_TO_ERROR_CODE: Record<number, string> = {
  400: "BAD_REQUEST",
  401: "UNAUTHORIZED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  429: "TOO_MANY_REQUESTS",
  502: "BAD_GATEWAY",
};

@Catch(HttpException)
export class HttpExceptionFilter extends BaseExceptionFilter {
  private readonly logger = new Logger(HttpExceptionFilter.name);

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
  ) {
    super();
  }

  override catch(exception: HttpException, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse();
    const request = ctx.getRequest();

    if (exception instanceof ZodSerializationException) {
      const zodError = exception.getZodError();
      if (zodError instanceof ZodError) {
        if (this.env.NODE_ENV === "production") {
          Sentry.captureException(zodError, {
            extra: {
              issues: zodError.issues,
              url: request.url,
              stack: zodError.stack,
            },
          });

          return response.status(400).json({
            result: false,
            error: {
              code: "BAD_REQUEST",
            },
          });
        }

        return response.status(400).json({
          result: false,
          error: {
            code: "BAD_REQUEST",
            details: zodError.issues,
          },
        });
      }
    }

    const message = exception.getResponse();
    const status = exception.getStatus();

    // If the response already matches our error format, use it directly
    if (BaseErrorResponse.safeParse(message).success) {
      return response.status(status).json(message);
    }

    // If the response is a slim error format, wrap it
    const slimParseResult = SlimBaseErrorResponse.safeParse(message);
    if (slimParseResult.success) {
      return response.status(status).json({
        result: false,
        error: slimParseResult.data,
      });
    }

    // Log server errors
    if (status >= 500) {
      this.logger.error(exception);
    }

    // Map status code to error code
    const errorCode = STATUS_CODE_TO_ERROR_CODE[status] ?? "UNKNOWN_ERROR";

    return response.status(status).json({
      result: false,
      error: {
        code: errorCode,
      },
    });
  }
}
