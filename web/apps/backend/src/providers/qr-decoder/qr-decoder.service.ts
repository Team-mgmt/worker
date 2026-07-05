import { readFileSync } from "node:fs";

import { Injectable } from "@nestjs/common";

import {
  prepareZXingModule,
  readBarcodes,
  type ReadResult,
} from "zxing-wasm/reader";

@Injectable()
export class QrDecoderService {
  private wasmReady: Promise<void> | null = null;

  private ensureWasm(): Promise<void> {
    if (!this.wasmReady) {
      this.wasmReady = this.loadWasm();
    }
    return this.wasmReady;
  }

  private async loadWasm(): Promise<void> {
    const wasmPath = require.resolve("zxing-wasm/reader/zxing_reader.wasm");
    const wasmBuffer = readFileSync(wasmPath);
    await prepareZXingModule({
      overrides: {
        instantiateWasm(
          imports: WebAssembly.Imports,
          successCallback: (instance: WebAssembly.Instance) => void,
        ) {
          WebAssembly.instantiate(wasmBuffer, imports)
            .then(({ instance }) => successCallback(instance))
            .catch(() => {});
          return {};
        },
      },
      fireImmediately: true,
    });
  }

  async decode(image: Buffer): Promise<ReadResult[]> {
    await this.ensureWasm();
    return readBarcodes(new Uint8Array(image), {
      formats: ["QRCode"],
      tryHarder: true,
      tryRotate: true,
      tryInvert: true,
      tryDownscale: true,
    });
  }
}
