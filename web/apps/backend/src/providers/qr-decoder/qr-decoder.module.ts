import { Module } from "@nestjs/common";

import { QrDecoderService } from "./qr-decoder.service";

@Module({
  providers: [QrDecoderService],
  exports: [QrDecoderService],
})
export class QrDecoderModule {}
