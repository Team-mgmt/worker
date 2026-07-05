import {
  BadRequestException,
  ConflictException,
  Injectable,
  NotFoundException,
} from "@nestjs/common";

import type { TiptapContent } from "@shelfalign/schema/models/tiptap-content";

import { S3Service } from "@/providers/s3/s3.service";

const DOCS_PREFIX = "docs/";
const DOCS_SUFFIX = ".json";
const SLUG_REGEX = /^[a-zA-Z0-9_-]+$/;
const CONTENT_TYPE = "application/json";
// CloudFront/S3 origin transfers are free; rely on TTL rather than paid
// invalidations so admin edits propagate within ~1 minute at zero cost.
const CACHE_CONTROL = "public, max-age=60";

// S3 GetObject on a missing key — or a key whose latest version is a delete
// marker — fails with NoSuchKey. Anything else (AccessDenied, transient
// network/5xx, parse errors thrown later in the try block) should surface to
// the caller rather than be swallowed as "deleted".
const S3_MISSING_LATEST_ERROR_NAMES: ReadonlySet<string> = new Set([
  "NoSuchKey",
]);

// For version-specific GetObject, S3 also returns NoSuchVersion for an unknown
// version id, and 405 MethodNotAllowed when the requested version is a delete
// marker.
const S3_MISSING_VERSION_ERROR_NAMES: ReadonlySet<string> = new Set([
  "NoSuchKey",
  "NoSuchVersion",
  "MethodNotAllowed",
]);

function isS3MissingError(error: unknown, names: ReadonlySet<string>): boolean {
  if (typeof error !== "object" || error === null || !("name" in error)) {
    return false;
  }
  const name = (error as { name?: unknown }).name;
  return typeof name === "string" && names.has(name);
}

export type DocumentSummary = {
  slug: string;
  lastModified: Date | null;
  size: number;
  isDeleted: boolean;
};

export type DocumentVersion = {
  versionId: string;
  lastModified: Date | null;
  size: number;
  isLatest: boolean;
  isDeleteMarker: boolean;
};

@Injectable()
export class AdminDocumentService {
  constructor(private readonly s3Service: S3Service) {}

  private toKey(slug: string): string {
    if (!SLUG_REGEX.test(slug)) {
      throw new BadRequestException({
        code: "INVALID_DOCUMENT_SLUG",
        params: { slug },
      });
    }
    return `${DOCS_PREFIX}${slug}${DOCS_SUFFIX}`;
  }

  private fromKey(key: string): string | null {
    if (!key.startsWith(DOCS_PREFIX) || !key.endsWith(DOCS_SUFFIX)) {
      return null;
    }
    const slug = key.slice(DOCS_PREFIX.length, -DOCS_SUFFIX.length);
    if (!slug || slug.includes("/") || !SLUG_REGEX.test(slug)) {
      return null;
    }
    return slug;
  }

  async listDocuments(includeDeleted: boolean): Promise<DocumentSummary[]> {
    const items = await this.s3Service.listKeysWithVersions(DOCS_PREFIX);
    const summaries: DocumentSummary[] = [];
    for (const item of items) {
      const slug = this.fromKey(item.key);
      if (!slug) continue;
      if (item.isDeleted && !includeDeleted) continue;
      summaries.push({
        slug,
        lastModified: item.lastModified,
        size: item.size,
        isDeleted: item.isDeleted,
      });
    }
    return summaries;
  }

  async getDocument(
    slug: string,
    versionId?: string,
  ): Promise<{
    slug: string;
    versionId: string | null;
    lastModified: Date | null;
    isDeleted: boolean;
    content: TiptapContent | null;
  }> {
    const key = this.toKey(slug);

    if (versionId) {
      // Fetch a specific historical version. May be a delete marker, in which
      // case we return content=null with isDeleted=true.
      try {
        const buffer = await this.s3Service.downloadObject(key, versionId);
        const content = this.parseContent(buffer);
        const versions = await this.s3Service.listObjectVersions(key);
        const meta = versions.find((v) => v.versionId === versionId);
        return {
          slug,
          versionId,
          lastModified: meta?.lastModified ?? null,
          isDeleted: false,
          content,
        };
      } catch (error) {
        if (!isS3MissingError(error, S3_MISSING_VERSION_ERROR_NAMES)) {
          throw error;
        }
        const versions = await this.s3Service.listObjectVersions(key);
        const meta = versions.find((v) => v.versionId === versionId);
        if (!meta) {
          throw new NotFoundException({
            code: "DOCUMENT_VERSION_NOT_FOUND",
            params: { slug, versionId },
          });
        }
        return {
          slug,
          versionId,
          lastModified: meta.lastModified,
          isDeleted: meta.isDeleteMarker,
          content: null,
        };
      }
    }

    // Latest version path. If the latest is a delete marker, fetch will fail
    // with NoSuchKey — surface it as isDeleted and return null content so the
    // UI can show "deleted" state. Anything else (corrupt JSON, AccessDenied,
    // transient 5xx) propagates so we don't mask data corruption or perm bugs.
    try {
      const buffer = await this.s3Service.downloadObject(key);
      const content = this.parseContent(buffer);
      const lastModified = await this.s3Service.getObjectLastModified(key);
      return {
        slug,
        versionId: null,
        lastModified,
        isDeleted: false,
        content,
      };
    } catch (error) {
      if (!isS3MissingError(error, S3_MISSING_LATEST_ERROR_NAMES)) {
        throw error;
      }
      const versions = await this.s3Service.listObjectVersions(key);
      if (versions.length === 0) {
        throw new NotFoundException({
          code: "DOCUMENT_NOT_FOUND",
          params: { slug },
        });
      }
      const latest = versions.find((v) => v.isLatest) ?? versions[0]!;
      return {
        slug,
        versionId: null,
        lastModified: latest.lastModified,
        isDeleted: latest.isDeleteMarker,
        content: null,
      };
    }
  }

