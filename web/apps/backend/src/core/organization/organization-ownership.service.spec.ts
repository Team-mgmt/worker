import { Test } from "@nestjs/testing";

import { NAMESPACES, RELATIONS } from "@shelfalign/schema/permission";

import { PrismaService } from "@/providers/database/prisma.service";

import { OrganizationOwnershipService } from "./organization-ownership.service";

describe("OrganizationOwnershipService", () => {
  const prisma = {
    permissionTuple: {
      create: jest.fn(),
      findMany: jest.fn(),
      count: jest.fn(),
    },
  };

  let service: OrganizationOwnershipService;

  beforeEach(async () => {
    jest.resetAllMocks();
    const moduleRef = await Test.createTestingModule({
      providers: [
        OrganizationOwnershipService,
        { provide: PrismaService, useValue: prisma },
      ],
    }).compile();
    service = moduleRef.get(OrganizationOwnershipService);
  });

  it("grantOwner inserts a tuple with the owner relation and org namespace", async () => {
    prisma.permissionTuple.create.mockResolvedValue({});
    await service.grantOwner("member-id", "org-id");
    expect(prisma.permissionTuple.create).toHaveBeenCalledWith({
      data: expect.objectContaining({
        namespace: NAMESPACES.organization,
        objectId: "org-id",
        organizationId: "org-id",
        relationId: RELATIONS.owner,
        memberId: "member-id",
      }),
    });
  });

  it("getOwners returns members from active owner tuples", async () => {
    prisma.permissionTuple.findMany.mockResolvedValue([
      { member: { id: "m1", userId: "u1" } },
      { member: { id: "m2", userId: "u2" } },
    ]);
    const result = await service.getOwners("org-id");
    expect(result.map((m) => m.id)).toEqual(["m1", "m2"]);
    expect(prisma.permissionTuple.findMany).toHaveBeenCalledWith({
      where: {
        namespace: NAMESPACES.organization,
        objectId: "org-id",
        relationId: RELATIONS.owner,
        revokedAt: null,
      },
      include: { member: true },
      orderBy: { createdAt: "asc" },
    });
  });

  it("isOwner returns true when count > 0", async () => {
    prisma.permissionTuple.count.mockResolvedValue(1);
    await expect(service.isOwner("m1", "org-id")).resolves.toBe(true);
    prisma.permissionTuple.count.mockResolvedValue(0);
    await expect(service.isOwner("m1", "org-id")).resolves.toBe(false);
  });
});
