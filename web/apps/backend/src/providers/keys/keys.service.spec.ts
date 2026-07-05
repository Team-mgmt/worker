import { BadRequestException } from "@nestjs/common";

import jose from "jose";

import type { EnvType } from "@/common/utils/env";

import type { ParsedKeyChain } from "./keys.schema";
import { KeyService } from "./keys.service";

function encodeTokenHeader(header: Record<string, unknown>) {
  return `${Buffer.from(JSON.stringify(header)).toString("base64url")}.payload.signature`;
}

function createKey(label: string): ParsedKeyChain["keys"][string] {
  return {
    private: { label, type: "private" },
    public: { label, type: "public" },
  } as unknown as ParsedKeyChain["keys"][string];
}

describe("KeyService", () => {
  const keyId = "dev/shelfalign/web-backend/auth-keys";
  const oldKid = "019a20a7-288e-731e-a515-402674bfd1ff";
  const newKid = "019a20a7-29da-766e-b028-834ab07b895e";

  let service: KeyService;
  let internals: { keys: Record<string, ParsedKeyChain> };
  let jwtVerifyMock: jest.Mock;

  beforeEach(() => {
    service = new KeyService({
      NODE_ENV: "development",
    } as unknown as EnvType);
    internals = service as unknown as {
      keys: Record<string, ParsedKeyChain>;
    };
    jwtVerifyMock = jose.jwtVerify as unknown as jest.Mock;
    jwtVerifyMock.mockReset();
    (jose.decodeProtectedHeader as unknown as jest.Mock).mockClear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("refetches keys once when a token uses an unknown kid", async () => {
    const oldKey = createKey("old");
    const newKey = createKey("new");
    internals.keys = {
      [keyId]: {
        latestKeyId: oldKid,
        keys: { [oldKid]: oldKey },
      },
    };
    const fetchKeys = jest
      .spyOn(service, "fetchKeys")
      .mockImplementation(async (requestedKeyId) => {
        internals.keys[requestedKeyId] = {
          latestKeyId: newKid,
          keys: { [oldKid]: oldKey, [newKid]: newKey },
        };
      });
    const token = encodeTokenHeader({ alg: "ES512", kid: newKid });
    const verifiedToken = {
      protectedHeader: { kid: newKid },
      payload: { sessionId: "session-id" },
    };
    jwtVerifyMock.mockResolvedValue(verifiedToken);

    await expect(service.validateToken(keyId, token)).resolves.toBe(
      verifiedToken,
    );

    expect(fetchKeys).toHaveBeenCalledWith(keyId);
    expect(jwtVerifyMock).toHaveBeenCalledWith(token, newKey.public, {
      algorithms: ["ES512"],
      clockTolerance: 0,
    });
  });

  it("throws invalid token when the kid is still unknown after refetch", async () => {
    const oldKey = createKey("old");
    internals.keys = {
      [keyId]: {
        latestKeyId: oldKid,
        keys: { [oldKid]: oldKey },
      },
    };
    const fetchKeys = jest.spyOn(service, "fetchKeys").mockResolvedValue();
    const token = encodeTokenHeader({ alg: "ES512", kid: newKid });

    await expect(service.validateToken(keyId, token)).rejects.toThrow(
      BadRequestException,
    );

    expect(fetchKeys).toHaveBeenCalledWith(keyId);
    expect(jwtVerifyMock).not.toHaveBeenCalled();
  });
});
