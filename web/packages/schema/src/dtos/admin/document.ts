import z from "zod";

import { TiptapContentSchema } from "../../models/tiptap-content";

import { BaseSuccessSchema } from "../base.js";

// A document slug is the part between `docs/` and `.json` in the S3 key.
// Slugs are URL-safe and must not contain slashes or extension.
export const DocumentSlugSchema = z
  .string()
  .min(1)
  .max(128)
  .regex(/^[a-zA-Z0-9_-]+$/);

export const AdminDocumentSummarySchema = z.object({
  slug: z.string(),
  lastModified: z.iso.datetime().nullable(),
  size: z.number(),
  isDeleted: z.boolean(),
});
export type AdminDocumentSummary = z.infer<typeof AdminDocumentSummarySchema>;

export const AdminDocumentVersionSchema = z.object({
  versionId: z.string(),
  lastModified: z.iso.datetime().nullable(),
  size: z.number(),
  isLatest: z.boolean(),
  isDeleteMarker: z.boolean(),
});
export type AdminDocumentVersion = z.infer<typeof AdminDocumentVersionSchema>;

// List documents
export const AdminListDocumentsQuerySchema = z.object({
  includeDeleted: z
    .union([z.literal("true"), z.literal("false")])
    .optional()
    .transform((v) => v === "true"),
});
export type AdminListDocumentsQuery = z.infer<
  typeof AdminListDocumentsQuerySchema
>;

export const AdminListDocumentsResponseSchema = z.object({
  result: z.literal(true),
  data: z.array(AdminDocumentSummarySchema),
});
export type AdminListDocumentsResponse = z.infer<
  typeof AdminListDocumentsResponseSchema
>;

// Get a document (current or specific version)
export const AdminGetDocumentQuerySchema = z.object({
  versionId: z.string().optional(),
});
export type AdminGetDocumentQuery = z.infer<typeof AdminGetDocumentQuerySchema>;

export const AdminGetDocumentResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    slug: z.string(),
    versionId: z.string().nullable(),
    lastModified: z.iso.datetime().nullable(),
    isDeleted: z.boolean(),
    content: TiptapContentSchema.nullable(),
  }),
});
export type AdminGetDocumentResponse = z.infer<
  typeof AdminGetDocumentResponseSchema
>;

// List versions for a document
export const AdminListDocumentVersionsResponseSchema = z.object({
  result: z.literal(true),
  data: z.array(AdminDocumentVersionSchema),
});
export type AdminListDocumentVersionsResponse = z.infer<
  typeof AdminListDocumentVersionsResponseSchema
>;

// Create a new document
export const AdminCreateDocumentRequestSchema = z.object({
  slug: DocumentSlugSchema,
  content: TiptapContentSchema,
});
export type AdminCreateDocumentRequest = z.infer<
  typeof AdminCreateDocumentRequestSchema
>;

export const AdminCreateDocumentResponseSchema = z.object({
  result: z.literal(true),
  data: AdminDocumentSummarySchema,
});
export type AdminCreateDocumentResponse = z.infer<
  typeof AdminCreateDocumentResponseSchema
>;

// Update an existing document (creates a new version)
export const AdminUpdateDocumentRequestSchema = z.object({
  content: TiptapContentSchema,
});
export type AdminUpdateDocumentRequest = z.infer<
  typeof AdminUpdateDocumentRequestSchema
>;

export const AdminUpdateDocumentResponseSchema = z.object({
  result: z.literal(true),
  data: AdminDocumentSummarySchema,
});
export type AdminUpdateDocumentResponse = z.infer<
  typeof AdminUpdateDocumentResponseSchema
>;

// Delete (places a delete marker; previous versions remain)
export const AdminDeleteDocumentResponseSchema = BaseSuccessSchema;
export type AdminDeleteDocumentResponse = z.infer<
  typeof AdminDeleteDocumentResponseSchema
>;

// Restore a previous version (reads it and writes a new latest version)
export const AdminRestoreDocumentVersionRequestSchema = z.object({
  versionId: z.string().min(1),
});
export type AdminRestoreDocumentVersionRequest = z.infer<
  typeof AdminRestoreDocumentVersionRequestSchema
>;

export const AdminRestoreDocumentVersionResponseSchema = z.object({
  result: z.literal(true),
  data: AdminDocumentSummarySchema,
});
export type AdminRestoreDocumentVersionResponse = z.infer<
  typeof AdminRestoreDocumentVersionResponseSchema
>;
