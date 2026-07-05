import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  Patch,
  Post,
  Query,
  UseGuards,
} from "@nestjs/common";

import { ZodSerializerDto } from "nestjs-zod";

import { AuthGuard } from "@/common/guards/auth.guard";
import { handleDateTime } from "@/common/utils/zod";

import {
  CreateDocumentRequestDto,
  CreateDocumentResponseDto,
  DeleteDocumentResponseDto,
  GetDocumentQueryDto,
  GetDocumentResponseDto,
  ListDocumentsQueryDto,
  ListDocumentsResponseDto,
  ListDocumentVersionsResponseDto,
  RestoreDocumentVersionRequestDto,
  RestoreDocumentVersionResponseDto,
  UpdateDocumentRequestDto,
  UpdateDocumentResponseDto,
} from "./document.schema";
import { AdminDocumentService } from "./document.service";

@UseGuards(AuthGuard({ roles: ["ADMIN"] }))
@Controller("/admin/documents")
export class AdminDocumentController {
  constructor(private readonly documentService: AdminDocumentService) {}

  @Get()
  @ZodSerializerDto(ListDocumentsResponseDto)
  async listDocuments(
    @Query() query: ListDocumentsQueryDto,
  ): Promise<ListDocumentsResponseDto> {
    const documents = await this.documentService.listDocuments(
      query.includeDeleted ?? false,
    );

    return handleDateTime({
      result: true,
      data: documents,
    }) satisfies ListDocumentsResponseDto;
  }

  @Post()
  @ZodSerializerDto(CreateDocumentResponseDto)
  async createDocument(
    @Body() body: CreateDocumentRequestDto,
  ): Promise<CreateDocumentResponseDto> {
    const summary = await this.documentService.createDocument(
      body.slug,
      body.content,
    );

    return handleDateTime({
      result: true,
      data: summary,
    }) satisfies CreateDocumentResponseDto;
  }

  @Get(":slug")
  @ZodSerializerDto(GetDocumentResponseDto)
  async getDocument(
    @Param("slug") slug: string,
    @Query() query: GetDocumentQueryDto,
  ): Promise<GetDocumentResponseDto> {
    const document = await this.documentService.getDocument(
      slug,
      query.versionId,
    );

    return handleDateTime({
      result: true,
      data: document,
    }) satisfies GetDocumentResponseDto;
  }

  @Get(":slug/versions")
  @ZodSerializerDto(ListDocumentVersionsResponseDto)
  async listVersions(
    @Param("slug") slug: string,
  ): Promise<ListDocumentVersionsResponseDto> {
    const versions = await this.documentService.listDocumentVersions(slug);

    return handleDateTime({
      result: true,
      data: versions,
    }) satisfies ListDocumentVersionsResponseDto;
  }

  @Patch(":slug")
  @ZodSerializerDto(UpdateDocumentResponseDto)
  async updateDocument(
    @Param("slug") slug: string,
    @Body() body: UpdateDocumentRequestDto,
  ): Promise<UpdateDocumentResponseDto> {
    const summary = await this.documentService.updateDocument(
      slug,
      body.content,
    );

    return handleDateTime({
      result: true,
      data: summary,
    }) satisfies UpdateDocumentResponseDto;
  }

  @Delete(":slug")
  @ZodSerializerDto(DeleteDocumentResponseDto)
  async deleteDocument(
    @Param("slug") slug: string,
  ): Promise<DeleteDocumentResponseDto> {
    await this.documentService.deleteDocument(slug);

    return {
      result: true,
    } satisfies DeleteDocumentResponseDto;
  }

  @Post(":slug/restore")
  @ZodSerializerDto(RestoreDocumentVersionResponseDto)
  async restoreVersion(
    @Param("slug") slug: string,
    @Body() body: RestoreDocumentVersionRequestDto,
  ): Promise<RestoreDocumentVersionResponseDto> {
    const summary = await this.documentService.restoreVersion(
      slug,
      body.versionId,
    );

    return handleDateTime({
      result: true,
      data: summary,
    }) satisfies RestoreDocumentVersionResponseDto;
  }
}
