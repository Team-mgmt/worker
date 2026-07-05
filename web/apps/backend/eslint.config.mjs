import js from "@eslint/js";
import pluginImport from "eslint-plugin-import";
import eslintPluginPrettier from "eslint-plugin-prettier/recommended";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

import qmrPlugin from "@qmr/eslint-plugin";

export default defineConfig([
  globalIgnores(["dist"]),
  {
    files: ["**/*.ts"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      eslintPluginPrettier,
    ],
    plugins: {
      import: pluginImport,
      qmr: qmrPlugin,
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.node,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    settings: {
      "import/internal-regex": "^@/",
    },
    rules: {
      "import/order": [
        "error",
        {
          groups: [
            "builtin", // :NODE:
            "external", // :PACKAGE:
            "internal", // :ALIAS:
            ["parent", "sibling", "index"], // "**" (relatives)
          ],
          pathGroups: [
            // === highlighted externals (@nestjs/) ===
            {
              pattern: "@nestjs/**",
              group: "external",
              position: "before",
            },
            {
              pattern: "@qmr/**",
              group: "external",
              position: "after",
            },
            // === internal alias sub-ordering ===
            // === relatives ===
          ],
          distinctGroup: true,
          pathGroupsExcludedImportTypes: ["react"],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "qmr/zod-serializer-return-type": "error",
    },
  },
]);