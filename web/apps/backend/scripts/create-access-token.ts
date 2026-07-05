import fs from "node:fs";
import path from "node:path";
import { loadEnvFile } from "node:process";

import {
  GetSecretValueCommand,
  SecretsManagerClient,
} from "@aws-sdk/client-secrets-manager";
import { PrismaPg } from "@prisma/adapter-pg";
import { SignJWT, importPKCS8 } from "jose";
import { Pool } from "pg";
import { v7 as uuidv7 } from "uuid";

import { PrismaClient } from "@shelfalign/database/client";

try {
  loadEnvFile();
} catch {
  // .env file may not exist
}

const userId = process.argv[2];
if (!userId) {
  console.error("Usage: pnpx tsx scripts/create-access-token.ts <userId>");
  process.exit(1);
}

console.log(`Creating access token for user: ${userId}`);
console.log(
  "Connecting to database... (psql://%s:%s@%s:%s/%s)",
  process.env.DATABASE_USER,
  process.env.DATABASE_PASS,
  process.env.DATABASE_HOST,
  process.env.DATABASE_PORT || "5432",
  process.env.DATABASE_NAME,
);

const pool = new Pool({
  host: process.env.DATABASE_HOST,
  user: process.env.DATABASE_USER,
  password: process.env.DATABASE_PASS,
  database: process.env.DATABASE_NAME,
  port: Number(process.env.DATABASE_PORT || "5432"),
  ssl:
    process.env.DATABASE_LOCAL !== "true"
      ? {
          ca: fs.readFileSync(
            path.resolve(__dirname, "../../../certs/aws-rds.crt"),
          ),
        }
      : false,
});

const prisma = new PrismaClient({ adapter: new PrismaPg(pool) });

async function getSigningKey() {
  const secretId = process.env.AUTH_KEY_SECRET_ID;
  if (!secretId) {
    throw new Error("AUTH_KEY_SECRET_ID environment variable is required");
  }

  const client = new SecretsManagerClient({
    credentials:
      process.env.AWS_ACCESS_KEY_ID && process.env.AWS_SECRET_ACCESS_KEY
        ? {
            accessKeyId: process.env.AWS_ACCESS_KEY_ID,
            secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
            sessionToken: process.env.AWS_SESSION_TOKEN,
          }
        : undefined,
  });

  const result = await client.send(
    new GetSecretValueCommand({ SecretId: secretId }),
  );

  if (!result.SecretString) {
    throw new Error("Failed to fetch keys from Secrets Manager");
  }

  const keychain = JSON.parse(result.SecretString) as Record<string, string>;
  const latestKeyId = keychain.LATEST_KEY_ID;
  if (!latestKeyId) {
    throw new Error("LATEST_KEY_ID not found in keychain");
  }

  const privateKeyPem = keychain[latestKeyId];
  if (!privateKeyPem) {
    throw new Error(`Private key not found for key ID: ${latestKeyId}`);
  }

  const privateKey = await importPKCS8(privateKeyPem, "ES512");
  return { keyId: latestKeyId, privateKey };
}

function getIssuerAndAudience() {
  const nodeEnv = process.env.NODE_ENV || "development";
  const port = process.env.PORT || "4000";

  if (nodeEnv === "production") {
    return { issuer: "https://api.shelfalign.kr", audience: "https://shelfalign.kr" };
  }
  if (nodeEnv === "local") {
    return {
      issuer: `http://localhost:${port}`,
      audience: `http://localhost:${port}`,
    };
  }
  return {
    issuer: `https://${nodeEnv}-api.shelfalign.kr`,
    audience: `https://${nodeEnv}.shelfalign.kr`,
  };
}

async function main() {
  const user = await prisma.user.findUnique({ where: { id: userId } });
  if (!user) {
    console.error(`User not found: ${userId}`);
    process.exit(1);
  }

  const session = await prisma.session.findFirst({
    where: { userId },
    orderBy: { createdAt: "desc" },
  });
  if (!session) {
    console.error(`No session found for user: ${userId}`);
    process.exit(1);
  }

  const members = await prisma.organizationMember.findMany({
    where: { userId },
    select: { organizationId: true, type: true },
  });

  const permissions: Record<string, string> = {};
  for (const member of members) {
    permissions[member.organizationId] = member.type;
  }

  const { keyId, privateKey } = await getSigningKey();
  const { issuer, audience } = getIssuerAndAudience();

  const accessToken = await new SignJWT({
    sessionId: session.id,
    permissions,
  })
    .setProtectedHeader({
      alg: "ES512",
      sub: user.id,
      aud: `${audience}/accessToken`,
      iss: issuer,
      kid: keyId,
      jti: uuidv7(),
    })
    .setExpirationTime("15m")
    .sign(privateKey);

  console.log(accessToken);
}

main()
  .catch((err) => {
    console.error(err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
    await pool.end();
  });
