import js from "@eslint/js";
import pluginImport from "eslint-plugin-import";
import eslintPluginPrettier from "eslint-plugin-prettier/recommended";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist"]),
  {
    files: ["**/*.{ts,tsx}", "eslint.config.mjs"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      eslintPluginPrettier,
    ],
    plugins: {
      import: pluginImport,
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        tsconfigRootDir: import.meta.dirname,
      },
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
            {
              pattern: "zod",
              group: "external",
              position: "before",
            },
            // === internal externals (shelfalign) ===
            {
              pattern: "@shelfalign/**",
              group: "external",
              position: "after",
            },
            { pattern: "@/**", group: "internal", position: "before" },
            // === relatives ===
            { pattern: "**/*.css", group: "sibling", position: "after" },
          ],
          distinctGroup: true,
          pathGroupsExcludedImportTypes: ["react"],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
    },
  },
]);
