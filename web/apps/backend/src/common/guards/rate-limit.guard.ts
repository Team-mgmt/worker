import {
  CanActivate,
  ExecutionContext,
  HttpException,
  Injectable,
  mixin,
} from "@nestjs/common";

import { CacheService } from "@/providers/cache/cache.service";

type RateLimitRule = {
  /** Max tokens in the bucket (also the burst ceiling). */
  capacity: number;
  /** Seconds for the bucket to refill from empty to full. */
  windowSec: number;
};

type RateLimitGuardOptions = {
  name: string;
  authenticated: RateLimitRule;
  anonymous: RateLimitRule;
};

type RateLimitRequest = {
  locals?: { userId?: string };
  headers: Record<string, string | string[] | undefined>;
  socket?: { remoteAddress?: string };
};

function resolveClientIp(request: RateLimitRequest): string | null {
  const forwardedFor = request.headers["x-forwarded-for"];
  const forwardedValue = Array.isArray(forwardedFor)
    ? forwardedFor[0]
    : forwardedFor;
  if (typeof forwardedValue === "string" && forwardedValue.length > 0) {
    const [first] = forwardedValue.split(",");
    const trimmed = first?.trim();
    if (trimmed) {
      return trimmed;
    }
  }

  const remoteAddress = request.socket?.remoteAddress;
  if (typeof remoteAddress === "string" && remoteAddress.length > 0) {
    return remoteAddress;
  }

  return null;
}

function resolveBucket(
  request: RateLimitRequest,
): { bucket: string; authenticated: boolean } | null {
  const userId = request.locals?.userId;
  if (userId) {
    return { bucket: `user:${userId}`, authenticated: true };
  }

  // Anonymous bucket is keyed on client IP. Turnstile tokens are single-use
  // and clients request a fresh one per action, so keying on the token would
  // give every request its own bucket and defeat the limiter.
  const ip = resolveClientIp(request);
  if (!ip) {
    return null;
  }

  return { bucket: `ip:${ip}`, authenticated: false };
}

export function RateLimitGuard(options: RateLimitGuardOptions) {
  @Injectable()
  class RateLimitGuardMixin implements CanActivate {
    constructor(private readonly cacheService: CacheService) {}

    async canActivate(context: ExecutionContext): Promise<boolean> {
      const request = context.switchToHttp().getRequest();
      const resolved = resolveBucket(request);

      if (!resolved) {
        throw new HttpException({ code: "RATE_LIMIT_BUCKET_MISSING" }, 429);
      }

      const rule = resolved.authenticated
        ? options.authenticated
        : options.anonymous;
      const key = `ratelimit:${options.name}:${resolved.bucket}`;

      const result = await this.cacheService.callFunction(
        "token_bucket",
        1,
        key,
        rule.capacity,
        rule.windowSec * 1000,
        Date.now(),
        rule.windowSec,
      );

      if (!Array.isArray(result) || result.length < 2) {
        throw new Error(
          `token_bucket returned unexpected shape: ${JSON.stringify(result)}`,
        );
      }

      const allowed = Number(result[0]) === 1;
      if (!allowed) {
        const retryAfterMs = Number(result[1]);
        throw new HttpException(
          {
            code: "RATE_LIMIT_EXCEEDED",
            params: {
              capacity: rule.capacity,
              windowSec: rule.windowSec,
              retryAfterMs,
            },
          },
          429,
        );
      }

      return true;
    }
  }

  return mixin(RateLimitGuardMixin);
}
