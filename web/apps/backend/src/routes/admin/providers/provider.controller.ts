import { Controller, Delete, Get, Query, UseGuards } from "@nestjs/common";

import { ZodSerializerDto } from "nestjs-zod";

import { ParamId } from "@/common/decorators/param-id.decorator";
import { AuthGuard } from "@/common/guards/auth.guard";
import { PaginationQueryDto } from "@/common/schema/pagination.schema";
import { handleDateTime } from "@/common/utils/zod";

import {
  DeleteProviderResponseDto,
  ListProvidersResponseDto,
  ProviderResponseDto,
} from "./provider.schema";
import { AdminProviderService } from "./provider.service";

@UseGuards(AuthGuard({ roles: ["ADMIN"] }))
@Controller("/admin/providers")
export class AdminProviderController {
  constructor(private readonly providerService: AdminProviderService) {}

  @Get()
  @ZodSerializerDto(ListProvidersResponseDto)
  async list(
    @Query() pagination: PaginationQueryDto,
  ): Promise<ListProvidersResponseDto> {
    const { providers, count } = await this.providerService.list(pagination);
    return handleDateTime({
      result: true,
      data: providers,
      count,
    }) satisfies ListProvidersResponseDto;
  }

  @Get(":id")
  @ZodSerializerDto(ProviderResponseDto)
  async get(@ParamId("id") id: string): Promise<ProviderResponseDto> {
    const provider = await this.providerService.get(id);
    return {
      result: true,
      data: handleDateTime(provider),
    };
  }

  @Delete(":id")
  @ZodSerializerDto(DeleteProviderResponseDto)
  async remove(@ParamId("id") id: string): Promise<DeleteProviderResponseDto> {
    await this.providerService.remove(id);
    return handleDateTime({
      result: true,
    }) satisfies DeleteProviderResponseDto;
  }
}
