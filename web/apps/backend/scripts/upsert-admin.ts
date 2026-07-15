import { loadEnvFile } from "node:process";

import { PrismaPg } from "@prisma/adapter-pg";
import argon2 from "argon2";
import { Pool } from "pg";
import { v7 as uuidv7 } from "uuid";

import { PrismaClient } from "@shelfalign/database/client";

const ADMIN_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000000";

try {
  loadEnvFile();
} catch {
  // EnvironmentFile is used in production; a local .env is optional.
}

const email = process.argv[2]?.trim().toLowerCase();
const password = process.argv[3];
if (!email || !password || password.length < 8) {
  console.error(
    "Usage: pnpm admin:upsert <email> <password-at-least-8-characters>",
  );
  process.exit(1);
}

const pool = new Pool({
  host: process.env.DATABASE_HOST,
  port: Number(process.env.DATABASE_PORT || "5432"),
  user: process.env.DATABASE_USER,
  password: process.env.DATABASE_PASS,
  database: process.env.DATABASE_NAME,
  ssl:
    process.env.DATABASE_LOCAL === "true"
      ? false
      : { rejectUnauthorized: false },
});
const prisma = new PrismaClient({ adapter: new PrismaPg(pool) });

async function main() {
  const provider = await prisma.provider.findFirst({
    where: { name: "local", deletedAt: null },
  });
  if (!provider)
    throw new Error(
      "Local provider is missing. Start the backend once before running this script.",
    );

  await prisma.organization.upsert({
    where: { id: ADMIN_ORGANIZATION_ID },
    update: { deletedAt: null },
    create: { id: ADMIN_ORGANIZATION_ID, name: "Admin Organization" },
  });

  const hash = await argon2.hash(password);
  const connection = await prisma.providerConnection.findUnique({
    where: {
      providerId_providerUniqueId: {
        providerId: provider.id,
        providerUniqueId: email,
      },
    },
  });

  const userId = connection?.userId ?? uuidv7();
  if (connection) {
    await prisma.$transaction([
      prisma.user.update({
        where: { id: userId },
        data: { name: "ShelfAlign Admin", deletedAt: null },
      }),
      prisma.providerConnection.update({
        where: { id: connection.id },
        data: {
          email,
          data: { password: hash },
          primary: true,
          emailVerifiedAt: new Date(),
        },
      }),
      prisma.organizationMember.upsert({
        where: {
          userId_organizationId: {
            userId,
            organizationId: ADMIN_ORGANIZATION_ID,
          },
        },
        update: { type: "ADMIN", name: "ShelfAlign Admin" },
        create: {
          id: uuidv7(),
          userId,
          organizationId: ADMIN_ORGANIZATION_ID,
          type: "ADMIN",
          name: "ShelfAlign Admin",
        },
      }),
    ]);
  } else {
    await prisma.user.create({
      data: {
        id: userId,
        name: "ShelfAlign Admin",
        connections: {
          create: {
            id: uuidv7(),
            providerId: provider.id,
            providerUniqueId: email,
            email,
            data: { password: hash },
            primary: true,
            emailVerifiedAt: new Date(),
          },
        },
        organizations: {
          create: {
            id: uuidv7(),
            organizationId: ADMIN_ORGANIZATION_ID,
            type: "ADMIN",
            name: "ShelfAlign Admin",
          },
        },
      },
    });
  }

  console.log(`Admin account ready: ${email} (${userId})`);
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
    await pool.end();
  });
