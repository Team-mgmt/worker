import { defineConfig, env } from "prisma/config";

export default defineConfig({
  schema: 'prisma/schema.prisma',
  migrations: {
    path: "prisma/migrations"
  },
  datasource: {
    url: process.env.DATABASE_URL || "postgresql://shelfalign:shelfalign@localhost:5432/shelfalign",
    shadowDatabaseUrl: process.env.SHADOWDB_URL || "postgresql://shelfalign:shelfalign@localhost:5432/shelfalign_shadow",
  },
});