import { createZodDto } from "nestjs-zod";

import {
  AdminCreateDocumentRequestSchema,
  AdminCreateDocumentResponseSchema,
  AdminDeleteDocumentResponseSchema,
  AdminGetDocumentQuerySchema,
  AdminGetDocumentResponseSchema,
  AdminListDocumentsQuerySchema,
  AdminListDocumentsResponseSchema,
  AdminListDocumentVersionsResponseSchema,
  AdminRestoreDocumentVersionRequestSchema,
  AdminRestoreDocumentVersionResponseSchema,
  AdminUpdateDocumentRequestSchema,
  AdminUpdateDocumentResponseSchema,
} from "@shelfalign/schema/dtos/admin/document";

export class ListDocumentsQueryDto extends createZodDto(
  AdminListDocumentsQuerySchema,
) {}
export class ListDocumentsResponseDto extends createZodDto(
  AdminListDocumentsResponseSchema,
) {}

export class GetDocumentQueryDto extends createZodDto(
  AdminGetDocumentQuerySchema,
) {}
export class GetDocumentResponseDto extends createZodDto(
  AdminGetDocumentResponseSchema,
) {}

export class ListDocumentVersionsResponseDto extends createZodDto(
  AdminListDocumentVersionsResponseSchema,
) {}

export class CreateDocumentRequestDto extends createZodDto(
  AdminCreateDocumentRequestSchema,
) {}
export class CreateDocumentResponseDto extends createZodDto(
  AdminCreateDocumentResponseSchema,
) {}

export class UpdateDocumentRequestDto extends createZodDto(
  AdminUpdateDocumentRequestSchema,
) {}
export class UpdateDocumentResponseDto extends createZodDto(
  AdminUpdateDocumentResponseSchema,
) {}

export class DeleteDocumentResponseDto extends createZodDto(
  AdminDeleteDocumentResponseSchema,
) {}

export class RestoreDocumentVersionRequestDto extends createZodDto(
  AdminRestoreDocumentVersionRequestSchema,
) {}
export class RestoreDocumentVersionResponseDto extends createZodDto(
  AdminRestoreDocumentVersionResponseSchema,
) {}
