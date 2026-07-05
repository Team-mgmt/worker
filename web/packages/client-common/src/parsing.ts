import type { z } from "zod";

import type { KyResponse } from "ky";
import { toast } from "sonner";

import { BaseErrorResponse } from "@shelfalign/schema/dtos/base";

import { ERROR_MESSAGES, ErrorResponseError, HandledParseError } from "./error";

export const INVALID_JSON = Symbol("INVALID_JSON");
export const INVALID_DATA = Symbol("INVALID_DATA");

function isProduction(): boolean {
  const importMeta = import.meta;
  if (typeof importMeta !== "object") {
    return false;
  }

  if (!("env" in importMeta)) {
    return false;
  }

  if (typeof importMeta.env !== "object" || importMeta.env === null) {
    return false;
  }

  if (!("MODE" in importMeta.env)) {
    return false;
  }

  return importMeta.env.MODE === "production";
}

export function tryJson<T>(
  input: string,
  schema?: z.ZodType<T>,
  debug?: boolean,
): T | typeof INVALID_JSON | typeof INVALID_DATA {
  try {
    const result = JSON.parse(input);
    if (!schema) return result;
    const schemaResult = schema.safeParse(result);
    if (schemaResult.success) return schemaResult.data;
    if (debug ?? !isProduction()) {
      console.error(input);
      console.error(schemaResult.error);
    }

    return INVALID_DATA;
  } catch (e) {
    if (debug ?? !isProduction()) {
      console.error(input);
      console.error(e);
    }
    return INVALID_JSON;
  }
}

export function tryResponseJson<T>(
  input: string,
  schema: z.ZodType<T>,
  debug?: boolean,
): T | typeof INVALID_JSON | typeof INVALID_DATA {
  const errorResponse = tryJson(input, BaseErrorResponse, false);
  if (errorResponse === INVALID_JSON) {
    return INVALID_JSON;
  }

  if (errorResponse !== INVALID_DATA) {
    throw new ErrorResponseError(
      errorResponse.error.code,
      errorResponse.error.params,
    );
  }

  return tryJson<T>(input, schema, debug);
}

export function toastError<T>(
  res: KyResponse<unknown>,
  result: T | typeof INVALID_DATA | typeof INVALID_JSON,
) {
  if (result === INVALID_DATA || result === INVALID_JSON) {
    toast.error("오류", {
      description: "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
    });
    throw new HandledParseError(res.url, res.status);
  }

  return result;
}

export function toastParseError<T extends Record<string, unknown>>(
  res: KyResponse<unknown>,
  result: T | typeof INVALID_DATA | typeof INVALID_JSON,
) {
  if (result === INVALID_DATA || result === INVALID_JSON) {
    toast.error("오류", {
      description: "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
    });
    throw new HandledParseError(res.url, res.status);
  }

  const errorResponse = BaseErrorResponse.safeParse(result);
  if (errorResponse.success) {
    if (!(errorResponse.data.error.code in ERROR_MESSAGES)) {
      toast.error("오류", {
        description: "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요",
      });
      throw new HandledParseError(res.url, res.status);
    }

    const message =
      ERROR_MESSAGES[
        errorResponse.data.error.code as keyof typeof ERROR_MESSAGES
      ];

    for (const [key, value] of Object.entries<string>(
      errorResponse.data.error.params ?? {},
    )) {
      message.title = message.title.replaceAll(`{${key}}`, value);
      message.message = message.message.replaceAll(`{${key}}`, value);
    }

    toast.error(message.title, {
      description: message.message,
    });
    throw new HandledParseError(res.url, res.status);
  }

  return result as T;
}
