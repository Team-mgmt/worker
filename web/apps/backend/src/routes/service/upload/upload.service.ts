import { Inject, Injectable } from "@nestjs/common";

import * as mimeDB from "mime-db";
import { v7 as uuidv7 } from "uuid";

import { EnvType, registerEnv } from "@/common/utils/env";
import { PrismaService } from "@/providers/database/prisma.service";
import { S3Service } from "@/providers/s3/s3.service";

// Strip C0 (U+0000–U+001F) and C1 (U+007F–U+009F) control characters from the
// filename. These can break logging, terminal output, CSV exports, and any
// place the filename is concatenated into a header or shell command. NFC
// normalization makes the stored value canonical so equality checks against
// it (e.g., from a Lambda event) don't depend on the OS the upload came from
// (macOS hands files in NFD, others in NFC).
function sanitizeFilename(value: string): string {
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\u0000-\u001F\u007F-\u009F]/gu, "").normalize("NFC");
}

type CreatePresignedUrlInput = {
  organizationId: string;
  createdById: string | null;
  filename: string;
  contentType: string;
  size: number;
};

@Injectable()
export class UploadService {
  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
    private readonly s3Service: S3Service,
    private readonly prismaService: PrismaService,
  ) {}

  async createPresignedUrl(input: CreatePresignedUrlInput) {
    const ext = mimeDB[input.contentType]?.extensions?.[0] ?? "bin";
    const id = uuidv7();
    const key = `${input.organizationId}/uploads/${id}.${ext}`;
    const filename = sanitizeFilename(input.filename);

    const uploadUrl = await this.s3Service.generatePresignedUploadUrl({
      Bucket: this.env.S3_BUCKET_NAME,
      Key: key,
      ContentType: input.contentType,
      ContentLength: input.size,
      ACL: "private",
      Tagging: this.s3Service.toTagging({ type: "temporary" }),
    });

    const uploadFile = await this.prismaService.uploadFile.create({
      data: {
        id,
        organizationId: input.organizationId,
        createdById: input.createdById,
        key,
        filename,
        contentType: input.contentType,
        size: input.size,
      },
    });

    return {
      uploadUrl,
      key,
      uploadFileId: uploadFile.id,
    };
  }
}
