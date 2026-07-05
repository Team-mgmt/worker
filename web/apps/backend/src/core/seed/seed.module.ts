import { Module } from "@nestjs/common";

import { S3Module } from "@/providers/s3/s3.module";

import { SeedService } from "./seed.service";

@Module({
  imports: [S3Module],
  providers: [SeedService],
})
export class SeedModule {}
