import pluginQuery from "@tanstack/eslint-plugin-query";

import css from "@eslint/css";
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import pluginImport from "eslint-plugin-import";
import eslintPluginPrettier from "eslint-plugin-prettier/recommended";
import reactHooks from "eslint-plugin-react-hooks";
import { reactRefresh } from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist"]),
  {
    files: ["**/*.{ts,tsx,js}"],
    extends: [
      ...pluginQuery.configs["flat/recommended"],
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat["recommended-latest"],
      reactRefresh.configs.vite({
        extraHOCs: [
          "createFileRoute",
          "createLazyFileRoute",
          "createRootRoute",
          "createRootRouteWithContext",
          "createLink",
          "createRoute",
          "createLazyRoute",
        ],
      }),
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
            // === highlighted externals (react, vite, @tanstack/) ===
            {
              pattern: "{react,react-dom/**}",
              group: "external",
              position: "before",
            },
            {
              pattern: "@tanstack/**",
              group: "external",
              position: "before",
            },
            // === internal externals (shelfalign) ===
            {
              pattern: "@shelfalign/**",
              group: "external",
              position: "after",
            },
            // === fortawesome ===
            {
              pattern: "@fortawesome/**",
              group: "external",
              position: "after",
            },
            // === internal alias sub-ordering ===
            {
              pattern: "@/lib/**",
              group: "internal",
              position: "before",
            },
            {
              pattern: "@/components/**",
              group: "internal",
              position: "after",
            },
            { pattern: "@/assets/**", group: "internal", position: "after" },
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
  {
    files: ["**/*.css"],
    plugins: {
      css,
    },
    language: "css/css",
    languageOptions: {
      tolerant: true,
    },
    rules: {
      "css/no-duplicate-imports": "error",
    },
  },
]);
