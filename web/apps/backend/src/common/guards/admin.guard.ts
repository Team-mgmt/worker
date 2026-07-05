import {
  CanActivate,
  ExecutionContext,
  Inject,
  Injectable,
  UnauthorizedException,
} from "@nestjs/common";

import { AccessTokenPayloadSchema } from "@shelfalign/schema/dtos/auth";

import { EnvType, registerEnv } from "@/common/utils/env";
import { KeyService } from "@/providers/keys/keys.service";

@Injectable()
export class AdminGuard implements CanActivate {
  private readonly audience: string;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
    private readonly keyService: KeyService,
  ) {
    if (this.env.NODE_ENV === "production") {
      this.audience = "https://shelfalign.kr";
    } else if (this.env.NODE_ENV === "local") {
      this.audience = `http://localhost:${this.env.PORT}`;
    } else if (this.env.NODE_ENV === "development") {
      this.audience = "https://dev.shelfalign.kr";
    } else {
      this.audience = `https://${this.env.NODE_ENV}.shelfalign.kr`;
    }
  }

  async canActivate(context: ExecutionContext) {
    const request = context.switchToHttp().getRequest();

    if (typeof request.locals === "undefined") {
      request.locals = {};
    }

    if (
      typeof request.locals.organizationId === "undefined" ||
      !request.locals.organizationId
    ) {
      const organizationId =
        "x-organization-id" in request.headers
          ? request.headers["x-organization-id"]
          : undefined;

      if (!organizationId || typeof organizationId !== "string") {
        throw new UnauthorizedException({
          code: "MISSING_ORGANIZATION_ID",
          params: {},
        });
      }

      request.locals.organizationId = organizationId;
    }

    const organizationId: string = request.locals.organizationId;
    if (!organizationId) {
      throw new UnauthorizedException({
        code: "MISSING_ORGANIZATION_ID",
        params: {},
      });
    }

    if ("authorization" in request.headers === false) {
      return false;
    }

    const authHeader = request.headers["authorization"];
    if (typeof authHeader !== "string") {
      return false;
    }

    const [type, token] = authHeader.split(" ");
    if (type !== "Bearer" || !token) {
      return false;
    }

    const validateResult = await (async () => {
      try {
        return await this.keyService.validateToken(
          this.env.AUTH_KEY_SECRET_ID,
          token,
        );
      } catch {
        return undefined;
      }
    })();

    if (!validateResult) {
      return false;
    }

    if (validateResult.protectedHeader.aud !== `${this.audience}/accessToken`) {
      return false;
    }

    const payloadResult = AccessTokenPayloadSchema.safeParse(
      validateResult.payload,
    );
    if (!payloadResult.success) {
      return false;
    }

    if (typeof request.locals === "undefined") {
      request.locals = {};
    }
    request.locals.sessionId = validateResult.payload.sessionId;

    if (organizationId in payloadResult.data.permissions === false) {
      return false;
    }

    return payloadResult.data.permissions[organizationId] === "ADMIN";
  }
}
