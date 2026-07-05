import crypto, { randomUUID } from "node:crypto";

import {
  BadRequestException,
  ConflictException,
  HttpException,
  Inject,
  Injectable,
  InternalServerErrorException,
  Logger,
  NotFoundException,
  UnauthorizedException,
} from "@nestjs/common";

import argon2 from "argon2";
import { v7 as uuidv7 } from "uuid";
import z from "zod";

import { Prisma, Provider } from "@shelfalign/database/client";
import { UserType } from "@shelfalign/database/types";
import {
  BaseProfile,
  ProviderConfigSchema,
} from "@shelfalign/schema/auth/providers/base";
import { LocalProviderDataSchema } from "@shelfalign/schema/auth/providers/local";
import { StateCache, StateCacheSchema } from "@shelfalign/schema/cache/state";
import {
  GetSessionDataSchema,
  RefreshTokenPayloadSchema,
} from "@shelfalign/schema/dtos/auth";
import type { MeResponse } from "@shelfalign/schema/dtos/auth/me";
import { NAMESPACES, RELATIONS } from "@shelfalign/schema/permission";

import { ADMIN_ORGANIZATION_ID } from "@/common/constants";
import { RedirectError } from "@/common/filters/redirect.filter";
import { EnvType, registerEnv } from "@/common/utils/env";
import { createDigest } from "@/common/utils/error";
import { INVALID_DATA, INVALID_JSON, tryJson } from "@/common/utils/zod";
import { CoreAuthService } from "@/core/auth/auth.service";
import { BaseProvider } from "@/core/auth/providers/base.provider";
import { GoogleProvider } from "@/core/auth/providers/google.provider";
import { MicrosoftProvider } from "@/core/auth/providers/microsoft.provider";
import { EmailTokenService } from "@/core/auth/tokens/email-token.service";
import { MailService } from "@/core/mail/mail.service";
import { renderResetPasswordTemplate } from "@/core/mail/templates/reset-password.template";
import { renderVerifyEmailTemplate } from "@/core/mail/templates/verify-email.template";
import { OrganizationOwnershipService } from "@/core/organization/organization-ownership.service";
import { CacheService } from "@/providers/cache/cache.service";
import { PrismaService } from "@/providers/database/prisma.service";
import { KeyService } from "@/providers/keys/keys.service";
import { S3Service } from "@/providers/s3/s3.service";

import { SignInRequestDto, SignUpRequestDto } from "./auth.schema";

const REFRESH_TOKEN_ROTATION_GRACE_MS = 10_000;

