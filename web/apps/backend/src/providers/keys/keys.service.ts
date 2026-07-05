import fs from "node:fs/promises";
import path from "node:path";

import {
  BadRequestException,
  Inject,
  Injectable,
  InternalServerErrorException,
  Logger,
} from "@nestjs/common";

import {
  GetSecretValueCommand,
  SecretsManagerClient,
} from "@aws-sdk/client-secrets-manager";
import jose from "jose";

import { EnvType, registerEnv } from "@/common/utils/env";
import { createDigest } from "@/common/utils/error";

import {
  KeyChainSchema,
  LocalKeyFileSchema,
  ParsedKeyChain,
} from "./keys.schema";

@Injectable()
export class KeyService {
  private readonly logger = new Logger(KeyService.name);

  private readonly client!: SecretsManagerClient;

  private keys: Record<string, ParsedKeyChain> = {};

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
  ) {
    const accessKeyId = this.env.AWS_ACCESS_KEY_ID;
    const secretAccessKey = this.env.AWS_SECRET_ACCESS_KEY;
    const sessionToken = this.env.AWS_SESSION_TOKEN;

    this.client = new SecretsManagerClient({
      credentials:
        accessKeyId && secretAccessKey
          ? {
              accessKeyId,
              secretAccessKey,
              sessionToken,
            }
          : undefined,
    });
  }

  private async loadLocalKeys(keyFile: string) {
    if (!["test", "local"].includes(this.env.NODE_ENV)) {
      throw new Error(
        "Local keys can only be loaded in test or local environment",
      );
    }

    const data = LocalKeyFileSchema.parse(
      JSON.parse(await fs.readFile(keyFile, "utf-8")),
    );
    const privateKey = await crypto.subtle.importKey(
      "jwk",
      data.privateKey,
      { name: "ECDSA", namedCurve: "P-521" },
      true,
      ["sign"],
    );
    const publicKey = await crypto.subtle.importKey(
      "jwk",
      data.publicKey,
      { name: "ECDSA", namedCurve: "P-521" },
      true,
      ["verify"],
    );
    return { private: privateKey, public: publicKey };
  }

  private async generateLocalKeys(keyId: string) {
    if (!["test", "local"].includes(this.env.NODE_ENV)) {
      throw new Error(
        "Local keys can only be loaded in test or local environment",
      );
    }

    const keysDir = path.join(process.cwd(), "..", "..", "local-data", "keys");
    const safeKeyId = keyId.replaceAll(/[^a-zA-Z0-9_-]/g, "_");
    const keyFile = path.join(keysDir, `${safeKeyId}.json`);
    const kid = "local-key";

    try {
      const keyPair = await this.loadLocalKeys(keyFile);
      this.keys[keyId] = {
        latestKeyId: kid,
        keys: { [kid]: keyPair },
      };
      this.logger.log("Loaded local keys from local-data/keys");
      return;
    } catch {
      // Key file doesn't exist or is invalid, generate new keys
    }

    this.logger.warn("Generating local keys for test/local mode");

    const keyPair = await crypto.subtle.generateKey(
      { name: "ECDSA", namedCurve: "P-521" },
      true,
      ["sign", "verify"],
    );

    const privateJwk = await crypto.subtle.exportKey("jwk", keyPair.privateKey);
    const publicJwk = await crypto.subtle.exportKey("jwk", keyPair.publicKey);

    await fs.mkdir(keysDir, { recursive: true });
    await fs.writeFile(
      keyFile,
      JSON.stringify({ privateKey: privateJwk, publicKey: publicJwk }, null, 2),
    );
    this.logger.log("Saved local keys to local-data/keys");

    this.keys[keyId] = {
      latestKeyId: kid,
      keys: {
        [kid]: {
          private: keyPair.privateKey,
          public: keyPair.publicKey,
        },
      },
    };
  }

  async fetchKeys(keyId: string) {
    if (this.env.NODE_ENV === "test" || this.env.NODE_ENV === "local") {
      await this.generateLocalKeys(keyId);
      return;
    }

    const rawKeys = await this.client.send(
      new GetSecretValueCommand({
        SecretId: keyId,
      }),
    );

    if (!rawKeys.SecretString) {
      const digest = createDigest(
        this.logger,
        "Failed to fetch keys from Secrets Manager",
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const keychain = (() => {
      try {
        const json = JSON.parse(rawKeys.SecretString);
        return KeyChainSchema.parse(json);
      } catch {
        const digest = createDigest(
          this.logger,
          `Failed to parse keys from Secrets Manager: ${rawKeys.SecretString}`,
        );
        throw new InternalServerErrorException({
          code: "INTERNAL_ERROR",
          params: { digest },
        });
      }
    })();

    const parsedKeys = await Promise.all(
      Object.entries(keychain)
        .filter(([key]) => key !== "LATEST_KEY_ID")
        .map(async ([kid, key]) => ({
          kid,
          key: await jose.importPKCS8(key, "ES512", { extractable: true }),
        })),
    );

    this.keys[keyId] = {
      latestKeyId: keychain.LATEST_KEY_ID,
      keys: {},
    } as ParsedKeyChain;

    for (const { kid, key: privateKey } of parsedKeys) {
      const privateJwk = await jose.exportJWK(privateKey);
      const algorithm = privateKey.algorithm as EcKeyAlgorithm;

      const publicKey = await crypto.subtle.importKey(
        "jwk",
        {
          kty: "EC",
          crv: privateJwk.crv,
          x: privateJwk.x,
          y: privateJwk.y,
          ext: true,
        },
        { name: algorithm.name, namedCurve: algorithm.namedCurve },
        true,
        ["verify"],
      );

      this.keys[keyId].keys[kid] = { private: privateKey, public: publicKey };
    }
  }

  async getLatestKey(keyId: string) {
    if (!(keyId in this.keys)) {
      await this.fetchKeys(keyId);
    }

    if (!this.keys[keyId]) {
      const digest = createDigest(
        this.logger,
        `Keys for keyId ${keyId} not found after fetch`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const keys = this.keys[keyId].keys[this.keys[keyId].latestKeyId];
    if (!keys) {
      const digest = createDigest(
        this.logger,
        `Latest key for keyId ${keyId} not found after fetch`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    return {
      keyId: this.keys[keyId].latestKeyId,
      key: keys,
    };
  }

  async validateToken(
    keyId: string,
    token: string,
    ignoreExpiration: boolean = false,
  ) {
    if (!(keyId in this.keys)) {
      await this.fetchKeys(keyId);
    }

    if (!this.keys[keyId]) {
      const digest = createDigest(
        this.logger,
        `Keys for keyId ${keyId} not found after fetch`,
      );
      throw new InternalServerErrorException({
        code: "INTERNAL_ERROR",
        params: { digest },
      });
    }

    const header = await jose.decodeProtectedHeader(token);
    if (!header.kid) {
      const digest = createDigest(this.logger, `Token missing kid in header`);
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: { digest },
      });
    }

    let keys = this.keys[keyId].keys[header.kid];
    if (!keys) {
      await this.fetchKeys(keyId);
      keys = this.keys[keyId]?.keys[header.kid];
    }

    if (!keys) {
      const digest = createDigest(
        this.logger,
        `Token has unknown kid ${header.kid} for keyId ${keyId}`,
      );
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: { digest },
      });
    }

    try {
      const result = await jose.jwtVerify(token, keys.public, {
        algorithms: ["ES512"],
        clockTolerance: ignoreExpiration ? Number.POSITIVE_INFINITY : 0,
      });

      return result;
    } catch (e: unknown) {
      if (e instanceof jose.errors.JWTExpired) {
        throw new BadRequestException({
          code: "TOKEN_EXPIRED",
          params: {},
        });
      }

      this.logger.error(e);
      const digest = createDigest(
        this.logger,
        `Failed to verify token for keyId ${keyId}: ${(e as Error).message}`,
      );
      throw new BadRequestException({
        code: "INVALID_TOKEN",
        params: { digest },
      });
    }
  }
}
