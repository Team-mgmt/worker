import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import pluginImport from "eslint-plugin-import";
import eslintPluginPrettier from "eslint-plugin-prettier/recommended";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist", "storybook-static"]),
  {
    files: ["**/*.{ts,tsx}", "eslint.config.js"],
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
            "builtin",
            "external",
            "internal",
            ["parent", "sibling", "index"],
          ],
          pathGroups: [
            {
              pattern: "zod",
              group: "external",
              position: "before",
            },
            {
              pattern: "@shelfalign/**",
              group: "external",
              position: "after",
            },
            { pattern: "@/**", group: "internal", position: "before" },
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
