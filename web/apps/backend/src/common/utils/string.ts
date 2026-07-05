import { BadRequestException } from "@nestjs/common";

export function paramNumber(value?: string | string[], defaultValue = 0) {
  if (!value || Array.isArray(value)) return defaultValue;

  const parsed = Number(value);
  return Number.isNaN(parsed) ? defaultValue : parsed;
}

export function uuidToBase64Url(uuid: string) {
  const hex = uuid.replace(/-/g, "");
  const bytes = Buffer.from(hex, "hex");
  return bytes.toString("base64url");
}

export function base64UrlToUuid(base64url: string) {
  if (base64url.length !== 22) {
    throw new BadRequestException({
      code: "INVALID_DATA",
    });
  }

  const bytes = Buffer.from(base64url, "base64url");
  const hex = bytes.toString("hex");
  return (
    hex.slice(0, 8) +
    "-" +
    hex.slice(8, 12) +
    "-" +
    hex.slice(12, 16) +
    "-" +
    hex.slice(16, 20) +
    "-" +
    hex.slice(20)
  );
}
