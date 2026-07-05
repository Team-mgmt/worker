import { BadRequestException, Inject, Injectable } from "@nestjs/common";

import {
  CloudFrontClient,
  CreateInvalidationCommand,
  waitUntilInvalidationCompleted,
} from "@aws-sdk/client-cloudfront";
import {
  CopyObjectCommand,
  DeleteObjectCommand,
  DeleteObjectTaggingCommand,
  GetObjectCommand,
  GetObjectTaggingCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
  ListObjectVersionsCommand,
  PutObjectCommand,
  PutObjectCommandInput,
  PutObjectTaggingCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

import { EnvType, registerEnv } from "@/common/utils/env";

// Round expiry to nearest hour for cache alignment
const PRESIGNED_URL_EXPIRY_SECONDS = 3600;

@Injectable()
export class S3Service {
  client: S3Client;
  private cloudFrontClient: CloudFrontClient;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
  ) {
    const accessKey = this.env.AWS_ACCESS_KEY_ID;
    const secretKey = this.env.AWS_SECRET_ACCESS_KEY;
    const sessionToken = this.env.AWS_SESSION_TOKEN;
    const region = this.env.AWS_REGION;
    const credentials =
      accessKey && secretKey
        ? { accessKeyId: accessKey, secretAccessKey: secretKey, sessionToken }
        : undefined;

    this.client = new S3Client({ region, credentials });
    this.cloudFrontClient = new CloudFrontClient({ region, credentials });
  }

  async generatePresignedUploadUrl(params: PutObjectCommandInput) {
    // Keep tagging and content-length as signed headers (not query params) so
    // SigV4 verifies the wire values match what we signed. Without these in
    // unhoistableHeaders the SDK hoists them to the query string and the
    // header sent by the client isn't bound to the signature, defeating the
    // size cap and tag enforcement.
    const command = new PutObjectCommand(params);
    const unhoistable = new Set<string>();
    if (params.Tagging) unhoistable.add("x-amz-tagging");
    if (params.ContentLength !== undefined) unhoistable.add("content-length");
    const url = await getSignedUrl(this.client, command, {
      expiresIn: 3600,
      unhoistableHeaders: unhoistable.size > 0 ? unhoistable : undefined,
    });
    return url;
  }

  async removeTag(key: string, tagKey: string) {
    const getTagsCommand = new GetObjectTaggingCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
    });

    const { TagSet = [] } = await this.client.send(getTagsCommand);
    const updatedTags = TagSet.filter((tag) => tag.Key !== tagKey);

    if (updatedTags.length === 0) {
      const deleteTagsCommand = new DeleteObjectTaggingCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
      });
      await this.client.send(deleteTagsCommand);
    } else {
      const putTagsCommand = new PutObjectTaggingCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
        Tagging: {
          TagSet: updatedTags,
        },
      });
      await this.client.send(putTagsCommand);
    }
  }

  async copyObject(
    sourceKey: string,
    destinationKey: string,
    tags?: Record<string, string>,
    contentType?: string,
  ) {
    const copyCommand = new CopyObjectCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: destinationKey,
      CopySource: `${this.env.S3_BUCKET_NAME}/${sourceKey}`,
      Tagging: tags ? this.toTagging(tags) : undefined,
      TaggingDirective: "REPLACE",
      // MetadataDirective=REPLACE wipes system headers like ContentType, so
      // pass an explicit ContentType when callers need it preserved (e.g.
      // SVG backgrounds — browsers refuse to render <img src=svg> when the
      // response Content-Type is binary/octet-stream).
      MetadataDirective: "REPLACE",
      ContentType: contentType,
    });

    await this.client.send(copyCommand);
  }

  toTagging(tags: Record<string, string>) {
    // Must match the frontend cap in packages/client-common/src/s3.ts so the
    // wire `x-amz-tagging` value matches the value signed into the presigned
    // URL. Truncating by code points (not UTF-16 units) avoids splitting
    // surrogate pairs in multi-byte filenames.
    const TAG_VALUE_MAX = 200;
    return Object.entries(tags)
      .map(([k, v]) => {
        const codePoints = Array.from(v);
        const truncated =
          codePoints.length <= TAG_VALUE_MAX
            ? v
            : codePoints.slice(0, TAG_VALUE_MAX).join("");
        return `${encodeURIComponent(k)}=${encodeURIComponent(truncated)}`;
      })
      .join("&");
  }

  getPublicUrl(key: string) {
    return `${this.env.CLOUDFRONT_URL}/${key}`;
  }

  async isExistingObject(key: string) {
    try {
      const getCommand = new HeadObjectCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
      });
      await this.client.send(getCommand);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * HEAD-checks an object's existence. Unlike `isExistingObject`, this only
   * swallows 404s (genuinely missing key, or latest version is a delete marker)
   * and rethrows everything else (AccessDenied, transient 5xx, ...) so callers
   * can surface real S3 issues instead of misreporting them as "missing".
   */
  async objectExists(key: string): Promise<boolean> {
    try {
      await this.client.send(
        new HeadObjectCommand({
          Bucket: this.env.S3_BUCKET_NAME,
          Key: key,
        }),
      );
      return true;
    } catch (error) {
      if (
        typeof error === "object" &&
        error !== null &&
        "name" in error &&
        typeof (error as { name?: unknown }).name === "string" &&
        ((error as { name: string }).name === "NotFound" ||
          (error as { name: string }).name === "NoSuchKey")
      ) {
        return false;
      }
      throw error;
    }
  }

  async getObjectContentType(key: string): Promise<string | undefined> {
    const response = await this.client.send(
      new HeadObjectCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
      }),
    );
    return response.ContentType;
  }

  async getObjectLastModified(key: string): Promise<Date | null> {
    try {
      const getCommand = new HeadObjectCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
      });
      const response = await this.client.send(getCommand);
      return response.LastModified ?? null;
    } catch {
      return null;
    }
  }

  async getMetadata(key: string): Promise<Record<string, string>> {
    const command = new HeadObjectCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
    });
    const response = await this.client.send(command);
    return response.Metadata ?? {};
  }

  async setMetadata(
    key: string,
    metadata: Record<string, string>,
  ): Promise<void> {
    // CopyObject with MetadataDirective=REPLACE rewrites ALL system headers,
    // so we must read the existing object headers and pass them through to
    // avoid dropping ContentType, CacheControl, etc.
    const headCommand = new HeadObjectCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
    });
    const head = await this.client.send(headCommand);
    const merged = { ...(head.Metadata ?? {}), ...metadata };

    const command = new CopyObjectCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
      CopySource: `${this.env.S3_BUCKET_NAME}/${key}`,
      MetadataDirective: "REPLACE",
      Metadata: merged,
      ContentType: head.ContentType,
      CacheControl: head.CacheControl,
      ContentDisposition: head.ContentDisposition,
      ContentEncoding: head.ContentEncoding,
      ContentLanguage: head.ContentLanguage,
    });
    await this.client.send(command);
  }

  async deleteObject(key: string) {
    const command = new DeleteObjectCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
    });
    await this.client.send(command);
  }

  async addTag(key: string, tagKey: string, tagValue: string) {
    const getTagsCommand = new GetObjectTaggingCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
    });

    const { TagSet = [] } = await this.client.send(getTagsCommand);

    // Check if tag already exists
    const existingTagIndex = TagSet.findIndex((tag) => tag.Key === tagKey);
    if (existingTagIndex >= 0) {
      TagSet[existingTagIndex] = { Key: tagKey, Value: tagValue };
    } else {
      TagSet.push({ Key: tagKey, Value: tagValue });
    }

    const putTagsCommand = new PutObjectTaggingCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
      Tagging: { TagSet },
    });
    await this.client.send(putTagsCommand);
  }

  async hasTag(key: string, tagKey: string): Promise<boolean> {
    try {
      const getTagsCommand = new GetObjectTaggingCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
      });
      const { TagSet = [] } = await this.client.send(getTagsCommand);
      return TagSet.some((tag) => tag.Key === tagKey);
    } catch {
      return false;
    }
  }

  async getTag(key: string, tagKey: string): Promise<string | null> {
    try {
      const getTagsCommand = new GetObjectTaggingCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
      });
      const { TagSet = [] } = await this.client.send(getTagsCommand);
      const tag = TagSet.find((tag) => tag.Key === tagKey);
      return tag?.Value ?? null;
    } catch {
      return null;
    }
  }

  async generatePresignedDownloadUrl(
    key: string,
    options?: { filename?: string },
  ) {
    const command = new GetObjectCommand({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
      // S3 honours `ResponseContentDisposition` on signed GETs and embeds
      // it in the response, so the browser uses the friendly filename
      // rather than the opaque key. RFC 5987 encoding handles the Korean
      // original filename surviving non-ASCII clients.
      ...(options?.filename !== undefined
        ? {
            ResponseContentDisposition: `attachment; filename*=UTF-8''${encodeURIComponent(
              options.filename,
            )}`,
          }
        : {}),
    });
    // Use fixed expiry time to enable caching on client side
    return getSignedUrl(this.client, command, {
      expiresIn: PRESIGNED_URL_EXPIRY_SECONDS,
    });
  }

  get bucketName() {
    return this.env.S3_BUCKET_NAME;
  }

  async invalidateCache(paths: string[], wait = false) {
    const distributionId = this.env.CLOUDFRONT_ID;
    if (!distributionId) {
      return;
    }

    const command = new CreateInvalidationCommand({
      DistributionId: distributionId,
      InvalidationBatch: {
        CallerReference: `${Date.now()}`,
        Paths: {
          Quantity: paths.length,
          Items: paths.map((path) =>
            path.startsWith("/") ? path : `/${path}`,
          ),
        },
      },
    });

    const response = await this.cloudFrontClient.send(command);
    const invalidationId = response.Invalidation?.Id;

    if (invalidationId && wait) {
      await waitUntilInvalidationCompleted(
        { client: this.cloudFrontClient, maxWaitTime: 300 },
        { DistributionId: distributionId, Id: invalidationId },
      );
    }
  }

  async downloadObject(key: string, versionId?: string): Promise<Buffer> {
    const response = await this.client.send(
      new GetObjectCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
        VersionId: versionId,
      }),
    );
    if (!response.Body) {
      throw new BadRequestException({
        code: "S3_OBJECT_NOT_FOUND",
        params: { key },
      });
    }
    return Buffer.from(await response.Body.transformToByteArray());
  }

  async putObject(
    key: string,
    body: Buffer | string,
    contentType?: string,
    cacheControl?: string,
  ): Promise<{ versionId: string | null }> {
    const response = await this.client.send(
      new PutObjectCommand({
        Bucket: this.env.S3_BUCKET_NAME,
        Key: key,
        Body: body,
        ContentType: contentType,
        CacheControl: cacheControl,
      }),
    );
    return { versionId: response.VersionId ?? null };
  }

  async listObjectsByPrefix(prefix: string): Promise<
    Array<{
      key: string;
      lastModified: Date | null;
      size: number;
    }>
  > {
    return this.listObjectsInBucket(this.env.S3_BUCKET_NAME, prefix);
  }

  async listObjectsInBucket(
    bucket: string,
    prefix: string,
  ): Promise<
    Array<{
      key: string;
      lastModified: Date | null;
      size: number;
    }>
  > {
    const items: Array<{
      key: string;
      lastModified: Date | null;
      size: number;
    }> = [];
    let continuationToken: string | undefined;

    do {
      const response = await this.client.send(
        new ListObjectsV2Command({
          Bucket: bucket,
          Prefix: prefix,
          ContinuationToken: continuationToken,
        }),
      );

      for (const item of response.Contents ?? []) {
        if (!item.Key) continue;
        items.push({
          key: item.Key,
          lastModified: item.LastModified ?? null,
          size: item.Size ?? 0,
        });
      }

      continuationToken = response.IsTruncated
        ? response.NextContinuationToken
        : undefined;
    } while (continuationToken);

    return items;
  }

  async generatePresignedDownloadUrlForBucket(
    bucket: string,
    key: string,
  ): Promise<string> {
    const command = new GetObjectCommand({ Bucket: bucket, Key: key });
    return getSignedUrl(this.client, command, {
      expiresIn: PRESIGNED_URL_EXPIRY_SECONDS,
    });
  }

  async listObjectVersions(key: string): Promise<
    Array<{
      versionId: string;
      lastModified: Date | null;
      size: number;
      isLatest: boolean;
      isDeleteMarker: boolean;
    }>
  > {
    const items: Array<{
      versionId: string;
      lastModified: Date | null;
      size: number;
      isLatest: boolean;
      isDeleteMarker: boolean;
    }> = [];

    let keyMarker: string | undefined;
    let versionIdMarker: string | undefined;

    do {
      const response = await this.client.send(
        new ListObjectVersionsCommand({
          Bucket: this.env.S3_BUCKET_NAME,
          Prefix: key,
          KeyMarker: keyMarker,
          VersionIdMarker: versionIdMarker,
        }),
      );

      for (const version of response.Versions ?? []) {
        if (!version.Key || version.Key !== key || !version.VersionId) continue;
        items.push({
          versionId: version.VersionId,
          lastModified: version.LastModified ?? null,
          size: version.Size ?? 0,
          isLatest: version.IsLatest ?? false,
          isDeleteMarker: false,
        });
      }

      for (const marker of response.DeleteMarkers ?? []) {
        if (!marker.Key || marker.Key !== key || !marker.VersionId) continue;
        items.push({
          versionId: marker.VersionId,
          lastModified: marker.LastModified ?? null,
          size: 0,
          isLatest: marker.IsLatest ?? false,
          isDeleteMarker: true,
        });
      }

      keyMarker = response.IsTruncated ? response.NextKeyMarker : undefined;
      versionIdMarker = response.IsTruncated
        ? response.NextVersionIdMarker
        : undefined;
    } while (keyMarker || versionIdMarker);

    return items.sort((a, b) => {
      const aTime = a.lastModified?.getTime() ?? 0;
      const bTime = b.lastModified?.getTime() ?? 0;
      return bTime - aTime;
    });
  }

  async listKeysWithVersions(prefix: string): Promise<
    Array<{
      key: string;
      lastModified: Date | null;
      size: number;
      isDeleted: boolean;
    }>
  > {
    const byKey = new Map<
      string,
      { lastModified: Date | null; size: number; isDeleted: boolean }
    >();

    let keyMarker: string | undefined;
    let versionIdMarker: string | undefined;

    do {
      const response = await this.client.send(
        new ListObjectVersionsCommand({
          Bucket: this.env.S3_BUCKET_NAME,
          Prefix: prefix,
          KeyMarker: keyMarker,
          VersionIdMarker: versionIdMarker,
        }),
      );

      for (const version of response.Versions ?? []) {
        if (!version.Key || !version.IsLatest) continue;
        byKey.set(version.Key, {
          lastModified: version.LastModified ?? null,
          size: version.Size ?? 0,
          isDeleted: false,
        });
      }

      for (const marker of response.DeleteMarkers ?? []) {
        if (!marker.Key || !marker.IsLatest) continue;
        byKey.set(marker.Key, {
          lastModified: marker.LastModified ?? null,
          size: 0,
          isDeleted: true,
        });
      }

      keyMarker = response.IsTruncated ? response.NextKeyMarker : undefined;
      versionIdMarker = response.IsTruncated
        ? response.NextVersionIdMarker
        : undefined;
    } while (keyMarker || versionIdMarker);

    return Array.from(byKey, ([key, value]) => ({ key, ...value })).sort(
      (a, b) => {
        const aTime = a.lastModified?.getTime() ?? 0;
        const bTime = b.lastModified?.getTime() ?? 0;
        return bTime - aTime;
      },
    );
  }
}