  async listDocumentVersions(slug: string): Promise<DocumentVersion[]> {
    const key = this.toKey(slug);
    const versions = await this.s3Service.listObjectVersions(key);
    if (versions.length === 0) {
      throw new NotFoundException({
        code: "DOCUMENT_NOT_FOUND",
        params: { slug },
      });
    }
    return versions;
  }

  async createDocument(
    slug: string,
    content: TiptapContent,
  ): Promise<DocumentSummary> {
    const key = this.toKey(slug);

    if (await this.s3Service.objectExists(key)) {
      throw new ConflictException({
        code: "DOCUMENT_ALREADY_EXISTS",
        params: { slug },
      });
    }

    return this.writeDocument(slug, key, content);
  }

  async updateDocument(
    slug: string,
    content: TiptapContent,
  ): Promise<DocumentSummary> {
    const key = this.toKey(slug);

    // HEAD returns 404 for missing keys *and* for keys whose latest version is
    // a delete marker, so this also blocks updates to soft-deleted documents —
    // restoreVersion is the explicit undelete path. `objectExists` rethrows
    // non-404 errors (AccessDenied, transient 5xx) so they aren't misreported
    // as 404.
    if (!(await this.s3Service.objectExists(key))) {
      throw new NotFoundException({
        code: "DOCUMENT_NOT_FOUND",
        params: { slug },
      });
    }

    return this.writeDocument(slug, key, content);
  }

  async deleteDocument(slug: string): Promise<void> {
    const key = this.toKey(slug);

    // Without this guard, S3 versioning happily writes a delete marker for any
    // key — typoed slugs would surface as ghost entries in the deleted list.
    if (!(await this.s3Service.objectExists(key))) {
      throw new NotFoundException({
        code: "DOCUMENT_NOT_FOUND",
        params: { slug },
      });
    }

    // S3 with versioning enabled keeps prior versions and adds a delete marker.
    await this.s3Service.deleteObject(key);
  }

  async restoreVersion(
    slug: string,
    versionId: string,
  ): Promise<DocumentSummary> {
    const key = this.toKey(slug);
    let buffer: Buffer;
    try {
      buffer = await this.s3Service.downloadObject(key, versionId);
    } catch (error) {
      if (!isS3MissingError(error, S3_MISSING_VERSION_ERROR_NAMES)) {
        throw error;
      }
      throw new NotFoundException({
        code: "DOCUMENT_VERSION_NOT_FOUND",
        params: { slug, versionId },
      });
    }

    // Verify it parses as valid Tiptap JSON before restoring. Bypasses the
    // existence check in updateDocument so a soft-deleted document can be
    // brought back.
    const content = this.parseContent(buffer);
    return this.writeDocument(slug, key, content);
  }

  private async writeDocument(
    slug: string,
    key: string,
    content: TiptapContent,
  ): Promise<DocumentSummary> {
    const body = JSON.stringify(content);
    await this.s3Service.putObject(key, body, CONTENT_TYPE, CACHE_CONTROL);
    const lastModified = await this.s3Service.getObjectLastModified(key);

    return {
      slug,
      lastModified,
      size: Buffer.byteLength(body, "utf8"),
      isDeleted: false,
    };
  }

  private parseContent(buffer: Buffer): TiptapContent {
    let parsed: unknown;
    try {
      parsed = JSON.parse(buffer.toString("utf8"));
    } catch {
      throw new BadRequestException({
        code: "DOCUMENT_INVALID_JSON",
      });
    }

    if (
      typeof parsed !== "object" ||
      parsed === null ||
      typeof (parsed as { type?: unknown }).type !== "string"
    ) {
      throw new BadRequestException({
        code: "DOCUMENT_INVALID_TIPTAP",
      });
    }

    return parsed as TiptapContent;
  }
}
