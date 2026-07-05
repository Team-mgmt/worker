import { randomUUID } from "crypto";

import { Injectable } from "@nestjs/common";

import type { OrganizationMember, Prisma } from "@shelfalign/database/client";
import { NAMESPACES, RELATIONS } from "@shelfalign/schema/permission";

import { PrismaService } from "@/providers/database/prisma.service";

type PrismaTx = Prisma.TransactionClient;

@Injectable()
export class OrganizationOwnershipService {
  constructor(private readonly prisma: PrismaService) {}

  async grantOwner(
    memberId: string,
    organizationId: string,
    tx?: PrismaTx,
  ): Promise<void> {
    const client = tx ?? this.prisma;
    await client.permissionTuple.create({
      data: {
        id: randomUUID(),
        namespace: NAMESPACES.organization,
        objectId: organizationId,
        organizationId,
        relationId: RELATIONS.owner,
        memberId,
      },
    });
  }

  async getOwners(organizationId: string): Promise<OrganizationMember[]> {
    const tuples = await this.prisma.permissionTuple.findMany({
      where: {
        namespace: NAMESPACES.organization,
        objectId: organizationId,
        relationId: RELATIONS.owner,
        revokedAt: null,
      },
      include: { member: true },
      orderBy: { createdAt: "asc" },
    });
    return tuples
      .map((t) => t.member)
      .filter((m): m is OrganizationMember => m != null);
  }

  async isOwner(memberId: string, organizationId: string): Promise<boolean> {
    const count = await this.prisma.permissionTuple.count({
      where: {
        namespace: NAMESPACES.organization,
        objectId: organizationId,
        relationId: RELATIONS.owner,
        memberId,
        revokedAt: null,
      },
    });
    return count > 0;
  }
}
