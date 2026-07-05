import crypto from "node:crypto";

import {
  BadRequestException,
  Inject,
  Injectable,
  InternalServerErrorException,
  Logger,
} from "@nestjs/common";

import jose from "jose";
import { v7 as uuidv7 } from "uuid";

import { UserType } from "@shelfalign/database/types";
import {
  AccessTokenPayload,
  AccessTokenPayloadSchema,
  RefreshTokenPayload,
} from "@shelfalign/schema/dtos/auth";

import { EnvType, registerEnv } from "@/common/utils/env";
import { createDigest } from "@/common/utils/error";
import { INVALID_DATA, INVALID_JSON, tryJson } from "@/common/utils/zod";
import { CacheService } from "@/providers/cache/cache.service";
import { PrismaService } from "@/providers/database/prisma.service";
import { KeyService } from "@/providers/keys/keys.service";

import { SessionCacheSchema } from "./auth.schema";

@Injectable()
export class CoreAuthService {
  private readonly logger = new Logger(CoreAuthService.name);
  private readonly issuer: string;
  private readonly audience: string;
  private readonly secretId: string;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
    private readonly prismaService: PrismaService,
    private readonly cacheService: CacheService,
    private readonly keyService: KeyService,
  ) {
    if (this.env.NODE_ENV === "production") {
      this.issuer = "https://api.shelfalign.kr";
      this.audience = "https://shelfalign.kr";
    } else if (this.env.NODE_ENV === "local") {
      this.issuer = `http://localhost:${this.env.PORT}`;
      this.audience = `http://localhost:${this.env.PORT}`;
    } else if (this.env.NODE_ENV === "development") {
      this.issuer = "https://dev-api.shelfalign.kr";
      this.audience = "https://dev.shelfalign.kr";
    } else {
      this.issuer = `https://${this.env.NODE_ENV}-api.shelfalign.kr`;
      this.audience = `https://${this.env.NODE_ENV}.shelfalign.kr`;
    }
    this.secretId = this.env.AUTH_KEY_SECRET_ID;
  }

  async createAccessToken(
    sessionId: string,
    userTypes: Record<string, UserType>,
  ) {
    const session = await this.prismaService.session.findUnique({
      where: {
        id: sessionId,
      },
    });

    if (!session) {
      const digest = createDigest(
        this.logger,
        `Session not found for sessionId: ${sessionId}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const latestKey = await this.keyService.getLatestKey(this.secretId);

    const accessToken = await new jose.SignJWT({
      sessionId,
      permissions: userTypes,
    } satisfies AccessTokenPayload)
      .setProtectedHeader({
        alg: "ES512",
        sub: session.userId,
        aud: `${this.audience}/accessToken`,
        iss: this.issuer,
        kid: latestKey.keyId,
        jti: uuidv7(),
      })
      .setExpirationTime("3h")
      .sign(latestKey.key.private);

    return accessToken;
  }

  async createRefreshToken(sessionId: string, previousTokenId?: string) {
    const session = await this.prismaService.session.findUnique({
      where: {
        id: sessionId,
      },
    });

    if (!session) {
      const digest = createDigest(
        this.logger,
        `Session not found for sessionId: ${sessionId}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const previousToken = previousTokenId
      ? await this.prismaService.refreshToken.findUnique({
          where: {
            id: previousTokenId,
          },
        })
      : null;

    if (previousTokenId && !previousToken) {
      const digest = createDigest(
        this.logger,
        `Previous token not found for tokenId: ${previousTokenId}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    if (previousToken) {
      if (previousToken.revokedAt) {
        throw new BadRequestException({
          code: "TOKEN_REVOKED",
          params: {},
        });
      }

      if (previousToken.expiresAt < new Date()) {
        throw new BadRequestException({
          code: "TOKEN_EXPIRED",
          params: {},
        });
      }
    }

    const latestKey = await this.keyService.getLatestKey(this.secretId);

    const tokenId = uuidv7();
    const refreshToken = await new jose.SignJWT(
      {} satisfies RefreshTokenPayload,
    )
      .setProtectedHeader({
        alg: "ES512",
        sub: session.userId,
        aud: `${this.audience}/refreshToken`,
        iss: this.issuer,
        jti: tokenId,
        kid: latestKey.keyId,
      })
      .sign(latestKey.key.private);

    const tokenHash = await crypto
      .createHash("sha256")
      .update(refreshToken)
      .digest("hex");

    await this.prismaService.refreshToken.create({
      data: {
        id: tokenId,
        sessionId: session.id,
        familyId: previousToken ? previousToken.familyId : uuidv7(),
        tokenHash,
        expiresAt: new Date(Date.now() + 3 * 60 * 60 * 1000), // 3 hours
        metadata: {},
      },
    });

    if (previousToken) {
      await this.prismaService.refreshToken.update({
        where: {
          id: previousToken.id,
        },
        data: {
          revokedAt: new Date(),
          revokedReason: "TOKEN_ROTATED",
        },
      });
    }

    return refreshToken;
  }

  async validateAccessToken(token: string) {
    const validateResult = await this.keyService.validateToken(
      this.env.AUTH_KEY_SECRET_ID,
      token,
    );

    if (!validateResult) {
      return false;
    }

    if (validateResult.protectedHeader.aud !== `${this.audience}/accessToken`) {
      return false;
    }

    const blockedToken = await this.cacheService.client.get(
      `auth:blocklist:accessToken:${validateResult.protectedHeader.jti}`,
    );

    if (blockedToken) {
      return false;
    }

    const sessionId = validateResult.payload.sessionId;
    if (typeof sessionId !== "string") {
      return false;
    }

    const blockedSession = await this.cacheService.client.get(
      `auth:blocklist:session:${sessionId}`,
    );

    if (blockedSession) {
      return false;
    }

    // Permissions live in the JWT itself (not in the session cache or DB),
    // so they're always fresh from the just-verified payload. Default to {}
    // if the payload doesn't parse — callers treat absent permissions as
    // "no elevated role", which is the safe fallback.
    const payloadParse = AccessTokenPayloadSchema.safeParse(
      validateResult.payload,
    );
    const permissions: Record<string, UserType> = payloadParse.success
      ? payloadParse.data.permissions
      : {};

    const sessionCache = await this.cacheService.client.get(
      `auth:session:${sessionId}`,
    );

    if (sessionCache) {
      const sessionCacheData = tryJson(sessionCache, SessionCacheSchema);
      if (
        sessionCacheData !== INVALID_JSON &&
        sessionCacheData !== INVALID_DATA
      ) {
        return { ...sessionCacheData, permissions };
      }

      // BAD CACHE
    }

    const session = await this.prismaService.session.findUnique({
      where: {
        id: sessionId,
      },
      select: {
        userId: true,
        expiresAt: true,
      },
    });

    if (!session) {
      return false;
    }

    // Logout flips Session.expiresAt to now (we don't hard-delete because
    // RefreshToken keeps an FK to Session for audit). Without this guard, a
    // logged-out token would re-validate the moment its blocklist entry is
    // evicted from the cache.
    if (session.expiresAt <= new Date()) {
      return false;
    }

    const sessionData = {
      sessionId,
      userId: session.userId,
    };

    // Cap the cache TTL at the session's remaining lifetime so we never
    // serve a logged-out session from cache past its expiresAt.
    const remainingSeconds = Math.floor(
      (session.expiresAt.getTime() - Date.now()) / 1000,
    );
    const ttlSeconds = Math.min(15 * 60, Math.max(1, remainingSeconds));

    await this.cacheService.client.set(
      `auth:session:${sessionId}`,
      JSON.stringify(sessionData),
      "EX",
      ttlSeconds,
    );

    return { ...sessionData, permissions };
  }

  async invalidateSession(sessionId: string) {
    // Add session to blocklist (15 minutes = max access token lifetime)
    await this.cacheService.client.set(
      `auth:blocklist:session:${sessionId}`,
      "1",
      "EX",
      15 * 60,
    );

    // Delete session cache
    await this.cacheService.client.del(`auth:session:${sessionId}`);

    // Delete all organization-specific session caches
    const keys = await this.cacheService.client.keys(
      `auth:session:${sessionId}:organization:*`,
    );
    if (keys.length > 0) {
      await this.cacheService.client.del(...keys);
    }
  }

  async validateOrganizationAccess(organizationId: string, userId: string) {
    const memberCache = await this.cacheService.client.get(
      `auth:organizationMember:${organizationId}:${userId}`,
    );

    if (memberCache) {
      try {
        const parsed = JSON.parse(memberCache) as {
          id?: string;
          type?: UserType;
        };

        if (
          typeof parsed.id === "string" &&
          (parsed.type === "ADMIN" || parsed.type === "LIBRARIAN")
        ) {
          return {
            id: parsed.id,
            type: parsed.type,
          } as const;
        }
      } catch {
        // NOTE: Backward compatibility for old cache format (plain memberId string)
        // is handled by falling back to DB lookup.
      }
    }

    const member = await this.prismaService.organizationMember.findUnique({
      where: {
        userId_organizationId: {
          organizationId,
          userId,
        },
      },
      select: {
        id: true,
        type: true,
      },
    });

    if (!member) {
      return false;
    }

    await this.cacheService.client.set(
      `auth:organizationMember:${organizationId}:${userId}`,
      JSON.stringify(member),
      "EX",
      5 * 60, // 5 minutes
    );

    return member;
  }
}
