import {
  Body,
  Controller,
  Delete,
  Get,
  Patch,
  Query,
  UseGuards,
} from "@nestjs/common";

import { ZodSerializerDto, ZodValidationPipe } from "nestjs-zod";

import { ParamId } from "@/common/decorators/param-id.decorator";
import { AuthGuard } from "@/common/guards/auth.guard";
import { PaginationQueryDto } from "@/common/schema/pagination.schema";
import { handleDateTime } from "@/common/utils/zod";

import {
  DeleteOrganizationResponseDto,
  ListOrganizationsResponseDto,
  OrganizationResponseDto,
  UpdateOrganizationDto,
} from "./organization.schema";
import { AdminOrganizationService } from "./organization.service";

@UseGuards(AuthGuard({ roles: ["ADMIN"] }))
@Controller("/admin/organizations")
export class AdminOrganizationController {
  constructor(private readonly organizationService: AdminOrganizationService) {}

  @Get()
  @ZodSerializerDto(ListOrganizationsResponseDto)
  async list(
    @Query() pagination: PaginationQueryDto,
  ): Promise<ListOrganizationsResponseDto> {
    const { organizations, count } =
      await this.organizationService.list(pagination);
    return handleDateTime({
      result: true,
      data: organizations,
      count,
    }) satisfies ListOrganizationsResponseDto;
  }

  @Get(":id")
  @ZodSerializerDto(OrganizationResponseDto)
  async get(@ParamId("id") id: string): Promise<OrganizationResponseDto> {
    const organization = await this.organizationService.get(id);
    return {
      result: true,
      data: handleDateTime(organization),
    };
  }

  @Patch(":id")
  @ZodSerializerDto(OrganizationResponseDto)
  async update(
    @ParamId("id") id: string,
    @Body(new ZodValidationPipe(UpdateOrganizationDto))
    updateOrganizationDto: UpdateOrganizationDto,
  ): Promise<OrganizationResponseDto> {
    const organization = await this.organizationService.update(
      id,
      updateOrganizationDto,
    );
    return handleDateTime({
      result: true,
      data: organization,
    }) satisfies OrganizationResponseDto;
  }

  @Delete(":id")
  @ZodSerializerDto(DeleteOrganizationResponseDto)
  async remove(
    @ParamId("id") id: string,
  ): Promise<DeleteOrganizationResponseDto> {
    await this.organizationService.remove(id);
    return handleDateTime({
      result: true,
    }) satisfies DeleteOrganizationResponseDto;
  }
}
