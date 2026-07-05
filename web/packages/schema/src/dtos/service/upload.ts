import z from "zod";

// Allowlist of MIME types that the platform's upload pipeline can produce or
// consume. Adding a new type here requires confirming downstream handlers
// (shelf images, board attachments, documents, etc.) actually expect it AND that
// the bucket/CloudFront serving path either keeps the bucket private or
// forces Content-Disposition: attachment for non-image types.
export const UPLOAD_ALLOWED_CONTENT_TYPES = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "image/svg+xml",
] as const;

// Hard cap on a single upload, in bytes. Keep generous enough for multi-page
// PDFs but small enough that storage cost amplification stays bounded if the
// rate limit is bypassed.
export const UPLOAD_MAX_SIZE_BYTES = 50 * 1024 * 1024;

export const GeneratePresignedUrlRequestSchema = z.object({
  filename: z.string().min(1, "파일명을 입력해주세요"),
  contentType: z.enum(UPLOAD_ALLOWED_CONTENT_TYPES, {
    error: "지원하지 않는 파일 형식입니다",
  }),
  size: z
    .number()
    .int()
    .positive("파일 크기를 입력해주세요")
    .max(UPLOAD_MAX_SIZE_BYTES, "파일 크기가 너무 큽니다"),
});
export type GeneratePresignedUrlRequest = z.infer<
  typeof GeneratePresignedUrlRequestSchema
>;

export const GeneratePresignedUrlResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    uploadUrl: z.url(),
    key: z.string(),
    uploadFileId: z.uuid(),
  }),
});
export type GeneratePresignedUrlResponse = z.infer<
  typeof GeneratePresignedUrlResponseSchema
>;
