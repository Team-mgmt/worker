import { Controller, Get, HttpException, HttpStatus } from "@nestjs/common";

import { CacheService } from "./providers/cache/cache.service";

@Controller()
export class AppController {
  constructor(private readonly cacheService: CacheService) {}

  @Get("/")
  getStatus() {
    return "";
  }

  @Get("/health")
  async getHealth() {
    const cache = await this.cacheService.isHealthy();
    if (!cache) {
      throw new HttpException(
        { status: "unhealthy", cache },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    return { status: "ok", cache };
  }
}
