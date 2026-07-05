#!/usr/bin/env node

import { appendFileSync, readFileSync } from "node:fs";

const rootPackage = JSON.parse(
  readFileSync(new URL("../../../package.json", import.meta.url), "utf8"),
);
const turboSpecifier =
  rootPackage.dependencies?.turbo ?? rootPackage.devDependencies?.turbo;

if (!turboSpecifier) {
  throw new Error("turbo dependency not found in package.json");
}

const turboPackage = JSON.parse(
  readFileSync(
    new URL("../../../node_modules/turbo/package.json", import.meta.url),
    "utf8",
  ),
);
const output = `version=${turboPackage.version}\n`;

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, output);
} else {
  process.stdout.write(output);
}
