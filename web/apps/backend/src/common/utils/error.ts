import { Logger } from "@nestjs/common";

import { v7 as uuidv7 } from "uuid";

import { uuidToBase64Url } from "./string";

export function createDigest(logger: Logger, message: string) {
  const digest = uuidToBase64Url(uuidv7());
  logger.error(`${digest} - ${message}`);
  return digest;
}
