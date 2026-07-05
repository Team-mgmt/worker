import { Module } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { ScheduleModule } from "@nestjs/schedule";
import { ThrottlerModule } from "@nestjs/throttler";

import { SentryModule } from "@sentry/nestjs/setup";
import { ZodSerializerInterceptor, ZodValidationPipe } from "nestjs-zod";

import { AppController } from "./app.controller";
import { AllExceptionsFilter } from "./common/filters/all-exceptions.filter";
import { HttpExceptionFilter } from "./common/filters/http-exception";
import { RedirectFilter } from "./common/filters/redirect.filter";
import { UserAwareThrottlerGuard } from "./common/guards/user-aware-throttler.guard";
import { registerEnv } from "./common/utils/env";
import { CoreAuthModule } from "./core/auth/auth.module";
import { PermissionModule } from "./core/permission/permission.module";
import { SeedModule } from "./core/seed/seed.module";
import { CacheModule } from "./providers/cache/cache.module";
import { CognitoModule } from "./providers/cognito/cognito.module";
import { PrismaModule } from "./providers/database/prisma.module";
import { KeyModule } from "./providers/keys/keys.module";
import { S3Module } from "./providers/s3/s3.module";
import { AdminDocumentModule } from "./routes/admin/document/document.module";
import { AdminOrganizationModule } from "./routes/admin/organization/organization.module";
import { AdminProviderModule } from "./routes/admin/providers/provider.module";
import { AuthModule } from "./routes/auth/auth.module";
import { UploadModule } from "./routes/service/upload/upload.module";

@Module({
  imports: [
    ConfigModule.forRoot({
      load: [registerEnv],
      isGlobal: true,
      skipProcessEnv: true,
    }),
    ScheduleModule.forRoot(),
    SentryModule.forRoot(),
    ThrottlerModule.forRoot({
      throttlers: [{ ttl: 60_000, limit: 60 }],
    }),
    PrismaModule,
    CacheModule,
    S3Module,
    KeyModule,
    CognitoModule,
    CoreAuthModule,
    PermissionModule,
    SeedModule,
    AuthModule,
    UploadModule,
    AdminDocumentModule,
    AdminOrganizationModule,
    AdminProviderModule,
  ],
  providers: [
    {
      provide: "APP_GUARD",
      useClass: UserAwareThrottlerGuard,
    },
    {
      provide: "APP_PIPE",
      useClass: ZodValidationPipe,
    },
    {
      provide: "APP_INTERCEPTOR",
      useClass: ZodSerializerInterceptor,
    },
    {
      provide: "APP_FILTER",
      useClass: AllExceptionsFilter,
    },
    {
      provide: "APP_FILTER",
      useClass: RedirectFilter,
    },
    {
      provide: "APP_FILTER",
      useClass: HttpExceptionFilter,
    },
  ],
  controllers: [AppController],
})
export class AppModule {}
