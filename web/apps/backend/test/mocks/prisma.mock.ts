import type { PrismaService } from "@/providers/database/prisma.service";

type MockPrismaService = {
  [K in keyof PrismaService]: PrismaService[K] extends (
    ...args: unknown[]
  ) => unknown
    ? jest.Mock
    : MockPrismaModel;
} & {
  $transaction: jest.Mock;
};

type MockPrismaModel = {
  findUnique: jest.Mock;
  findFirst: jest.Mock;
  findMany: jest.Mock;
  create: jest.Mock;
  createMany: jest.Mock;
  update: jest.Mock;
  updateMany: jest.Mock;
  delete: jest.Mock;
  deleteMany: jest.Mock;
  count: jest.Mock;
  upsert: jest.Mock;
};

const createMockModel = (): MockPrismaModel => ({
  findUnique: jest.fn(),
  findFirst: jest.fn(),
  findMany: jest.fn(),
  create: jest.fn(),
  createMany: jest.fn(),
  update: jest.fn(),
  updateMany: jest.fn(),
  delete: jest.fn(),
  deleteMany: jest.fn(),
  count: jest.fn(),
  upsert: jest.fn(),
});

export const createMockPrismaService = (): MockPrismaService => {
  return {
    session: createMockModel(),
    user: createMockModel(),
    refreshToken: createMockModel(),
    organization: createMockModel(),
    organizationMember: createMockModel(),
    permissionRelation: createMockModel(),
    permissionTuple: createMockModel(),
    uploadFile: createMockModel(),
    provider: createMockModel(),
    providerConnection: createMockModel(),
    emailVerificationToken: createMockModel(),
    passwordResetToken: createMockModel(),
    invitation: createMockModel(),
    emailLog: createMockModel(),
    library: createMockModel(),
    libraryBook: createMockModel(),
    libraryHolding: createMockModel(),
    shelfScanSession: createMockModel(),
    shelfDetection: createMockModel(),
    $transaction: jest.fn((ops) => Promise.all(ops)),
    $connect: jest.fn(),
    $disconnect: jest.fn(),
    $on: jest.fn(),
    $use: jest.fn(),
    $queryRaw: jest.fn(),
    $executeRaw: jest.fn(),
  } as unknown as MockPrismaService;
};

export type { MockPrismaService, MockPrismaModel };
