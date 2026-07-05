import type z from "zod";

import type { Prisma } from "@shelfalign/database/types";

type Equals<T, U> =
  (<G>() => G extends T ? 1 : 2) extends <G>() => G extends U ? 1 : 2
    ? true
    : false;

export type DateToString<T> = T extends Date
  ? string
  : T extends Array<infer U>
    ? Array<DateToString<U>>
    : T extends Record<string, unknown>
      ? { [K in keyof T]: DateToString<T[K]> }
      : T;

export type PrismaJsonToUnknown<T> =
  Equals<T, Prisma.JsonValue> extends true
    ? unknown
    : T extends Array<T>
      ? Array<PrismaJsonToUnknown<T[number]>>
      : T extends Record<string, unknown>
        ? { [K in keyof T]: PrismaJsonToUnknown<T[K]> }
        : T;

export type PrismaZodType<T> = z.ZodType<DateToString<PrismaJsonToUnknown<T>>>;
