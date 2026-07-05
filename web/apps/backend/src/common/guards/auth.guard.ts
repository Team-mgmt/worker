import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  mixin,
  UnauthorizedException,
} from "@nestjs/common";

import { validate as uuidValidate, version as uuidVersion } from "uuid";

import { UserType } from "@shelfalign/database/types";

import { CoreAuthService } from "@/core/auth/auth.service";

/**
 * Validates that a string is a valid UUID.
 * Returns true only for valid UUIDs (nil, v4, or v7 format).
 */
function isValidOrganizationId(id: string): boolean {
  if (!uuidValidate(id)) {
    return false;
  }
  // Accept UUID nil (admin), v4, and v7 (the formats used in this application)
  const version = uuidVersion(id);
  return version === 0 || version === 4 || version === 7;
}

/**
 * Organization context behavior.
 * - `required`: `x-organization-id` must be present and the user must be a member.
 * - `optional`: missing `x-organization-id` is allowed; if provided, it is validated.
 * - `skip`: ignore organization header and membership checks entirely.
 */
type OrganizationMode = "required" | "optional" | "skip";

type AuthOrganizationOptions = {
  organization?: OrganizationMode;
};

type AuthGuardOptions = AuthOrganizationOptions & {
  roles?: UserType[];
};

export function AuthGuard(options?: AuthGuardOptions) {
  @Injectable()
  class AuthGuardMixin implements CanActivate {
    constructor(readonly coreAuthService: CoreAuthService) {}

    async canActivate(context: ExecutionContext) {
      const request = context.switchToHttp().getRequest();
      const organizationMode = options?.organization ?? "required";

      if ("authorization" in request.headers === false) {
        throw new UnauthorizedException({
          code: "MISSING_AUTHORIZATION_HEADER",
          params: {},
        });
      }

      const authHeader = request.headers["authorization"];
      if (typeof authHeader !== "string") {
        throw new UnauthorizedException({
          code: "INVALID_AUTHORIZATION_HEADER",
          params: {},
        });
      }

      const [type, token] = authHeader.split(" ");
      if (type !== "Bearer" || !token) {
        throw new UnauthorizedException({
          code: "INVALID_AUTHORIZATION_HEADER",
          params: {},
        });
      }

      const validateResult =
        await this.coreAuthService.validateAccessToken(token);

      if (!validateResult) {
        throw new UnauthorizedException({
          code: "INVALID_ACCESS_TOKEN",
          params: {},
        });
      }

      if (typeof request.locals === "undefined") {
        request.locals = {};
      }
      request.locals.sessionId = validateResult.sessionId;
      request.locals.userId = validateResult.userId;

      if (organizationMode === "skip") {
        return true;
      }

      const rawOrganizationId =
        "x-organization-id" in request.headers
          ? request.headers["x-organization-id"]
          : undefined;

      if (
        typeof rawOrganizationId !== "undefined" &&
        typeof rawOrganizationId !== "string"
      ) {
        throw new UnauthorizedException({
          code: "INVALID_ORGANIZATION_ID_FORMAT",
          params: {},
        });
      }

      const organizationId =
        typeof rawOrganizationId === "string" && rawOrganizationId.length > 0
          ? rawOrganizationId
          : undefined;

      if (!organizationId) {
        if (organizationMode === "optional") {
          return true;
        }

        throw new UnauthorizedException({
          code: "MISSING_ORGANIZATION_ID",
          params: {},
        });
      }

      if (!isValidOrganizationId(organizationId)) {
        throw new UnauthorizedException({
          code: "INVALID_ORGANIZATION_ID_FORMAT",
          params: {},
        });
      }

      request.locals.organizationId = organizationId;

      const member = await this.coreAuthService.validateOrganizationAccess(
        organizationId,
        validateResult.userId,
      );

      if (!member) {
        throw new UnauthorizedException({
          code: "UNAUTHORIZED_ORGANIZATION",
          params: { organizationId },
        });
      }

      request.locals.memberId = member.id;
      request.locals.memberType = member.type;

      const requiredRoles = options?.roles;
      if (requiredRoles && requiredRoles.length > 0) {
        if (!requiredRoles.includes(member.type)) {
          throw new ForbiddenException({
            code: "INSUFFICIENT_ORGANIZATION_ROLE",
            params: {
              organizationId,
              requiredRoles,
              currentRole: member.type,
            },
          });
        }
      }

      return true;
    }
  }

  return mixin(AuthGuardMixin);
}
