import { BadRequestException } from "@nestjs/common";

const SAFE_S3_KEY_PATTERN = /^[a-zA-Z0-9\-_./]+$/;

/**
 * Validates and sanitizes S3 keys using an allowlist approach.
 * Allows: alphanumeric, hyphen, underscore, dot, forward slash.
 * Rejects empty keys, path traversal (`..`, `//`), and leading slashes.
 */
export function sanitizeS3Key(key: string): string {
  if (!key || !SAFE_S3_KEY_PATTERN.test(key)) {
    throw new BadRequestException({
      code: "INVALID_S3_KEY",
      params: { key },
    });
  }

  if (key.includes("..") || key.includes("//")) {
    throw new BadRequestException({
      code: "INVALID_S3_KEY",
      params: { key },
    });
  }

  const sanitized = key.startsWith("/") ? key.slice(1) : key;

  if (sanitized.includes("..") || sanitized.startsWith("/")) {
    throw new BadRequestException({
      code: "INVALID_S3_KEY",
      params: { key },
    });
  }

  return sanitized;
}

export function extractExtension(key: string): string {
  const sanitizedKey = sanitizeS3Key(key);
  const parts = sanitizedKey.split("/").pop()?.split(".") ?? [];
  const ext = parts.length > 1 ? parts.pop() : null;

  if (ext && /^[a-zA-Z0-9]+$/.test(ext)) {
    return ext;
  }

  return "bin";
}
