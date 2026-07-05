import { readFileSync } from "node:fs";
import { join } from "node:path";
import url from "node:url";

import { Inject, Injectable, Logger, type OnModuleInit } from "@nestjs/common";

import { Sha256 } from "@aws-crypto/sha256-js";
import { defaultProvider } from "@aws-sdk/credential-provider-node";
import { CrtSignerV4 } from "@aws-sdk/signature-v4-crt";
import type { HttpRequest } from "@smithy/types";
import { Cluster, Redis as Valkey } from "iovalkey";
import { v7 as uuidv7 } from "uuid";

import { EnvType, registerEnv } from "@/common/utils/env";
import { redactErrorForLog } from "@/common/utils/redact-error";

// Resolved relative to the compiled file so it works both in dev (src/scripts/)
// and in dist/ (copied via nest-cli.json assets). `apps/backend/scripts/` is a
// dev-only folder and is NOT bundled into the docker runtime image.
const VALKEY_FUNCTIONS_LUA_PATH = join(
  __dirname,
  "../../scripts/valkey-unlock.lua",
);

// Recreate the cluster client after this many consecutive slot-refresh
// failures. iovalkey will keep retrying internally but a transient cold-start
// failure can leave the cluster object wedged forever; recreating from
// scratch lets the process self-heal without a redeploy.
const SLOT_REFRESH_RECREATE_THRESHOLD = 5;

// Backoff schedule for re-attempting AUTH after a transient
// "ERR IAM Authentication service is not available" reply. AWS documents this
// error class as retryable; one transient response should not waste an entire
// 9.6h reauth window because that lets the 12h IAM token expire.
const REAUTH_RETRY_DELAYS_MS = [1000, 2000, 4000] as const;

const isTransientIamAuthError = (error: unknown): boolean =>
  error instanceof Error &&
  /IAM Authentication service is not available/i.test(error.message);

@Injectable()
export class CacheService implements OnModuleInit {
  private readonly logger = new Logger(CacheService.name);
  private reauthTimer!: NodeJS.Timeout;
  private slotRefreshFailures = 0;
  private isRecreating = false;

