import { defineConfig } from "tsup";

const isWatch = process.argv.includes("--watch");

export default defineConfig({
  entry: [
    "src/permission.ts",
    "src/auth/**/*.ts",
    "src/cache/**/*.ts",
    "src/dtos/auth/**/*.ts",
    "src/dtos/auth.ts",
    "src/dtos/base.ts",
    "src/dtos/admin/document.ts",
    "src/dtos/admin/organization.ts",
    "src/dtos/admin/provider.ts",
    "src/dtos/service/upload.ts",
    "src/models/organization.ts",
    "src/models/organization-member.ts",
    "src/models/provider.ts",
    "src/models/provider-connection.ts",
    "src/models/session.ts",
    "src/models/tiptap-content.ts",
    "src/models/upload-file.ts",
    "src/models/user.ts",
  ],
  format: ["esm"],
  dts: false,
  sourcemap: true,
  clean: !isWatch,
  splitting: false,
  treeshake: false,
  onSuccess: "tsc --emitDeclarationOnly --declaration --declarationMap",
  esbuildOptions(options) {
    options.alias = {
      "@": "./src",
    };
  },
});
