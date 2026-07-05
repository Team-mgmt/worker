import type z from "zod";

export const INVALID_JSON = Symbol("INVALID_JSON");
export const INVALID_DATA = Symbol("INVALID_DATA");
export function tryJson<T>(
  input: string,
  schema?: z.ZodType<T>,
): T | typeof INVALID_JSON | typeof INVALID_DATA {
  try {
    const result = JSON.parse(input);
    if (!schema) return result;
    const schemaResult = schema.safeParse(result);
    if (schemaResult.success) return schemaResult.data;

    return INVALID_DATA;
  } catch {
    return INVALID_JSON;
  }
}

type DateTimeHandled<T> = T extends Date
  ? string
  : T extends Array<infer U>
    ? Array<DateTimeHandled<U>>
    : T extends Record<string, unknown>
      ? { [K in keyof T]: DateTimeHandled<T[K]> }
      : T;

export function handleDateTime<T>(data: T): DateTimeHandled<T> {
  if (data instanceof Date) {
    return data.toISOString() as DateTimeHandled<T>;
  }

  if (Array.isArray(data)) {
    return data.map((item) => handleDateTime(item)) as DateTimeHandled<T>;
  }

  if (typeof data === "object" && data !== null) {
    const result: Record<string, unknown> = {};
    for (const key in data) {
      if (Object.prototype.hasOwnProperty.call(data, key)) {
        const value = (data as Record<string, unknown>)[key];
        result[key] = handleDateTime(value);
      }
    }
    return result as DateTimeHandled<T>;
  }

  return data as DateTimeHandled<T>;
}
