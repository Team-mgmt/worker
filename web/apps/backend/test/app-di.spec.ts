import { NestFactory } from "@nestjs/core";

const testEnv: Record<string, string> = {
  NODE_ENV: "test",
  TURNSTILE_SECRET_KEY: "test-turnstile-secret",
  CACHE_HOST: "localhost",
  CACHE_PORT: "6379",
  CACHE_USERNAME: "default",
  CACHE_PASSWORD: "test-cache-password",
  CACHE_INSECURE: "true",
  CACHE_SINGLE_NODE: "true",
  DATABASE_HOST: "localhost",
  DATABASE_USER: "postgres",
  DATABASE_PASS: "postgres",
  DATABASE_PORT: "5432",
  DATABASE_NAME: "postgres",
  DATABASE_LOCAL: "true",
  AWS_REGION: "ap-northeast-2",
  S3_BUCKET_NAME: "shelfalign-test-bucket",
  CLOUDFRONT_URL: "https://cdn.example.test",
  CLOUDFRONT_ID: "test-cloudfront",
  AUTH_KEY_SECRET_ID: "test-auth-secret",
  AUTH_REFRESH_TOKEN_COOKIE_NAME: "shelfalign_refresh_token",
  SCAN_URL_BASE: "https://scan.shelfalign.test",
  FRONTEND_URL: "https://backoffice.shelfalign.test",
};

for (const [key, value] of Object.entries(testEnv)) {
  process.env[key] ??= value;
}

describe("AppModule dependency injection", () => {
  it("creates the main Nest application", async () => {
    const { AppModule } = await import("../src/app.module");

    // Intentionally do not call app.init(); this checks DI resolution without
    // starting lifecycle hooks that connect to external services.
    const app = await NestFactory.create(AppModule, {
      abortOnError: false,
      logger: false,
    });

    expect(app).toBeDefined();
    await app.getHttpAdapter().close();
  });
});
