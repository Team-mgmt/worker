import { loadEnvFile } from "node:process";

import { ConfigType, registerAs } from "@nestjs/config";

import z from "zod";

export const envSchema = z.object({
  NODE_ENV: z
    .enum(["development", "production", "staging", "test", "local"])
    .default("development"),
  PORT: z.string().default("4000").transform(Number),
  CORS_ORIGINS: z.string().array().optional(),
  TURNSTILE_SECRET_KEY: z.string(),
  CACHE_HOST: z.string(),
  CACHE_PORT: z.string().default("6379").transform(Number),
  CACHE_USERNAME: z.string(),
  CACHE_PASSWORD: z.string().optional(),
  CACHE_INSECURE: z.string().default("false"),
  CACHE_SINGLE_NODE: z.string().default("false"),
  DATABASE_HOST: z.string(),
  READONLY_HOST: z.string().optional(),
  DATABASE_USER: z.string(),
  DATABASE_PASS: z.string().optional(),
  DATABASE_PORT: z.string().default("5432").transform(Number),
  DATABASE_NAME: z.string(),
  DATABASE_LOCAL: z.string().default("false"),
  AWS_ACCESS_KEY_ID: z.string().optional(),
  AWS_SECRET_ACCESS_KEY: z.string().optional(),
  AWS_SESSION_TOKEN: z.string().optional(),
  AWS_REGION: z.string().optional(),
  S3_BUCKET_NAME: z.string(),
  DEBUG_S3_BUCKET: z.string().optional(),
  DEBUG_S3_PREFIX: z.string().default("debug"),
  CLOUDFRONT_URL: z.url(),
  CLOUDFRONT_ID: z.string(),
  AUTH_KEY_SECRET_ID: z.string(),
  AUTH_REFRESH_TOKEN_COOKIE_NAME: z.string(),
  SCAN_URL_BASE: z.url(),
  FRONTEND_URL: z.url(),
  MAIL_TRANSPORT: z.enum(["ses", "stream"]).default("stream"),
  MAIL_FROM: z.string().optional(),
  OPENAI_API_KEY: z.string().optional(),
});

export const loadParsedEnv = () => {
  try {
    loadEnvFile();
  } catch (err) {
    const code =
      typeof err === "object" && err !== null && "code" in err
        ? (err as { code?: unknown }).code
        : undefined;
    if (code !== "ENOENT") {
      throw err;
    }
  }
  return envSchema.parse(process.env);
};

export const registerEnv = registerAs("ENV", loadParsedEnv);

export type EnvType = ConfigType<typeof registerEnv>;
