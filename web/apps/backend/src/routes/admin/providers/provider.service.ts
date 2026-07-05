import { Injectable, NotFoundException } from "@nestjs/common";

import { Prisma, type Provider } from "@shelfalign/database/client";

import { PaginationQueryDto } from "@/common/schema/pagination.schema";
import { PrismaService } from "@/providers/database/prisma.service";

@Injectable()
export class AdminProviderService {
  constructor(private readonly prisma: PrismaService) {}

  async list(
    pagination?: PaginationQueryDto,
  ): Promise<{ providers: Provider[]; count: number }> {
    const { page = 1, pageSize = 10 } = pagination ?? {};
    const skip = (page - 1) * pageSize;
    const take = pageSize;

    const where: Prisma.ProviderWhereInput = {
      deletedAt: null,
    };

    const [providers, count] = await this.prisma.$transaction([
      this.prisma.provider.findMany({
        where,
        take,
        skip,
        orderBy: {
          createdAt: "desc",
        },
      }),
      this.prisma.provider.count({ where }),
    ]);

    return { providers, count };
  }

  async get(id: string): Promise<Provider> {
    const provider = await this.prisma.provider.findUnique({
      where: { id, deletedAt: null },
    });

    if (!provider) {
      throw new NotFoundException({
        code: "PROVIDER_NOT_FOUND",
        params: { providerId: id },
      });
    }

    return provider;
  }

  async remove(id: string) {
    const provider = await this.prisma.provider.findUnique({
      where: { id, deletedAt: null },
    });

    if (!provider) {
      throw new NotFoundException({
        code: "PROVIDER_NOT_FOUND",
        params: { providerId: id },
      });
    }

    await this.prisma.provider.update({
      where: { id },
      data: {
        deletedAt: new Date(),
      },
    });
  }
}
