import { createHash, randomBytes, timingSafeEqual } from "crypto";

import { Injectable } from "@nestjs/common";

@Injectable()
export class EmailTokenService {
  generate(): { raw: string; hash: string } {
    const raw = randomBytes(32).toString("base64url");
    return { raw, hash: this.hash(raw) };
  }

  hash(raw: string): string {
    return createHash("sha256").update(raw, "utf8").digest("hex");
  }

  compare(raw: string, storedHash: string): boolean {
    const a = Buffer.from(this.hash(raw), "hex");
    const b = Buffer.from(storedHash, "hex");
    if (a.length !== b.length) return false;
    return timingSafeEqual(a, b);
  }
}
