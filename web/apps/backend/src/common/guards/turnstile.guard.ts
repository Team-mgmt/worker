import {
  CanActivate,
  ExecutionContext,
  Inject,
  Injectable,
  Logger,
  mixin,
} from "@nestjs/common";

import z from "zod";

import { EnvType, registerEnv } from "@/common/utils/env";
import { CoreAuthService } from "@/core/auth/auth.service";

const TurnstileSuccessResponse = z.object({
  success: z.literal(true),
  challenge_ts: z.string(),
  hostname: z.string(),
  "error-codes": z.array(z.string()).optional(),
  action: z.string().optional(),
  cdata: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()),
});

const TurnstileFailedResponse = z.object({
  success: z.literal(false),
  "error-codes": z.array(z.string()),
});

const TurnstileResponse = z.union([
  TurnstileSuccessResponse,
  TurnstileFailedResponse,
]);

type TurnstileGuardOptions = {
  customError?: Error;
  customNoTokenError?: Error;
  customFailedError?: Error;
  skipIfAuthenticated?: boolean;
};

export function TurnstileGuard(options?: TurnstileGuardOptions) {
  @Injectable()
  class TurnstileGuardMixin implements CanActivate {
    readonly logger = new Logger(TurnstileGuardMixin.name);

    constructor(
      @Inject(registerEnv.KEY)
      readonly env: EnvType,
      readonly coreAuthService: CoreAuthService,
    ) {}

    async canActivate(context: ExecutionContext): Promise<boolean> {
      const request = context.switchToHttp().getRequest();
      const routePath = `${request.method ?? "?"} ${request.originalUrl ?? request.url ?? "?"}`;

      this.logger.verbose(
        `canActivate start: route=${routePath}, skipIfAuthenticated=${options?.skipIfAuthenticated ?? false}`,
      );

      if (this.env.NODE_ENV === "test") {
        this.logger.verbose(
          `Skipping Turnstile verification: NODE_ENV=test (route=${routePath})`,
        );
        return true;
      }

      if (options?.skipIfAuthenticated) {
        const authHeader = request.headers["authorization"];
        this.logger.verbose(
          `skipIfAuthenticated enabled: authorization header ${typeof authHeader === "string" ? "present" : "missing"}`,
        );
        if (typeof authHeader === "string") {
          const [type, token] = authHeader.split(" ");
          if (type === "Bearer" && token) {
            // Treat any validation failure (return `false` or thrown
            // TOKEN_EXPIRED/INVALID_TOKEN) as unauthenticated so the caller
            // falls through to the Turnstile path instead of 4xx-ing.
            let validateResult: Awaited<
              ReturnType<CoreAuthService["validateAccessToken"]>
            > = false;
            try {
              validateResult =
                await this.coreAuthService.validateAccessToken(token);
            } catch (err) {
              this.logger.verbose(
                `Bearer token validation threw, treating as unauthenticated: ${err instanceof Error ? err.message : String(err)}`,
              );
              validateResult = false;
            }
            if (validateResult) {
              this.logger.verbose(
                `Bearer token valid: userId=${validateResult.userId}, sessionId=${validateResult.sessionId} — skipping Turnstile`,
              );
              if (typeof request.locals === "undefined") {
                request.locals = {};
              }
              request.locals.sessionId = validateResult.sessionId;
              request.locals.userId = validateResult.userId;
              return true;
            }
            this.logger.verbose(
              "Bearer token invalid or expired, falling through to Turnstile verification",
            );
          } else {
            this.logger.verbose(
              `authorization header present but not a Bearer token (type=${type ?? "none"}), falling through to Turnstile verification`,
            );
          }
        }
      }

      const turnstileToken = request.headers["x-turnstile-token"];

      if ("x-turnstile-token" in request.headers === false) {
        this.logger.verbose(
          `x-turnstile-token header missing (route=${routePath})`,
        );
        if (options?.customNoTokenError) {
          throw options.customNoTokenError;
        }

        if (options?.customError) {
          throw options.customError;
        }
        return false;
      }

      if (!turnstileToken) {
        this.logger.verbose(
          `x-turnstile-token header present but empty (route=${routePath})`,
        );
        if (options?.customNoTokenError) {
          throw options.customNoTokenError;
        }

        if (options?.customError) {
          throw options.customError;
        }
        return false;
      }

      this.logger.verbose(
        `Verifying Turnstile token with Cloudflare siteverify (tokenLength=${String(turnstileToken).length})`,
      );

      const formData = new FormData();
      formData.append("secret", this.env.TURNSTILE_SECRET_KEY);
      formData.append("response", turnstileToken);

      const res = await fetch(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        {
          method: "POST",
          body: formData,
        },
      );

      this.logger.verbose(
        `Cloudflare siteverify responded: status=${res.status}`,
      );

      const data = TurnstileResponse.safeParse(await res.json());
      if (!data.success) {
        this.logger.error(
          `Turnstile verification response parse error: ${data.error.message}`,
        );

        if (options?.customError) {
          throw options.customError;
        }
        return false;
      }

      if (!data.data.success) {
        const codes = data.data["error-codes"] || [];
        this.logger.verbose(
          `Turnstile verification rejected: error-codes=[${codes.join(", ")}]`,
        );
        if (this.env.NODE_ENV === "development") {
          this.logger.error(
            `Turnstile verification failed: ${codes.join(", ")}`,
          );
        }

        if (options?.customFailedError) {
          throw options.customFailedError;
        }

        if (options?.customError) {
          throw options.customError;
        }
        return false;
      }

      this.logger.verbose(
        `Turnstile verification succeeded: hostname=${data.data.hostname}, action=${data.data.action ?? "none"}, challenge_ts=${data.data.challenge_ts}`,
      );

      return true;
    }
  }

  return mixin(TurnstileGuardMixin);
}
