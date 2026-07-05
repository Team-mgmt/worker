import { EmailTokenService } from "./email-token.service";

describe("EmailTokenService", () => {
  const service = new EmailTokenService();

  it("generates a raw token and returns its sha256 hash", () => {
    const { raw, hash } = service.generate();
    expect(raw).toMatch(/^[A-Za-z0-9_-]{40,}$/);
    expect(hash).toHaveLength(64);
    expect(service.hash(raw)).toBe(hash);
  });

  it("compare returns true only for matching hash", () => {
    const { raw, hash } = service.generate();
    expect(service.compare(raw, hash)).toBe(true);
    expect(service.compare(raw + "x", hash)).toBe(false);
  });
});