  client!: Valkey | Cluster;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
  ) {}

  private get isStaticCredential() {
    return Boolean(this.env.CACHE_PASSWORD);
  }

  async onModuleInit() {
    await this.connect();

    if (this.env.CACHE_SINGLE_NODE === "true" || this.isStaticCredential) {
      return;
    }

    // AWS drops IAM-authenticated connections after 12 hours
    this.reauthTimer = setInterval(
      () => {
        void this.reauth();
      },
      12 * 60 * 60 * 1000 * 0.8,
    );
  }

  async onModuleDestroy() {
    clearInterval(this.reauthTimer);
    await this.client.quit().catch(() => this.client.disconnect());
  }

  // Refresh the IAM token and AUTH every node. Retries on transient
  // "IAM Authentication service is not available" replies — without this, a
  // single transient response loses the 12h connection because the next reauth
  // is scheduled 9.6h later.
  private async reauth() {
    this.logger.log("Reauthenticating cache connection");
    const username = this.env.CACHE_USERNAME;
    const maxAttempts = REAUTH_RETRY_DELAYS_MS.length + 1;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const [password] = await this.getPassword();
        await this.applyAuthToAllNodes(username, password);
        return;
      } catch (error) {
        const safe = redactErrorForLog(error);
        const isLastAttempt = attempt === maxAttempts;
        if (isLastAttempt || !isTransientIamAuthError(error)) {
          this.logger.error(
            `Error during cache reauthentication: ${safe.message}`,
            safe.stack,
          );
          return;
        }
        const delayMs = REAUTH_RETRY_DELAYS_MS[attempt - 1];
        this.logger.warn(
          `Transient IAM auth during reauth (attempt ${attempt}/${maxAttempts}): ${safe.message} — retrying in ${delayMs}ms`,
        );
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
  }

  private async applyAuthToAllNodes(username: string, password: string) {
    if (this.client instanceof Valkey) {
      await this.client.auth(username, password);
      this.client.options.password = password;
      return;
    }
    for (const node of this.client.nodes()) {
      await node.auth(username, password);
    }
    this.client.options.redisOptions = {
      ...(this.client.options.redisOptions ?? {}),
      password,
    };
  }

  private async connect() {
    const host = this.env.CACHE_HOST;
    const port = this.env.CACHE_PORT;
    const username = this.env.CACHE_USERNAME;
    const [password] = await this.getPassword();

    const isInsecure = this.env.CACHE_INSECURE === "true";
    const tlsOptions = isInsecure ? {} : { tls: {} };

    if (this.env.CACHE_SINGLE_NODE === "true") {
      this.client = new Valkey({ host, port, ...tlsOptions });
      await this.loadValkeyFunctions();
      return;
    }

    this.client = new Valkey.Cluster([{ host, port }], {
      dnsLookup: (hostname, callback) => callback(null, hostname),
      redisOptions: {
        username,
        password,
        reconnectOnError: (err) =>
          /\b(WRONGPASS|NOAUTH)\b/i.test(err.message) ? 1 : false,
        ...tlsOptions,
      },
      slotsRefreshTimeout: 5000,
    });

    this.client.on("ready", () => {
      this.slotRefreshFailures = 0;
    });

    this.client.on("error", (err: Error) => {
      if (
        !/Failed to refresh slots cache|ClusterAllFailedError/i.test(
          err.message,
        )
      ) {
        return;
      }
      this.slotRefreshFailures++;
      if (this.slotRefreshFailures >= SLOT_REFRESH_RECREATE_THRESHOLD) {
        void this.recreate();
      }
    });

    this.client.on("reconnecting", async () => {
      if (this.isStaticCredential) {
        return;
      }

      try {
        const [password] = await this.getPassword();
        if (this.client instanceof Valkey) {
          this.client.options.password = password;
        } else {
          this.client.options.redisOptions = {
            ...(this.client.options.redisOptions ?? {}),
            password,
          };
        }
      } catch (error) {
        const safe = redactErrorForLog(error);
        this.logger.error(
          `Error updating cache password on reconnect: ${safe.message}`,
          safe.stack,
        );
      }
    });
  }

  private async recreate() {
    if (this.isRecreating) {
      return;
    }
    this.isRecreating = true;

    this.logger.warn(
      `Recreating cache client after ${this.slotRefreshFailures} consecutive slot-refresh failures`,
    );

    const old = this.client;
    old.removeAllListeners("error");
    old.removeAllListeners("ready");
    old.removeAllListeners("reconnecting");

    try {
      await old.quit().catch(() => old.disconnect());
    } catch (error) {
      const safe = redactErrorForLog(error);
      this.logger.error(
        `Error disposing wedged cache client: ${safe.message}`,
        safe.stack,
      );
    }

    this.slotRefreshFailures = 0;

    try {
      await this.connect();
    } catch (error) {
      const safe = redactErrorForLog(error);
      this.logger.error(
        `Error recreating cache client: ${safe.message}`,
        safe.stack,
      );
    } finally {
      this.isRecreating = false;
    }
  }

  // Liveness probe used by /health. Returns false if the cluster has not
  // reached "ready" or if PING does not return PONG within 3 seconds, so a
  // wedged task surfaces as an unhealthy container to ECS.
  async isHealthy(): Promise<boolean> {
    if (this.client.status !== "ready") {
      return false;
    }
    try {
      const result = await Promise.race([
        this.client.ping(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("cache ping timeout")), 3000),
        ),
      ]);
      return result === "PONG";
    } catch (error) {
      const safe = redactErrorForLog(error);
      this.logger.warn(
        `Cache health check failed: ${safe.message}`,
        safe.stack,
      );
      return false;
    }
  }

  async loadValkeyFunctions(): Promise<void> {
    const source = readFileSync(VALKEY_FUNCTIONS_LUA_PATH, "utf8");
    // FUNCTION LOAD is keyless, so in cluster mode iovalkey routes it to one
    // random master. FCALL with a key is then routed to the slot owner, which
    // throws function-not-found if it hasn't seen the load. Load on every
    // master so any shard can serve later FCALL traffic.
    //
    // Cluster#nodes() reads connectionPool synchronously and does NOT wait for
    // slot discovery. If we read it while status is still "connecting", we get
    // only the seed nodes and silently load the function on a subset of
    // shards. Wait for "ready" first so we see every master.
    if (this.client instanceof Cluster && this.client.status !== "ready") {
      await new Promise<void>((resolve, reject) => {
        const onReady = () => {
          this.client.off("error", onError);
          resolve();
        };
        const onError = (err: Error) => {
          this.client.off("ready", onReady);
          reject(err);
        };
        this.client.once("ready", onReady);
        this.client.once("error", onError);
      });
    }

    const targets =
      this.client instanceof Cluster
        ? this.client.nodes("master")
        : [this.client];
    if (targets.length === 0) {
      throw new Error(
        "FUNCTION LOAD REPLACE aborted: no master nodes discovered. " +
          "Cluster slot discovery may have failed.",
      );
    }
    try {
      await Promise.all(
        targets.map((node) => node.call("FUNCTION", "LOAD", "REPLACE", source)),
      );
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(
        `FUNCTION LOAD REPLACE failed: ${detail}. ` +
          `Valkey functions could not be registered from ${VALKEY_FUNCTIONS_LUA_PATH}.`,
      );
    }
  }

  // FCALL wrapper that self-heals against shards missing the 'shelfalign' function
  // library. A shard can lack the library after scale-out or after a replica
  // is promoted to master before the initial FUNCTION LOAD propagated. On
  // "Function not found", reload the library on every currently-discovered
  // master and retry the call once.
  async callFunction(
    functionName: string,
    numKeys: number,
    ...args: (string | number)[]
  ): Promise<unknown> {
    try {
      return await this.client.call("FCALL", functionName, numKeys, ...args);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      if (!/Function not found/i.test(detail)) {
        throw error;
      }

      this.logger.warn(
        `FCALL ${functionName}: function not found — reloading Valkey function library and retrying`,
      );
      await this.loadValkeyFunctions();
      return await this.client.call("FCALL", functionName, numKeys, ...args);
    }
  }

  // Acquire a distributed lock. Returns a UUIDv7 token on success, null if the
  // key is already held. Release via unlock() with the same token.
  async lock(key: string, timeoutSec: number): Promise<string | null> {
    const value = uuidv7();
    const result = await this.client.set(key, value, "EX", timeoutSec, "NX");
    return result === "OK" ? value : null;
  }

  // Compare-and-delete unlock via the 'shelfalign' Valkey Function library. Only
  // succeeds if the stored value matches the token we acquired with lock().
  async unlock(key: string, value: string): Promise<boolean> {
    const result = await this.callFunction("unlock", 1, key, value);
    return result === 1;
  }

  private async getPassword() {
    const rawPassword = this.env.CACHE_PASSWORD;
    if (rawPassword) {
      this.logger.log("Using provided cache password for cache connection");
      return [rawPassword, true] as const;
    }

    this.logger.log("Using IAM token as password for cache connection");

    const region = this.env.AWS_REGION;
    const hostname = this.env.CACHE_HOST;
    const username = this.env.CACHE_USERNAME;

    const matchResult =
      /clustercfg\.([A-Za-z0-9-_]+)\.[A-Za-z0-9]+\.[A-Za-z0-9]+\.cache\.amazonaws\.com/.exec(
        hostname,
      );

    if (!matchResult || !matchResult[1]) {
      throw new Error(
        "CACHE_HOST is not in the expected format for IAM authentication",
      );
    }

    if (!region) {
      throw new Error(
        "AWS_REGION is not set, but required for IAM authentication",
      );
    }

    const request = {
      method: "GET",
      protocol: "http:",
      hostname: matchResult[1],
      headers: {
        host: matchResult[1],
      },
      query: {
        Action: "connect",
        User: username,
      },
      path: "/",
    } satisfies HttpRequest;

    const signer = new CrtSignerV4({
      credentials: defaultProvider(),
      service: "elasticache",
      region,
      sha256: Sha256,
    });

    const signedRequest = await signer.presign(request, { expiresIn: 15 * 60 });

    return [
      url.format(signedRequest).toString().replace("http://", ""),
      false,
    ] as const;
  }
}