@Injectable()
export class AuthService {
  private readonly logger = new Logger(AuthService.name);

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
    private readonly prismaService: PrismaService,
    private readonly cacheService: CacheService,
    private readonly keyService: KeyService,
    private readonly coreAuthService: CoreAuthService,
    private readonly microsoftProvider: MicrosoftProvider,
    private readonly googleProvider: GoogleProvider,
    private readonly ownershipService: OrganizationOwnershipService,
    private readonly emailTokenService: EmailTokenService,
    private readonly mailService: MailService,
    private readonly s3Service: S3Service,
  ) {}

  async signIn(data: SignInRequestDto) {
    const localProvider = await this.prismaService.provider.findFirst({
      where: {
        name: "local",
        deletedAt: null,
      },
    });

    if (!localProvider) {
      const digest = createDigest(this.logger, "Local provider not found");
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const providerConnection =
      await this.prismaService.providerConnection.findUnique({
        where: {
          providerId_providerUniqueId: {
            providerId: localProvider.id,
            providerUniqueId: data.email,
          },
        },
        include: {
          user: {
            include: {
              organizations: true,
            },
          },
        },
      });

    if (!providerConnection) {
      throw new BadRequestException({
        code: "INVALID_CREDENTIALS",
        params: { email: data.email },
      });
    }

    const user = providerConnection.user;

    const providerDataResult = LocalProviderDataSchema.safeParse(
      providerConnection.data,
    );

    if (!providerDataResult.success) {
      const digest = createDigest(
        this.logger,
        `Failed to parse provider data for user ${user.id}: ${providerDataResult.error.message}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const isPasswordValid = await argon2.verify(
      providerDataResult.data.password,
      data.password,
    );

    if (!isPasswordValid) {
      throw new BadRequestException({
        code: "INVALID_CREDENTIALS",
        params: { email: data.email },
      });
    }

    const primaryConnection =
      await this.prismaService.providerConnection.findUnique({
        where: {
          userId_primary: {
            userId: providerConnection.userId,
            primary: true,
          },
        },
      });

    if (!primaryConnection) {
      const digest = createDigest(
        this.logger,
        `Primary provider connection not found for user ${user.id}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const session = await this.prismaService.session.create({
      data: {
        id: uuidv7(),
        userId: user.id,
        providerConnectionId: providerConnection.id,
        metadata: {},
        expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000), // 30 days
      },
    });

    // Include permissions for ALL user's organizations in the access token
    const permissions: Record<string, UserType> = {};
    for (const org of user.organizations) {
      permissions[org.organizationId] = org.type;
    }

    const accessToken = await this.coreAuthService.createAccessToken(
      session.id,
      permissions,
    );
    const refreshToken = await this.coreAuthService.createRefreshToken(
      session.id,
    );

    return {
      accessToken,
      refreshToken,
      organizations: user.organizations,
    };
  }

  async signInWithProvider(
    requestIp: string,
    userAgent: string,
    initiatedFrom: StateCache["initiatedFrom"],
    providerId: string,
  ) {
    const provider = await this.prismaService.provider.findUnique({
      where: {
        id: providerId,
        deletedAt: null,
      },
    });

    if (!provider) {
      throw new BadRequestException({
        code: "UNKNOWN_PROVIDER",
        params: { providerId },
      });
    }

    const providerConfigResult = ProviderConfigSchema.safeParse(
      provider.config,
    );
    if (!providerConfigResult.success) {
      const digest = createDigest(
        this.logger,
        `Failed to parse provider config for provider ${provider.id}: ${providerConfigResult.error.message}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const providerConfig = providerConfigResult.data;

    let authProvider: BaseProvider | null = null;
    if (providerConfig.type === "microsoft") {
      authProvider = this.microsoftProvider;
    }

    if (providerConfig.type === "google") {
      authProvider = this.googleProvider;
    }

    if (!authProvider) {
      throw new InternalServerErrorException({
        code: "PROVIDER_NOT_IMPLEMENTED",
        params: { providerType: providerConfig.type, providerId },
      });
    }

    const { url, codeVerifier, state } = await authProvider.getAuthorizeUrl(
      providerId,
      providerConfig,
    );

    const session = uuidv7();

    await this.cacheService.client.set(
      `auth:state:${state}`,
      JSON.stringify({
        codeVerifier,
        requestIp,
        userAgent,
        oauthSession: session,
        initiatedFrom,
        provider: providerId,
      } satisfies StateCache),
      "EX",
      5 * 60,
    );

    return { url, session };
  }

  async signInWithProviderCallback(
    requestIp: string,
    userAgent: string,
    sessionId: string,
    code: string,
    state: string,
  ) {
    const sessionText = await this.cacheService.client.get(
      `auth:state:${state}`,
    );
    if (!sessionText) {
      throw new RedirectError("/auth/signin?error=SESSION_EXPIRED");
    }

    const session = tryJson(sessionText, StateCacheSchema);
    if (session === INVALID_DATA || session === INVALID_JSON) {
      const digest = createDigest(
        this.logger,
        `Invalid session data "${sessionText}"`,
      );
      throw new RedirectError(
        `/auth/signin?error=INTERNAL_ERROR&digest=${digest}`,
      );
    }

    if (session.oauthSession !== sessionId) {
      throw new RedirectError(
        "/auth/signin?error=SESSION_MISMATCH",
        session.initiatedFrom,
      );
    }

    if (session.userAgent !== userAgent) {
      throw new RedirectError(
        "/auth/signin?error=USER_AGENT_MISMATCH",
        session.initiatedFrom,
      );
    }

    if (session.requestIp !== requestIp) {
      throw new RedirectError(
        "/auth/signin?error=REQUEST_IP_MISMATCH",
        session.initiatedFrom,
      );
    }

    const provider = await this.prismaService.provider.findUnique({
      where: {
        id: session.provider,
        deletedAt: null,
      },
    });

    if (!provider) {
      throw new RedirectError(
        `/auth/signin?error=UNKNOWN_PROVIDER&provider=${session.provider}`,
        session.initiatedFrom,
      );
    }

    const providerConfigResult = ProviderConfigSchema.safeParse(
      provider.config,
    );
    if (!providerConfigResult.success) {
      const digest = createDigest(
        this.logger,
        `Failed to parse provider config for provider ${provider.id}: ${providerConfigResult.error.message}`,
      );
      throw new RedirectError(
        `/auth/signin?error=INTERNAL_ERROR&digest=${digest}`,
        session.initiatedFrom,
      );
    }

    const providerConfig = providerConfigResult.data;

    let authProvider: BaseProvider | null = null;
    if (providerConfig.type === "microsoft") {
      authProvider = this.microsoftProvider;
    }

    if (providerConfig.type === "google") {
      authProvider = this.googleProvider;
    }

    if (!authProvider) {
      const digest = createDigest(
        this.logger,
        `Unsupported provider type ${providerConfig.type}`,
      );
      throw new RedirectError(
        `/auth/signin?error=INTERNAL_ERROR&digest=${digest}`,
        session.initiatedFrom,
      );
    }

    const authResult = await authProvider.getToken(
      provider.id,
      providerConfig,
      code,
      session.codeVerifier,
    );

    if (!authResult.result) {
      throw new RedirectError(
        `/auth/signin?error=INTERNAL_ERROR&digest=${authResult.digest}`,
        session.initiatedFrom,
      );
    }

    const profileResult = await authProvider.getProfile(authResult.token);

    if (!profileResult.result) {
      throw new RedirectError(
        `/auth/signin?error=INTERNAL_ERROR&digest=${profileResult.digest}`,
        session.initiatedFrom,
      );
    }

    const profile = profileResult.profile;
    const baseProfileResult = await authProvider.getBaseProfile(profile);

    if (!baseProfileResult.result) {
      throw new RedirectError(
        `/auth/signin?error=INTERNAL_ERROR&digest=${baseProfileResult.digest}`,
        session.initiatedFrom,
      );
    }

    const baseProfile = baseProfileResult.profile;

    const existingConnection =
      await this.prismaService.providerConnection.findUnique({
        where: {
          providerId_providerUniqueId: {
            providerId: provider.id,
            providerUniqueId: baseProfile.id,
          },
        },
        include: {
          user: {
            include: {
              organizations: {
                include: {
                  organization: true,
                },
              },
            },
          },
        },
      });

    let user: NonNullable<typeof existingConnection>["user"];
    let connectionId: string;

    if (existingConnection) {
      await this.prismaService.providerConnection.update({
        where: {
          id: existingConnection.id,
        },
        data: {
          email: baseProfile.email,
          data: profile as Prisma.JsonObject,
        },
      });

      user = existingConnection.user;
      connectionId = existingConnection.id;
    } else {
      const newUserResult = await this.signUpWithProvider(
        provider,
        baseProfile,
        profile,
      );
      user = newUserResult.user;
      connectionId = newUserResult.connectionId;
    }

    const primaryConnection =
      await this.prismaService.providerConnection.findUnique({
        where: {
          userId_primary: {
            userId: user.id,
            primary: true,
          },
        },
      });

    if (!primaryConnection) {
      const digest = createDigest(
        this.logger,
        `Primary provider connection not found for user ${user.id}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const newSession = await this.prismaService.session.create({
      data: {
        id: uuidv7(),
        userId: user.id,
        providerConnectionId: connectionId,
        metadata: {},
        expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000), // 30 days
      },
    });

    // Include permissions for ALL user's organizations in the access token
    const permissions: Record<string, UserType> = {};
    for (const org of user.organizations) {
      permissions[org.organizationId] = org.type;
    }

    const accessToken = await this.coreAuthService.createAccessToken(
      newSession.id,
      permissions,
    );
    const refreshToken = await this.coreAuthService.createRefreshToken(
      newSession.id,
    );

    return {
      initiatedFrom: session.initiatedFrom,
      accessToken,
      refreshToken,
      organizations: user.organizations,
    };
  }

  async signUp(data: SignUpRequestDto) {
    const localProvider = await this.prismaService.provider.findFirst({
      where: {
        name: "local",
        deletedAt: null,
      },
    });

    if (!localProvider) {
      const digest = createDigest(this.logger, "Local provider not found");
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const existingConnection =
      await this.prismaService.providerConnection.findFirst({
        where: {
          providerId: localProvider.id,
          providerUniqueId: data.email,
        },
      });

    if (existingConnection) {
      throw new ConflictException({
        code: "ACCOUNT_EXISTS",
        params: { email: data.email },
      });
    }

    const existingNicknameUser = await this.prismaService.user.findUnique({
      where: { nickname: data.nickname },
    });

    if (existingNicknameUser) {
      throw new ConflictException({
        code: "NICKNAME_TAKEN",
        params: { nickname: data.nickname },
      });
    }

    const userId = uuidv7();
    const connectionId = uuidv7();
    const hash = await argon2.hash(data.password);
    let permissions: Record<string, UserType> = {};

    if (data.type === "LIBRARIAN" || data.type === "ADMIN") {
      const organization = await this.prismaService.organization.create({
        data: {
          id: uuidv7(),
          name: `${data.name}`,
        },
      });

      const memberId = uuidv7();

      await this.prismaService.user.create({
        data: {
          id: userId,
          name: data.name,
          phone: data.phone,
          nickname: data.nickname,
          connections: {
            create: {
              id: connectionId,
              email: data.email,
              providerId: localProvider.id,
              providerUniqueId: data.email,
              data: {
                password: hash,
              } satisfies z.infer<typeof LocalProviderDataSchema>,
              primary: true,
            },
          },
          organizations: {
            create: {
              id: memberId,
              organizationId: organization.id,
              name: data.name,
              type: data.type,
            },
          },
        },
      });

      const adminMemberSetId = uuidv7();

      await this.prismaService.permissionTuple.create({
        data: {
          id: adminMemberSetId,
          label: "Organization Creator",
          organizationId: organization.id,
          namespace: NAMESPACES.memberSet,
          objectId: adminMemberSetId,
          relationId: RELATIONS.memberSetMember,
          memberId,
        },
      });

      await this.prismaService.permissionTuple.create({
        data: {
          id: uuidv7(),
          organizationId: organization.id,
          label: "Organization Admin",
          namespace: NAMESPACES.organization,
          objectId: organization.id,
          relationId: RELATIONS.admin,
          targetId: adminMemberSetId,
        },
      });

      await this.ownershipService.grantOwner(memberId, organization.id);

      permissions = { [organization.id]: data.type };
    } else {
      await this.prismaService.user.create({
        data: {
          id: userId,
          name: data.name,
          phone: data.phone,
          nickname: data.nickname,
          connections: {
            create: {
              id: connectionId,
              email: data.email,
              providerId: localProvider.id,
              providerUniqueId: data.email,
              data: {
                password: hash,
              } satisfies z.infer<typeof LocalProviderDataSchema>,
              primary: true,
            },
          },
        },
      });
    }

    const session = await this.prismaService.session.create({
      data: {
        id: uuidv7(),
        userId,
        providerConnectionId: connectionId,
        metadata: {},
        expiresAt: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000), // 30 days
      },
    });

    try {
      await this.sendVerificationEmail(session.id);
    } catch (err) {
      this.logger.warn(`failed to send verify email: ${String(err)}`);
    }

    const accessToken = await this.coreAuthService.createAccessToken(
      session.id,
      permissions,
    );
    const refreshToken = await this.coreAuthService.createRefreshToken(
      session.id,
    );

    return {
      accessToken,
      refreshToken,
    };
  }

  async getTargetOrganization(
    provider: Provider,
    email: string,
  ): Promise<{ organizationId: string; memberType: UserType } | null> {
    // Admin provider always targets admin organization
    if (provider.id === ADMIN_ORGANIZATION_ID) {
      return { organizationId: ADMIN_ORGANIZATION_ID, memberType: "ADMIN" };
    }

    // Check for pending invitations
    const invitation = await this.prismaService.invitation.findFirst({
      where: {
        email,
        acceptedAt: null,
        revokedAt: null,
      },
      orderBy: { createdAt: "desc" },
    });

    if (invitation) {
      // Mark invitation as accepted
      await this.prismaService.invitation.update({
        where: { id: invitation.id },
        data: { acceptedAt: new Date() },
      });
      return {
        organizationId: invitation.organizationId,
        memberType: "LIBRARIAN",
      };
    }

    // TODO: handle SAML providers - they may define target organization via provider config

    // No target organization found, will create new one
    return null;
  }

  async signUpWithProvider(
    provider: Provider,
    baseProfile: BaseProfile,
    profile: unknown,
  ) {
    const userId = uuidv7();
    const connectionId = uuidv7();
    const targetOrg = await this.getTargetOrganization(
      provider,
      baseProfile.email,
    );

    let organizationId: string;
    let memberType: UserType = "ADMIN";
    let createdNewOrganization = false;

    if (targetOrg) {
      organizationId = targetOrg.organizationId;
      memberType = targetOrg.memberType;
    } else {
      const newOrganization = await this.prismaService.organization.create({
        data: {
          id: uuidv7(),
          name: `${baseProfile.name}님의 조직`,
        },
      });
      organizationId = newOrganization.id;
      createdNewOrganization = true;
    }

    const newUser = await this.prismaService.user.create({
      data: {
        id: userId,
        name: baseProfile.name,
        connections: {
          create: {
            id: connectionId,
            email: baseProfile.email,
            providerId: provider.id,
            providerUniqueId: baseProfile.id,
            data: profile as Prisma.JsonObject,
            primary: true,
            // OAuth providers (Google, Microsoft) verify the email before
            // issuing an id token, so a provider-linked connection can be
            // treated as verified at link time.
            emailVerifiedAt: new Date(),
          },
        },
        organizations: {
          create: {
            id: uuidv7(),
            organizationId,
            name: baseProfile.name,
            type: memberType,
          },
        },
      },
      include: {
        organizations: {
          include: {
            organization: true,
          },
        },
      },
    });

    // For freshly created orgs, grant ownership to the new member so the
    // OwnerVerifiedRule has an owner to resolve. Invitation-backed
    // onboarding inherits ownership from the invitation's existing org.
    if (createdNewOrganization) {
      const newMember = newUser.organizations.find(
        (m) => m.organizationId === organizationId,
      );
      if (newMember) {
        await this.ownershipService.grantOwner(newMember.id, organizationId);
      }
    }

    return { user: newUser, connectionId };
  }

  async refreshToken(token: string) {
    const validateResult = await this.keyService.validateToken(
      this.env.AUTH_KEY_SECRET_ID,
      token,
    );

    if (
      !("jti" in validateResult.protectedHeader) ||
      !validateResult.protectedHeader.jti
    ) {
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: {},
      });
    }

    const blocked = await this.cacheService.client.get(
      `auth:blocklist:refreshToken:${validateResult.protectedHeader.jti}`,
    );

    if (blocked) {
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: {},
      });
    }

    const tokenHash = crypto.createHash("sha256").update(token).digest("hex");

    const storedToken = await this.prismaService.refreshToken.findUnique({
      where: {
        tokenHash,
      },
      include: {
        session: true,
      },
    });

    if (!storedToken) {
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: {},
      });
    }

    // Grace window for rotated tokens: if a client sends the previous refresh
    // cookie moments after another concurrent request already rotated it
    // (common when multiple requests fan out after a 15m access-token expiry),
    // mint a fresh access token for the same session without rotating the
    // cookie again. Outside the window, or for non-rotation revocations
    // (logout/password reset), reject as before.
    //
    // Crucially, only grant grace when the family still has an active
    // successor. Password-reset/logout re-revokes the successor with a
    // different reason, which makes the whole family effectively dead even
    // though this (older) row still carries revokedReason "TOKEN_ROTATED".
    const isWithinRotationWindow =
      storedToken.revokedAt !== null &&
      storedToken.revokedReason === "TOKEN_ROTATED" &&
      Date.now() - storedToken.revokedAt.getTime() <
        REFRESH_TOKEN_ROTATION_GRACE_MS;

    const hasActiveSuccessor = isWithinRotationWindow
      ? (await this.prismaService.refreshToken.findFirst({
          where: {
            familyId: storedToken.familyId,
            id: { not: storedToken.id },
            revokedAt: null,
          },
          select: { id: true },
        })) !== null
      : false;

    const isWithinRotationGrace = isWithinRotationWindow && hasActiveSuccessor;

    if (storedToken.revokedAt && !isWithinRotationGrace) {
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: {},
      });
    }

    if (storedToken.expiresAt < new Date()) {
      throw new BadRequestException({
        code: "TOKEN_EXPIRED",
        params: {},
      });
    }

    const payloadResult = RefreshTokenPayloadSchema.safeParse(
      validateResult.payload,
    );

    if (!payloadResult.success) {
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: {},
      });
    }

    if (storedToken.session.userId !== validateResult.protectedHeader.sub) {
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: {},
      });
    }

    // Get all user's organizations for permissions
    const members = await this.prismaService.organizationMember.findMany({
      where: {
        userId: storedToken.session.userId,
      },
    });

    // Include permissions for ALL user's organizations in the access token
    const permissions: Record<string, UserType> = {};
    for (const member of members) {
      permissions[member.organizationId] = member.type;
    }

    const accessToken = await this.coreAuthService.createAccessToken(
      storedToken.sessionId,
      permissions,
    );

    if (isWithinRotationGrace) {
      return {
        accessToken,
        refreshToken: null,
      };
    }

    const refreshToken = await this.coreAuthService.createRefreshToken(
      storedToken.sessionId,
      storedToken.id,
    );

    return {
      accessToken,
      refreshToken,
    };
  }

  async deleteSession(sessionId: string) {
    const session = await this.prismaService.session.findUnique({
      where: { id: sessionId },
    });

    if (!session) {
      throw new UnauthorizedException({
        code: "SESSION_NOT_FOUND",
        params: {},
      });
    }

    // Revoke all refresh tokens for this session
    await this.prismaService.refreshToken.updateMany({
      where: {
        sessionId,
        revokedAt: null,
      },
      data: {
        revokedAt: new Date(),
        revokedReason: "LOGOUT",
      },
    });

    // Expire the session so subsequent validations reject it. We don't
    // hard-delete because revoked RefreshTokens retain a FK to Session for
    // audit; deletion would either violate the FK or require dropping the
    // token history.
    await this.prismaService.session.update({
      where: { id: sessionId },
      data: { expiresAt: new Date() },
    });

    // Invalidate session cache (event-driven invalidation)
    await this.coreAuthService.invalidateSession(sessionId);
  }

  async getSession(sessionId: string, organizationId?: string) {
    const cacheSession = await this.cacheService.client.get(
      `auth:session:${sessionId}:organization:${organizationId}`,
    );
    if (cacheSession) {
      const parsed = tryJson(cacheSession, GetSessionDataSchema);
      if (parsed !== INVALID_DATA && parsed !== INVALID_JSON) {
        return parsed;
      }
    }

    const session = await this.prismaService.session.findUnique({
      where: {
        id: sessionId,
      },
      select: {
        id: true,
        createdAt: true,
        expiresAt: true,
        metadata: true,
        user: {
          select: {
            id: true,
            name: true,
            nickname: true,
          },
        },
      },
    });

    if (!session) {
      throw new UnauthorizedException({
        code: "SESSION_NOT_FOUND",
        params: {},
      });
    }

    if (organizationId) {
      const member = await this.prismaService.organizationMember.findUnique({
        where: {
          userId_organizationId: {
            userId: session.user.id,
            organizationId,
          },
        },
        select: {
          id: true,
          name: true,
          type: true,
          organizationId: true,
        },
      });

      if (!member) {
        throw new UnauthorizedException({
          code: "UNAUTHORIZED_ORGANIZATION",
          params: { organizationId },
        });
      }
    }

    const membership = await this.prismaService.organizationMember.findMany({
      where: {
        userId: session.user.id,
      },
      omit: {
        userId: true,
      },
    });

    const primaryConnection =
      await this.prismaService.providerConnection.findUnique({
        where: {
          userId_primary: {
            userId: session.user.id,
            primary: true,
          },
        },
      });

    if (!primaryConnection) {
      const digest = createDigest(
        this.logger,
        `Primary provider connection not found for user ${session.user.id}`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const result = {
      id: session.id,
      createdAt: session.createdAt,
      expiresAt: session.expiresAt,
      user: {
        id: session.user.id,
        name: session.user.name,
        nickname: session.user.nickname,
        primaryEmail: primaryConnection.email,
      },
      membership,
    };

    await this.cacheService.client.set(
      `auth:session:${sessionId}:organization:${organizationId}`,
      JSON.stringify({
        ...result,
        createdAt: result.createdAt.toISOString(),
        expiresAt: result.expiresAt.toISOString(),
      }),
      "EX",
      5 * 60,
    );

    return result;
  }

  async getOrganizationsBySessionId(sessionId: string) {
    const session = await this.prismaService.session.findUnique({
      where: { id: sessionId, expiresAt: { gt: new Date() } },
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

    const organizations = await this.prismaService.organization.findMany({
      where: {
        members: {
          some: {
            userId: session.userId,
          },
        },
      },
      include: {
        members: {
          where: {
            userId: session.userId,
          },
        },
      },
    });

    return organizations.filter((org) => org.id !== ADMIN_ORGANIZATION_ID);
  }

  async getMe(sessionId: string): Promise<MeResponse["data"]> {
    const session = await this.prismaService.session.findUnique({
      where: { id: sessionId },
      select: { userId: true },
    });

    if (!session) {
      throw new UnauthorizedException({
        code: "SESSION_NOT_FOUND",
        params: {},
      });
    }

    const user = await this.prismaService.user.findUniqueOrThrow({
      where: { id: session.userId },
      include: {
        connections: true,
        organizations: {
          include: { organization: true },
        },
      },
    });

    const verifiedAt = user.connections.reduce<Date | null>((acc, c) => {
      if (!c.emailVerifiedAt) return acc;
      if (!acc || c.emailVerifiedAt < acc) return c.emailVerifiedAt;
      return acc;
    }, null);
    const primaryConnection =
      user.connections.find((c) => c.primary) ?? user.connections[0];
    const userEmail = primaryConnection?.email ?? "";

    const organizations = await Promise.all(
      user.organizations.map(async (member) => {
        const owners = await this.ownershipService.getOwners(
          member.organizationId,
        );
        const ownerUserIds = Array.from(new Set(owners.map((o) => o.userId)));
        const ownerVerifiedCount =
          ownerUserIds.length > 0
            ? await this.prismaService.providerConnection.count({
                where: {
                  userId: { in: ownerUserIds },
                  emailVerifiedAt: { not: null },
                },
              })
            : 0;
        const verified = ownerVerifiedCount > 0;
        const isOwner = owners.some((o) => o.id === member.id);
        return {
          id: member.organization.id,
          name: member.organization.name,
          type: member.type,
          membershipId: member.id,
          verificationStatus: verified
            ? ("VERIFIED" as const)
            : ("UNVERIFIED" as const),
          isOwner,
        };
      }),
    );

    const pictureUrl = user.picture
      ? await this.s3Service.generatePresignedDownloadUrl(user.picture)
      : null;

    return {
      user: {
        id: user.id,
        name: user.name,
        nickname: user.nickname,
        email: userEmail,
        phone: user.phone,
        pictureUrl,
        emailVerifiedAt: verifiedAt ? verifiedAt.toISOString() : null,
      },
      organizations,
    };
  }

  async setPicture(
    sessionId: string,
    picture: string | null,
  ): Promise<{ pictureUrl: string | null }> {
    const session = await this.prismaService.session.findUnique({
      where: { id: sessionId },
      select: { userId: true },
    });
    if (!session) {
      throw new UnauthorizedException({
        code: "SESSION_NOT_FOUND",
        params: {},
      });
    }

    // Validate that the S3 key actually belongs to an UploadFile this user
    // created — otherwise a leaked presigned URL would let anyone attach
    // any image to their profile.
    if (picture) {
      const uploadFile = await this.prismaService.uploadFile.findUnique({
        where: { key: picture },
        select: { createdById: true },
      });
      if (!uploadFile || uploadFile.createdById !== session.userId) {
        throw new BadRequestException({
          code: "INVALID_PICTURE",
          params: {},
        });
      }
    }

    await this.prismaService.user.update({
      where: { id: session.userId },
      data: { picture },
    });

    return {
      pictureUrl: picture
        ? await this.s3Service.generatePresignedDownloadUrl(picture)
        : null,
    };
  }

  async checkNicknameAvailable(nickname: string): Promise<boolean> {
    const existing = await this.prismaService.user.findUnique({
      where: { nickname },
      select: { id: true },
    });
    return existing === null;
  }

  async setNickname(sessionId: string, nickname: string): Promise<void> {
    const session = await this.prismaService.session.findUnique({
      where: { id: sessionId },
      select: { userId: true },
    });

    if (!session) {
      throw new UnauthorizedException({
        code: "SESSION_NOT_FOUND",
        params: {},
      });
    }

    const existing = await this.prismaService.user.findFirst({
      where: { nickname, NOT: { id: session.userId } },
      select: { id: true },
    });

    if (existing) {
      throw new ConflictException({
        code: "NICKNAME_TAKEN",
        params: { nickname },
      });
    }

    await this.prismaService.user.update({
      where: { id: session.userId },
      data: { nickname },
    });
  }

  async setPhone(sessionId: string, phone: string | null): Promise<void> {
    const session = await this.prismaService.session.findUnique({
      where: { id: sessionId },
      select: { userId: true },
    });

    if (!session) {
      throw new UnauthorizedException({
        code: "SESSION_NOT_FOUND",
        params: {},
      });
    }

    await this.prismaService.user.update({
      where: { id: session.userId },
      data: { phone },
    });
  }

  async sendVerificationEmail(sessionId: string): Promise<void> {
    const session = await this.prismaService.session.findUnique({
      where: { id: sessionId },
      select: { userId: true },
    });

    if (!session) {
      throw new UnauthorizedException({
        code: "SESSION_NOT_FOUND",
        params: {},
      });
    }

    const providerConnection =
      await this.prismaService.providerConnection.findFirst({
        where: {
          userId: session.userId,
          provider: { name: "local" },
        },
      });

    if (!providerConnection) {
      throw new NotFoundException({
        code: "NO_LOCAL_PROVIDER",
        params: {},
      });
    }

    if (providerConnection.emailVerifiedAt) {
      throw new BadRequestException({
        code: "EMAIL_ALREADY_VERIFIED",
        params: {},
      });
    }

    // Atomic 60s resend throttle via cache SETNX. A check-then-create
    // pattern has a TOCTOU race where two concurrent requests can both
    // pass the check and both send mail. SETNX gives single-winner
    // semantics within the TTL window.
    const rateLimitKey = `auth:verify-email:ratelimit:${providerConnection.id}`;
    const acquired = await this.cacheService.client.set(
      rateLimitKey,
      "1",
      "EX",
      60,
      "NX",
    );
    if (acquired !== "OK") {
      throw new HttpException({ code: "RATE_LIMITED", params: {} }, 429);
    }

    const { raw, hash } = this.emailTokenService.generate();

    await this.prismaService.emailVerificationToken.create({
      data: {
        id: randomUUID(),
        providerConnectionId: providerConnection.id,
        tokenHash: hash,
        email: providerConnection.email,
        expiresAt: new Date(Date.now() + 24 * 60 * 60_000),
      },
    });

    const user = await this.prismaService.user.findUniqueOrThrow({
      where: { id: session.userId },
    });

    const frontendUrl = this.env.FRONTEND_URL;
    const verifyUrl = `${frontendUrl}/auth/verify-email/confirm?token=${raw}`;

    const rendered = renderVerifyEmailTemplate({
      name: user.name,
      verifyUrl,
      expiresInHours: 24,
    });

    await this.mailService.send(
      {
        to: providerConnection.email,
        ...rendered,
      },
      { kind: "VERIFY_EMAIL", userId: session.userId },
    );
  }

  async confirmVerificationEmail(rawToken: string): Promise<void> {
    const tokenHash = this.emailTokenService.hash(rawToken);
    const record = await this.prismaService.emailVerificationToken.findUnique({
      where: { tokenHash },
    });

    if (!record || record.consumedAt || record.expiresAt < new Date()) {
      throw new BadRequestException({
        code: "TOKEN_INVALID",
        params: {},
      });
    }

    await this.prismaService.$transaction(async (tx) => {
      // Atomic consumption guarded by the validity predicates so concurrent
      // confirm requests with the same token cannot both succeed.
      const consumed = await tx.emailVerificationToken.updateMany({
        where: {
          id: record.id,
          consumedAt: null,
          expiresAt: { gt: new Date() },
        },
        data: { consumedAt: new Date() },
      });
      if (consumed.count === 0) {
        throw new BadRequestException({
          code: "TOKEN_INVALID",
          params: {},
        });
      }
      // Only stamp emailVerifiedAt on first verification. Later still-valid
      // tokens for the same connection must not overwrite the original
      // timestamp, or the field degrades from "when verified" to "last token
      // redeemed".
      await tx.providerConnection.updateMany({
        where: {
          id: record.providerConnectionId,
          emailVerifiedAt: null,
        },
        data: { emailVerifiedAt: new Date() },
      });
    });
  }

  async sendPasswordReset(email: string): Promise<void> {
    const providerConnection =
      await this.prismaService.providerConnection.findFirst({
        where: {
          email,
          provider: { name: "local" },
        },
        include: { user: true },
      });

    if (!providerConnection) {
      return;
    }

    const { raw, hash } = this.emailTokenService.generate();

    await this.prismaService.passwordResetToken.create({
      data: {
        id: randomUUID(),
        providerConnectionId: providerConnection.id,
        tokenHash: hash,
        expiresAt: new Date(Date.now() + 60 * 60_000),
      },
    });

    const frontendUrl = this.env.FRONTEND_URL;
    const resetUrl = `${frontendUrl}/auth/reset-password?token=${raw}`;

    const rendered = renderResetPasswordTemplate({
      name: providerConnection.user.name,
      resetUrl,
      expiresInMinutes: 60,
    });

    // Swallow mail failures so the response shape is identical to the
    // unknown-email branch. Otherwise SES outages would leak account
    // existence via HTTP error vs. 200 responses. MailService.send logs
    // the failure at error level, so no extra logging is needed here.
    try {
      await this.mailService.send(
        {
          to: providerConnection.email,
          ...rendered,
        },
        { kind: "RESET_PASSWORD", userId: providerConnection.user.id },
      );
    } catch {
      // intentionally swallowed for enumeration safety
    }
  }

  async resetPassword(rawToken: string, newPassword: string): Promise<void> {
    const tokenHash = this.emailTokenService.hash(rawToken);
    const record = await this.prismaService.passwordResetToken.findUnique({
      where: { tokenHash },
      include: { providerConnection: true },
    });

    if (!record || record.consumedAt || record.expiresAt < new Date()) {
      throw new BadRequestException({
        code: "TOKEN_INVALID",
        params: {},
      });
    }

    const passwordHash = await argon2.hash(newPassword);
    const providerConnection = record.providerConnection;
    const existingData =
      providerConnection.data && typeof providerConnection.data === "object"
        ? (providerConnection.data as Record<string, unknown>)
        : {};
    const nextData: Prisma.JsonObject = {
      ...existingData,
      password: passwordHash,
    } as Prisma.JsonObject;

    await this.prismaService.$transaction(async (tx) => {
      // Atomic consumption: the updateMany will only affect the row if it
      // is still unconsumed and unexpired, so concurrent reset requests
      // with the same token cannot both succeed.
      const consumed = await tx.passwordResetToken.updateMany({
        where: {
          id: record.id,
          consumedAt: null,
          expiresAt: { gt: new Date() },
        },
        data: { consumedAt: new Date() },
      });
      if (consumed.count === 0) {
        throw new BadRequestException({
          code: "TOKEN_INVALID",
          params: {},
        });
      }
      await tx.providerConnection.update({
        where: { id: providerConnection.id },
        data: { data: nextData },
      });
      await tx.refreshToken.updateMany({
        where: {
          session: { providerConnectionId: providerConnection.id },
          revokedAt: null,
        },
        data: {
          revokedAt: new Date(),
          revokedReason: "PASSWORD_RESET",
        },
      });
    });
  }
}
