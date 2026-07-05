// Mock for jose library

class MockSignJWT {
  private payload: Record<string, unknown>;
  private header: Record<string, unknown> = {};
  private _expTime: string | null = null;

  constructor(payload: Record<string, unknown>) {
    this.payload = payload;
  }

  setProtectedHeader(header: Record<string, unknown>): MockSignJWT {
    this.header = header;
    return this;
  }

  setExpirationTime(time: string): MockSignJWT {
    this._expTime = time;
    return this;
  }

  async sign(_key: unknown): Promise<string> {
    // Return a mock JWT-like string (header.payload.signature format)
    const headerBase64 = Buffer.from(JSON.stringify(this.header)).toString(
      "base64url",
    );
    const payloadWithExp = this._expTime
      ? { ...this.payload, exp: this._expTime }
      : this.payload;
    const payloadBase64 = Buffer.from(JSON.stringify(payloadWithExp)).toString(
      "base64url",
    );
    const signature = "mock_signature";
    return `${headerBase64}.${payloadBase64}.${signature}`;
  }
}

class MockJWTExpired extends Error {}

const mockJose = {
  SignJWT: MockSignJWT,
  decodeProtectedHeader: jest.fn((token: string) => {
    const [header] = token.split(".");
    if (!header) {
      throw new Error("Invalid token");
    }

    return JSON.parse(Buffer.from(header, "base64url").toString("utf-8"));
  }),
  jwtVerify: jest.fn(),
  importSPKI: jest.fn(),
  importPKCS8: jest.fn(),
  exportSPKI: jest.fn(),
  exportPKCS8: jest.fn(),
  errors: {
    JWTExpired: MockJWTExpired,
  },
};

export default mockJose;
