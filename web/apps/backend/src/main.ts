import "./instrument";
import "./otel";

import { Logger } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import { DocumentBuilder, SwaggerModule } from "@nestjs/swagger";

import cookieParser from "cookie-parser";
import { cleanupOpenApiDoc } from "nestjs-zod";

import { AppModule } from "./app.module";
import { loadParsedEnv } from "./common/utils/env";

const logger = new Logger("Bootstrap");

async function bootstrap() {
  const env = loadParsedEnv();

  const app = await NestFactory.create(AppModule, {
    logger:
      env.NODE_ENV === "production"
        ? ["log", "warn", "error", "fatal"]
        : ["log", "warn", "error", "fatal", "debug", "verbose"],
    cors: {
      origin: (origin, callback) => {
        if (env.CORS_ORIGINS === undefined) {
          return callback(null, true);
        }
        if (typeof origin !== "string") {
          return callback(null, true);
        }
        if (env.CORS_ORIGINS.includes(origin)) {
          return callback(null, true);
        }
        return callback(null, false);
      },
      credentials: true,
      allowedHeaders: [
        "Authorization",
        "X-Turnstile-Token",
        "sentry-trace",
        "baggage",
        "content-type",
        "x-retry-request",
        "x-organization-id",
        "x-scan-token",
      ],
    },
  });

  const openApiDocument = SwaggerModule.createDocument(
    app,
    new DocumentBuilder()
      .setTitle("ShelfAlign Backend API")
      .setDescription("ShelfAlign Backend API Documentation")
      .setVersion("2.0")
      .build(),
  );
  SwaggerModule.setup("docs", app, cleanupOpenApiDoc(openApiDocument));

  app.use(cookieParser());

  // Disable 'X-Powered-By' header for security reasons
  app.getHttpAdapter().getInstance().disable("x-powered-by");

  const port = env.PORT ?? 4000;
  const host = process.env.HOST ?? "localhost";
  await app.listen(port, host);

  logger.log(`Server is running on http://${host}:${port}`);
}
bootstrap().catch((e) => {
  logger.error("Error during app bootstrap:", e);
  process.exit(1);
});
