type MockCacheClient = {
  get: jest.Mock;
  set: jest.Mock;
  del: jest.Mock;
  keys: jest.Mock;
  expire: jest.Mock;
  ttl: jest.Mock;
  exists: jest.Mock;
};

type MockCacheService = {
  client: MockCacheClient;
};

export const createMockCacheClient = (): MockCacheClient => ({
  get: jest.fn(),
  set: jest.fn(),
  del: jest.fn(),
  keys: jest.fn(),
  expire: jest.fn(),
  ttl: jest.fn(),
  exists: jest.fn(),
});

export const createMockCacheService = (): MockCacheService => ({
  client: createMockCacheClient(),
});

export type { MockCacheService, MockCacheClient };
