import { Inject, Injectable, Logger, OnModuleInit } from "@nestjs/common";

import { defaultProvider } from "@aws-sdk/credential-provider-node";
import { Signer } from "@aws-sdk/rds-signer";
import { PrismaPg } from "@prisma/adapter-pg";
import { Pool } from "pg";

import { PrismaClient } from "@shelfalign/database/client";

import { EnvType, registerEnv } from "@/common/utils/env";

@Injectable()
export class PrismaService extends PrismaClient implements OnModuleInit {
  private readonly logger;

  private databasePool: Pool;
  private readonlyPool: Pool;

  private databaseConnected: boolean = false;
  private readonlyConnected: boolean = false;

  readonly: PrismaClient;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
  ) {
    const logger = new Logger(PrismaService.name);

    if (env.DATABASE_PASS) {
      logger.log("Using provided database password");
    } else if (env.DATABASE_LOCAL === "true") {
      throw new Error("Database password must be provided in local mode");
    } else {
      logger.log("Using IAM token as password");
    }

    const databasePool = new Pool({
      host: env.DATABASE_HOST,
      user: env.DATABASE_USER,
      database: env.DATABASE_NAME,
      port: env.DATABASE_PORT,
      password: () => PrismaService.createDatabasePassword(env),
      application_name: "shelfalign-backend",
      ssl: env.DATABASE_LOCAL !== "true",
    });

    const readonlyPool = new Pool({
      host: env.READONLY_HOST || env.DATABASE_HOST,
      user: env.DATABASE_USER,
      database: env.DATABASE_NAME,
      port: env.DATABASE_PORT,
      password: () => PrismaService.createDatabasePassword(env),
      application_name: "shelfalign-backend",
      options: "-c default_transaction_read_only=on",
      ssl: env.DATABASE_LOCAL !== "true",
    });

    const databaseAdapter = new PrismaPg(databasePool);
    const readonlyAdapter = new PrismaPg(readonlyPool);
    super({ adapter: databaseAdapter });

    this.logger = logger;

    this.databasePool = databasePool;
    this.readonlyPool = readonlyPool;

    this.readonly = new PrismaClient({ adapter: readonlyAdapter });

    // Prevent unused variable error
    void this.env;
  }

  async onModuleInit() {
    try {
      await this.$connect();
      await this.$queryRaw`SELECT 1;`;
      this.logger.log("Connected to the database");
      this.databaseConnected = true;
    } catch (error) {
      this.logger.error("PrismaService connection error:", error);
      throw error;
    }

    try {
      await this.readonly.$connect();
      await this.readonly.$queryRaw`SELECT 1;`;
      this.logger.log("Connected to the readonly database");
      this.readonlyConnected = true;
    } catch (error) {
      this.logger.error("PrismaService readonly connection error:", error);
      throw error;
    }
  }

  async onModuleDestroy() {
    await this.databasePool.end();
    await this.readonlyPool.end();
  }

  static async createDatabasePassword(env: EnvType): Promise<string> {
    const password = env.DATABASE_PASS;
    if (password) {
      return password;
    }

    if (env.DATABASE_LOCAL === "true") {
      throw new Error("Database password must be provided in local mode");
    }

    const region = env.AWS_REGION || "ap-northeast-2";
    const hostname = env.DATABASE_HOST;
    const username = env.DATABASE_USER;
    const port = env.DATABASE_PORT;
    const credentials =
      env.AWS_ACCESS_KEY_ID && env.AWS_SECRET_ACCESS_KEY
        ? {
            accessKeyId: env.AWS_ACCESS_KEY_ID,
            secretAccessKey: env.AWS_SECRET_ACCESS_KEY,
            sessionToken: env.AWS_SESSION_TOKEN,
          }
        : defaultProvider();

    const signer = new Signer({
      credentials,
      region,
      hostname,
      username,
      port,
    });
    const token = await signer.getAuthToken();
    return token;
  }

  async waitForActiveConnections(timeoutMs: number = 10000) {
    const checkInterval = 10; // 10ms
    let elapsed = 0;
    await new Promise<void>((resolve, reject) => {
      const interval = setInterval(() => {
        if (this.databaseConnected && this.readonlyConnected) {
          clearInterval(interval);
          return resolve();
        }
        elapsed += checkInterval;
        if (elapsed >= timeoutMs) {
          clearInterval(interval);
          return reject();
        }
      }, checkInterval);
    });
  }

  async findIn<T>(targets: string[], query: (ids: string[]) => Promise<T[]>) {
    const slices: string[][] = [];
    for (let i = 0; i < targets.length; i += 100) {
      slices.push(targets.slice(i, i + 100));
    }

    const result = await Promise.all(slices.map(query));
    return result.reduce<T[]>((acc, curr) => acc.concat(curr), []);
  }

  async countIn(targets: string[], query: (ids: string[]) => Promise<number>) {
    const slices: string[][] = [];
    for (let i = 0; i < targets.length; i += 100) {
      slices.push(targets.slice(i, i + 100));
    }

    const result = await Promise.all(slices.map(query));
    return result.reduce((acc, curr) => acc + curr, 0);
  }
}
