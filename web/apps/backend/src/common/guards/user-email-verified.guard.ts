import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
} from "@nestjs/common";

import { PrismaService } from "@/providers/database/prisma.service";

@Injectable()
export class UserEmailVerifiedGuard implements CanActivate {
  constructor(private readonly prisma: PrismaService) {}

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    const request = ctx.switchToHttp().getRequest();
    const userId: string | undefined = request.locals?.userId;
    if (!userId) {
      throw new ForbiddenException({
        code: "NO_USER_CONTEXT",
        params: {},
      });
    }

    const count = await this.prisma.providerConnection.count({
      where: { userId, emailVerifiedAt: { not: null } },
    });

    if (count === 0) {
      throw new ForbiddenException({
        code: "EMAIL_NOT_VERIFIED",
        params: {},
      });
    }

    return true;
  }
}
