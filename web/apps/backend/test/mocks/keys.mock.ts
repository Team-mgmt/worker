import * as crypto from "crypto";

type MockKeyService = {
  getLatestKey: jest.Mock;
  validateToken: jest.Mock;
};

// Generate a mock EC key pair for testing
const generateMockKeyPair = () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync("ec", {
    namedCurve: "P-521",
  });
  return { private: privateKey, public: publicKey };
};

export const createMockKeyService = (): MockKeyService => {
  const mockKeyPair = generateMockKeyPair();

  return {
    getLatestKey: jest.fn().mockResolvedValue({
      keyId: "test-key-id",
      key: mockKeyPair,
    }),
    validateToken: jest.fn(),
  };
};

export type { MockKeyService };
