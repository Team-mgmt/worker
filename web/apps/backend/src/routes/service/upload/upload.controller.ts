import { Body, Controller, Post, UseGuards } from "@nestjs/common";
import { Throttle } from "@nestjs/throttler";

import { ZodSerializerDto } from "nestjs-zod";

import { GUEST_ORGANIZATION_ID } from "@/common/constants";
import { Organization } from "@/common/decorators/organization.decorator";
import { UserId } from "@/common/decorators/user-id.decorator";
import { AuthGuard } from "@/common/guards/auth.guard";
import { TurnstileGuard } from "@/common/guards/turnstile.guard";
import { handleDateTime } from "@/common/utils/zod";

import {
  GeneratePresignedUrlRequestDto,
  GeneratePresignedUrlResponseDto,
} from "./upload.schema";
import { UploadService } from "./upload.service";

@Controller("/service/upload")
export class UploadController {
  constructor(private readonly uploadService: UploadService) {}

  // 30/min per authed user is generous for normal interactive use (one upload
  // every two seconds sustained) but will catch loops that try to enumerate
  // presigned URLs or spam UploadFile rows.
  @Post()
  @UseGuards(AuthGuard())
  @Throttle({ default: { ttl: 60_000, limit: 30 } })
  @ZodSerializerDto(GeneratePresignedUrlResponseDto)
  async createPresignedUrl(
    @Organization() organizationId: string,
    @UserId() userId: string,
    @Body() body: GeneratePresignedUrlRequestDto,
  ): Promise<GeneratePresignedUrlResponseDto> {
    const data = await this.uploadService.createPresignedUrl({
      organizationId,
      createdById: userId,
      filename: body.filename,
      contentType: body.contentType,
      size: body.size,
    });

    return handleDateTime({
      result: true,
      data,
    }) satisfies GeneratePresignedUrlResponseDto;
  }

  // User-scoped uploads (e.g. profile pictures): the file ends up on `User`,
  // not on an OrganizationMember, so we don't require an active org context.
  // The UploadFile row is partitioned under GUEST_ORGANIZATION_ID; `createdById`
  // is what actually identifies ownership for downstream validation.
  @Post("/me")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @Throttle({ default: { ttl: 60_000, limit: 30 } })
  @ZodSerializerDto(GeneratePresignedUrlResponseDto)
  async createUserPresignedUrl(
    @UserId() userId: string,
    @Body() body: GeneratePresignedUrlRequestDto,
  ): Promise<GeneratePresignedUrlResponseDto> {
    const data = await this.uploadService.createPresignedUrl({
      organizationId: GUEST_ORGANIZATION_ID,
      createdById: userId,
      filename: body.filename,
      contentType: body.contentType,
      size: body.size,
    });

    return handleDateTime({
      result: true,
      data,
    }) satisfies GeneratePresignedUrlResponseDto;
  }

  // Guests pass Turnstile per request, so the bot floor is high. Keep the
  // bucket tighter than authed since there's no user identity to attribute
  // abuse to and lifecycle expiry is the only cleanup.
  @Post("/guest")
  @UseGuards(TurnstileGuard({ skipIfAuthenticated: true }))
  @Throttle({ default: { ttl: 60_000, limit: 10 } })
  @ZodSerializerDto(GeneratePresignedUrlResponseDto)
  async createGuestPresignedUrl(
    @Body() body: GeneratePresignedUrlRequestDto,
  ): Promise<GeneratePresignedUrlResponseDto> {
    const data = await this.uploadService.createPresignedUrl({
      organizationId: GUEST_ORGANIZATION_ID,
      createdById: null,
      filename: body.filename,
      contentType: body.contentType,
      size: body.size,
    });

    return handleDateTime({
      result: true,
      data,
    }) satisfies GeneratePresignedUrlResponseDto;
  }
}
