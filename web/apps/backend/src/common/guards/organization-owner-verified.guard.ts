import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
} from "@nestjs/common";

import { OrganizationOwnershipService } from "@/core/organization/organization-ownership.service";
import { PrismaService } from "@/providers/database/prisma.service";

@Injectable()
export class OrganizationOwnerVerifiedGuard implements CanActivate {
  constructor(
    private readonly ownership: OrganizationOwnershipService,
    private readonly prisma: PrismaService,
  ) {}

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    const request = ctx.switchToHttp().getRequest();
    const organizationId: string | undefined = request.locals?.organizationId;
    if (!organizationId) {
      throw new ForbiddenException({
        code: "NO_ORGANIZATION_CONTEXT",
        params: {},
      });
    }

    const owners = await this.ownership.getOwners(organizationId);
    if (owners.length === 0) {
      throw new ForbiddenException({
        code: "SCAN_DISABLED_UNVERIFIED_OWNER",
        params: {},
      });
    }

    const count = await this.prisma.providerConnection.count({
      where: {
        userId: { in: owners.map((o) => o.userId) },
        emailVerifiedAt: { not: null },
      },
    });
    if (count === 0) {
      throw new ForbiddenException({
        code: "SCAN_DISABLED_UNVERIFIED_OWNER",
        params: {},
      });
    }

    return true;
  }
}
