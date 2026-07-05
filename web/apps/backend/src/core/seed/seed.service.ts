import { randomUUID } from "node:crypto";

import { Inject, Injectable, Logger, OnModuleInit } from "@nestjs/common";

import { GetObjectCommand, PutObjectCommand } from "@aws-sdk/client-s3";
import { v7 as uuidv7 } from "uuid";

import { UserType } from "@shelfalign/database/types";
import { NAMESPACES, RELATIONS } from "@shelfalign/schema/permission";

import {
  ADMIN_ORGANIZATION_ID,
  GUEST_ORGANIZATION_ID,
} from "@/common/constants";
import { EnvType, registerEnv } from "@/common/utils/env";
import { PrismaService } from "@/providers/database/prisma.service";
import { S3Service } from "@/providers/s3/s3.service";

const EMAIL_VERIFIED_BACKFILL_FLAG = "flags/migrations/email-verified";

@Injectable()
export class SeedService implements OnModuleInit {
  private logger = new Logger(SeedService.name);

  constructor(
    private readonly prismaService: PrismaService,
    private readonly s3Service: S3Service,
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
  ) {}

  private async createProvider(name: string) {
    const providers = await this.prismaService.provider.findMany({
      where: { name, deletedAt: null },
      orderBy: { createdAt: "asc" },
    });

    if (providers.length === 0) {
      this.logger.log(`No ${name} provider found. Creating one...`);
      await this.prismaService.provider.create({
        data: {
          id: uuidv7(),
          name,
          config: {},
        },
      });
      return;
    }

    if (providers.length > 1 && providers[0]) {
      this.logger.warn(
        `Multiple ${name} providers found (${providers.length}). Only the first one will remain active.`,
      );
      await this.prismaService.provider.updateMany({
        where: {
          name,
          id: { not: providers[0].id },
          deletedAt: null,
        },
        data: { deletedAt: new Date() },
      });
    }
  }

  private async createOrganization(id: string, name: string) {
    const organization = await this.prismaService.organization.findUnique({
      where: { id },
    });
    if (organization) return;

    this.logger.log(`Creating organization: ${name}`);
    await this.prismaService.organization.create({
      data: { id, name },
    });
  }

  private async readBackfillCutoff(): Promise<Date | null> {
    try {
      const res = await this.s3Service.client.send(
        new GetObjectCommand({
          Bucket: this.env.S3_BUCKET_NAME,
          Key: EMAIL_VERIFIED_BACKFILL_FLAG,
        }),
      );
      const body = await res.Body?.transformToString();
      if (!body) return null;
      const parsed = JSON.parse(body) as { cutoff?: string };
      return parsed.cutoff ? new Date(parsed.cutoff) : null;
    } catch {
      return null;
    }
  }

  private async backfillLegacyEmailVerified() {
    let cutoff = await this.readBackfillCutoff();
    if (!cutoff) {
      cutoff = new Date();
      try {
        await this.s3Service.client.send(
          new PutObjectCommand({
            Bucket: this.env.S3_BUCKET_NAME,
            Key: EMAIL_VERIFIED_BACKFILL_FLAG,
            Body: JSON.stringify({ cutoff: cutoff.toISOString() }, null, 2),
            ContentType: "application/json",
            IfNoneMatch: "*",
          }),
        );
      } catch (err) {
        const status =
          (err as { $metadata?: { httpStatusCode?: number } })?.$metadata
            ?.httpStatusCode ?? 0;
        if (status !== 412) {
          this.logger.warn(
            "Could not persist email verification backfill marker to S3. " +
              "Continuing with an in-memory cutoff for this boot.",
          );
        } else {
          const persisted = await this.readBackfillCutoff();
          if (!persisted) throw err;
          cutoff = persisted;
        }
      }
    }

    const result = await this.prismaService.providerConnection.updateMany({
      where: {
        emailVerifiedAt: null,
        createdAt: { lt: cutoff },
      },
      data: { emailVerifiedAt: cutoff },
    });

    if (result.count > 0) {
      this.logger.log(
        `Backfilled ${result.count} legacy provider connections as email-verified.`,
      );
    }
  }

  private async backfillOrgOwnerTuples() {
    await this.prismaService.permissionRelation.upsert({
      where: { id: RELATIONS.owner },
      update: {},
      create: { id: RELATIONS.owner, name: "owner" },
    });

    const orgs = await this.prismaService.organization.findMany({
      select: { id: true },
    });
    let granted = 0;

    for (const org of orgs) {
      const existing = await this.prismaService.permissionTuple.count({
        where: {
          namespace: NAMESPACES.organization,
          objectId: org.id,
          relationId: RELATIONS.owner,
          revokedAt: null,
        },
      });
      if (existing > 0) continue;

      const admin = await this.prismaService.organizationMember.findFirst({
        where: { organizationId: org.id, type: UserType.ADMIN },
        orderBy: { id: "asc" },
      });
      const pick =
        admin ??
        (await this.prismaService.organizationMember.findFirst({
          where: { organizationId: org.id },
          orderBy: { id: "asc" },
        }));
      if (!pick) continue;

      await this.prismaService.permissionTuple.create({
        data: {
          id: randomUUID(),
          namespace: NAMESPACES.organization,
          objectId: org.id,
          organizationId: org.id,
          relationId: RELATIONS.owner,
          memberId: pick.id,
        },
      });
      granted += 1;
    }

    if (granted > 0) {
      this.logger.log(`Granted owner tuple for ${granted} organization(s).`);
    }
  }

  async onModuleInit() {
    await this.prismaService.waitForActiveConnections();
    await this.createProvider("local");
    await this.createProvider("admin");
    await this.createOrganization(ADMIN_ORGANIZATION_ID, "Admin Organization");
    await this.createOrganization(GUEST_ORGANIZATION_ID, "Guest Organization");
    await this.backfillLegacyEmailVerified();
    await this.backfillOrgOwnerTuples();
  }
}
