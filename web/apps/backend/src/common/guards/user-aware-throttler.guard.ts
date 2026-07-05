import { ExecutionContext, Inject, Injectable } from "@nestjs/common";
import { Reflector } from "@nestjs/core";
import {
  ThrottlerGuard,
  ThrottlerModuleOptions,
  ThrottlerStorage,
} from "@nestjs/throttler";

import { ADMIN_ORGANIZATION_ID } from "@/common/constants";
import { CoreAuthService } from "@/core/auth/auth.service";

// Default ThrottlerGuard keys by client IP, which lumps all users behind a
// shared NAT/proxy into one bucket. Override the tracker so authenticated
// requests are keyed by userId — that matches the per-user limit advertised
// on routes like POST /service/upload. Admins (backoffice users) bypass
// throttling entirely via shouldSkip — the default safety-net limit gets in
// the way of legitimate admin tooling and admin routes are already gated by
// ADMIN-scoped AuthGuards.
//
// Note on ordering: this is registered as APP_GUARD and runs before any
// route-level AuthGuard, so `request.locals.userId` is not yet populated.
// Validate the access token here directly via CoreAuthService — the same
// call AuthGuard makes — and use the cached result. AuthGuard's later call
// hits the session cache populated here, so the extra work is one Redis
// get on the hot path.

type ResolvedSession = {
  userId: string;
  isAdmin: boolean;
};

const RESOLVED_SESSION_KEY = "__userAwareThrottlerSession__";

@Injectable()
export class UserAwareThrottlerGuard extends ThrottlerGuard {
  constructor(
    @Inject("THROTTLER:MODULE_OPTIONS") options: ThrottlerModuleOptions,
    @Inject(ThrottlerStorage) storageService: ThrottlerStorage,
    reflector: Reflector,
    private readonly coreAuthService: CoreAuthService,
  ) {
    super(options, storageService, reflector);
  }

  protected override async shouldSkip(
    context: ExecutionContext,
  ): Promise<boolean> {
    const req = context.switchToHttp().getRequest<Record<string, unknown>>();
    const session = await this.resolveSession(req);
    return session?.isAdmin === true;
  }

  protected override async getTracker(
    req: Record<string, unknown>,
  ): Promise<string> {
    const session = await this.resolveSession(req);
    if (session?.userId) {
      return `user:${session.userId}`;
    }
    return super.getTracker(req);
  }

  // Memoize the validated token on the request so shouldSkip and getTracker
  // — both invoked during canActivate — don't each pay the cost of a full
  // JWT signature verification.
  private async resolveSession(
    req: Record<string, unknown>,
  ): Promise<ResolvedSession | null> {
    const cached = (req as Record<string, unknown>)[RESOLVED_SESSION_KEY] as
      | ResolvedSession
      | null
      | undefined;
    if (cached !== undefined) {
      return cached;
    }
    const session = await this.computeSession(req);
    (req as Record<string, unknown>)[RESOLVED_SESSION_KEY] = session;
    return session;
  }

  private async computeSession(
    req: Record<string, unknown>,
  ): Promise<ResolvedSession | null> {
    const headers = (req as { headers?: Record<string, unknown> }).headers;
    const authHeader = headers?.["authorization"];
    if (typeof authHeader !== "string") {
      return null;
    }

    const [type, token] = authHeader.split(" ");
    if (type !== "Bearer" || !token) {
      return null;
    }

    // validateAccessToken (via keyService.validateToken) throws
    // BadRequestException on malformed/expired tokens. Swallow those
    // here and fall back to IP — otherwise a stale Authorization header
    // on a public route would 400 instead of just being IP-throttled.
    // Real auth enforcement is the route-level AuthGuard's job.
    try {
      const result = await this.coreAuthService.validateAccessToken(token);
      if (!result || !result.userId) {
        return null;
      }
      return {
        userId: result.userId,
        isAdmin: result.permissions[ADMIN_ORGANIZATION_ID] === "ADMIN",
      };
    } catch {
      return null;
    }
  }
}
