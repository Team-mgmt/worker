import path from "node:path";

import { tanstackRouter } from "@tanstack/router-plugin/vite";

import babel from "@rolldown/plugin-babel";
import { sentryVitePlugin } from "@sentry/vite-plugin";
import tailwindcss from "@tailwindcss/vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { analyzer } from "vite-bundle-analyzer";

export default defineConfig({
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    babel({
      presets: [reactCompilerPreset()],
    }),
    tailwindcss(),
    sentryVitePlugin({
      org: "swjeon",
      project: "shelfalign-backoffice",
      authToken: process.env.SENTRY_AUTH_TOKEN,
    }),
    analyzer({
      openAnalyzer: false,
      enabled: process.argv.includes("--analyze"),
    }),
  ],
  build: {
    sourcemap: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
