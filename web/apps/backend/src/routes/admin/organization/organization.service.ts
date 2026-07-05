import {
  ForbiddenException,
  Injectable,
  NotFoundException,
} from "@nestjs/common";

import { Prisma } from "@shelfalign/database/client";

import { ADMIN_ORGANIZATION_ID } from "@/common/constants";
import { PaginationQueryDto } from "@/common/schema/pagination.schema";
import { PrismaService } from "@/providers/database/prisma.service";

import type { UpdateOrganizationDto } from "./organization.schema";

@Injectable()
export class AdminOrganizationService {
  constructor(private readonly prisma: PrismaService) {}

  async list(pagination?: PaginationQueryDto) {
    const { page = 1, pageSize = 10 } = pagination ?? {};
    const skip = (page - 1) * pageSize;
    const take = pageSize;

    const where: Prisma.OrganizationWhereInput = {
      deletedAt: null,
    };

    const [organizations, count] = await this.prisma.$transaction([
      this.prisma.organization.findMany({
        where,
        take,
        skip,
        orderBy: {
          createdAt: "desc",
        },
      }),
      this.prisma.organization.count({ where }),
    ]);

    return { organizations, count };
  }

  async get(id: string) {
    const organization = await this.prisma.organization.findUnique({
      where: { id, deletedAt: null },
    });
    if (!organization) {
      throw new NotFoundException({
        code: "ORGANIZATION_NOT_FOUND",
        params: { organizationId: id },
      });
    }
    return organization;
  }

  async update(id: string, data: UpdateOrganizationDto) {
    const organization = await this.prisma.organization.findUnique({
      where: { id, deletedAt: null },
    });
    if (!organization) {
      throw new NotFoundException({
        code: "ORGANIZATION_NOT_FOUND",
        params: { organizationId: id },
      });
    }

    const updated = await this.prisma.organization.update({
      where: { id, deletedAt: null },
      data,
    });
    return updated;
  }

  async remove(id: string) {
    if (id === ADMIN_ORGANIZATION_ID) {
      throw new ForbiddenException({
        code: "CANNOT_DELETE_ADMIN_ORGANIZATION",
        params: { organizationId: id },
      });
    }

    const organization = await this.prisma.organization.findUnique({
      where: { id, deletedAt: null },
    });
    if (!organization) {
      throw new NotFoundException({
        code: "ORGANIZATION_NOT_FOUND",
        params: { organizationId: id },
      });
    }

    await this.prisma.organization.update({
      where: { id, deletedAt: null },
      data: {
        deletedAt: new Date(),
      },
    });
  }
}
