import { defineConfig } from "tsup";

const isWatch = process.argv.includes("--watch");

export default defineConfig({
  entry: ["src/**/*.ts", "src/**/*.tsx", "!src/**/*.stories.tsx"],
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
