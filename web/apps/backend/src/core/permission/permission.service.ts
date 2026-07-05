import { Injectable, Logger, OnModuleInit } from "@nestjs/common";

import { RELATIONS, UUIDv4 } from "@shelfalign/schema/permission";

import { PrismaService } from "@/providers/database/prisma.service";

@Injectable()
export class PermissionService implements OnModuleInit {
  private readonly logger = new Logger(PermissionService.name);

  constructor(private readonly prismaService: PrismaService) {}

  private async initializePermissionRelation(id: UUIDv4, name: string) {
    const adminRelation =
      await this.prismaService.permissionRelation.findUnique({
        where: { id },
      });

    if (!adminRelation) {
      this.logger.log(`No "${name}" relation (${id}) found. Creating one...`);
      await this.prismaService.permissionRelation.create({
        data: { id, name },
      });
    }
  }

  async onModuleInit() {
    // Initialize permission namespaces and relations
    for (const relation of Object.keys(RELATIONS)) {
      await this.initializePermissionRelation(
        RELATIONS[relation as keyof typeof RELATIONS],
        relation,
      );
    }
  }

  /**
   * Batch fetches permission tuple tree by fetching all references in batches
   * instead of making one query per tuple (N+1 fix)
   */
  async getPermissionTupleTree(
    id: string,
    cache: Set<string> = new Set<string>(),
  ): Promise<string[]> {
    return this.batchGetPermissionTupleTree([id], cache);
  }

  /**
   * Batch fetches permission tuple trees for multiple starting IDs
   * Uses iterative approach with batch queries to avoid N+1
   */
  private async batchGetPermissionTupleTree(
    startIds: string[],
    cache: Set<string> = new Set<string>(),
  ): Promise<string[]> {
    // Filter out already cached IDs
    let toFetch = startIds.filter((id) => !cache.has(id));

    while (toFetch.length > 0) {
      // Batch fetch all tuples with their references
      const tuples = await this.prismaService.permissionTuple.findMany({
        where: {
          id: { in: toFetch },
          revokedAt: null,
        },
        select: {
          id: true,
          references: { select: { id: true } },
        },
      });

      // Add fetched IDs to cache
      for (const tuple of tuples) {
        cache.add(tuple.id);
      }

      // Collect next level of IDs to fetch (references not yet in cache)
      const nextLevel: string[] = [];
      for (const tuple of tuples) {
        for (const ref of tuple.references) {
          if (!cache.has(ref.id)) {
            nextLevel.push(ref.id);
          }
        }
      }

      // Deduplicate and prepare for next iteration
      toFetch = [...new Set(nextLevel)];
    }

    return Array.from(cache.values());
  }

  async getUserPermissionTupleTree(memberId: string, organizationId: string) {
    const userTuples = await this.prismaService.permissionTuple.findMany({
      where: {
        memberId,
        organizationId,
        revokedAt: null,
      },
      select: {
        id: true,
      },
    });

    const startIds = userTuples.map((tuple) => tuple.id);
    return this.batchGetPermissionTupleTree(startIds);
  }

  async checkUserPermission(
    namespace: string,
    objectId: string,
    relationId: string,
    memberId: string,
    organizationId: string,
  ) {
    const userTuples = await this.getUserPermissionTupleTree(
      memberId,
      organizationId,
    );

    const permission = await this.prismaService.permissionTuple.count({
      where: {
        namespace,
        objectId,
        relationId,
        organizationId,
        OR: [
          {
            memberId,
          },
          {
            targetId: { in: userTuples },
          },
        ],
      },
    });

    return permission > 0;
  }
}
