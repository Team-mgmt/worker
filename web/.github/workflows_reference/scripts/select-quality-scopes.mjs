import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const repoRoot = new URL("../../../", import.meta.url);
const repoRootPath = fileURLToPath(repoRoot);
const changedFilesArgIndex = process.argv.indexOf("--changed-files");
const changedFilesPath =
  changedFilesArgIndex === -1
    ? "changed-files.txt"
    : (process.argv[changedFilesArgIndex + 1] ?? "changed-files.txt");
const eventName = process.env.EVENT_NAME ?? process.env.GITHUB_EVENT_NAME;
const outputPath = process.env.GITHUB_OUTPUT;

if (!outputPath) {
  throw new Error("GITHUB_OUTPUT is required");
}

const changedFiles = fs
  .readFileSync(changedFilesPath, "utf8")
  .split(/\r?\n/)
  .filter(Boolean);

const matchesPath = (file, pattern) => {
  if (pattern.endsWith("/")) {
    return file.startsWith(pattern);
  }

  return file === pattern;
};

const hasChangedPath = (patterns = []) =>
  changedFiles.some((file) =>
    patterns.some((pattern) => matchesPath(file, pattern)),
  );

const readJson = (url) => JSON.parse(fs.readFileSync(url, "utf8"));
const turboConfig = readJson(new URL("turbo.json", repoRoot));

const parseTurboJson = (output) => {
  const start = output.indexOf("{");
  const end = output.lastIndexOf("}");

  if (start === -1 || end === -1 || end < start) {
    throw new Error("Turbo did not return JSON output");
  }

  return JSON.parse(output.slice(start, end + 1));
};

const findTurboAffectedPackages = (task, packageNames) => {
  const packageFilters = [...packageNames].map(
    (packageName) => `--filter=...${packageName}`,
  );
  const affectedPackages = new Set();

  if (packageFilters.length === 0) {
    return affectedPackages;
  }

  const output = execFileSync(
    "pnpm",
    [
      "exec",
      "turbo",
      "run",
      task,
      "--dry-run=json",
      ...packageFilters,
    ],
    {
      cwd: repoRootPath,
      encoding: "utf8",
      maxBuffer: 50 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const dryRun = parseTurboJson(output);

  for (const affectedPackage of dryRun.packages ?? []) {
    affectedPackages.add(affectedPackage);
  }

  return affectedPackages;
};

const toScope = (packageName) => packageName.replace(/^@qmr\//, "");

const toDisplayName = (scope) =>
  scope
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

const findWorkspacePackages = () => {
  // Top-level workspace roots are flat ("apps/X"). `apps/lambda/*` is the
  // nested exception — every lambda lives under it because they share build
  // tooling and deploy together. Add new nested groups here if needed.
  const workspaceRoots = ["apps", "apps/lambda", "packages", "tests"];
  const packages = [];

  for (const root of workspaceRoots) {
    const rootUrl = new URL(`${root}/`, repoRoot);

    if (!fs.existsSync(rootUrl)) {
      continue;
    }

    for (const entry of fs.readdirSync(rootUrl, { withFileTypes: true })) {
      if (!entry.isDirectory()) {
        continue;
      }

      const packagePath = `${root}/${entry.name}`;
      const packageJsonUrl = new URL(`${packagePath}/package.json`, repoRoot);

      if (!fs.existsSync(packageJsonUrl)) {
        continue;
      }

      const manifest = readJson(packageJsonUrl);

      packages.push({
        name: manifest.name,
        path: `${packagePath}/`,
        scripts: manifest.scripts ?? {},
        runtimeDependencies: {
          ...manifest.dependencies,
          ...manifest.peerDependencies,
          ...manifest.optionalDependencies,
        },
      });
    }
  }

  return packages;
};

const workspacePackages = findWorkspacePackages();
const workspacePackageNames = new Set(
  workspacePackages.map((workspacePackage) => workspacePackage.name),
);
const manualDispatch = eventName === "workflow_dispatch";
const globalQualityChange = hasChangedPath([
  ".github/workflows/ci.yaml",
  ".github/workflows/scripts/",
  ".node-version",
  "package.json",
  "pnpm-workspace.yaml",
  "turbo.json",
]);
const directlyChangedPackages = new Set();

for (const workspacePackage of workspacePackages) {
  if (
    manualDispatch ||
    globalQualityChange ||
    hasChangedPath([workspacePackage.path])
  ) {
    directlyChangedPackages.add(workspacePackage.name);
  }
}

const findRuntimeAffectedPackages = (packageNames) => {
  const affectedPackages = new Set(packageNames);
  let changed = true;

  while (changed) {
    changed = false;

    for (const workspacePackage of workspacePackages) {
      if (affectedPackages.has(workspacePackage.name)) {
        continue;
      }

      const dependsOnAffectedPackage = Object.keys(
        workspacePackage.runtimeDependencies,
      ).some(
        (dependencyName) =>
          workspacePackageNames.has(dependencyName) &&
          affectedPackages.has(dependencyName),
      );

      if (dependsOnAffectedPackage) {
        affectedPackages.add(workspacePackage.name);
        changed = true;
      }
    }
  }

  return affectedPackages;
};

const intersectSets = (left, right) =>
  new Set([...left].filter((value) => right.has(value)));

const allWorkspacePackageNames = workspacePackages.map(
  (workspacePackage) => workspacePackage.name,
);
const ciAffectedPackages = manualDispatch
  ? new Set(allWorkspacePackageNames)
  : intersectSets(
      findTurboAffectedPackages("build", directlyChangedPackages),
      findRuntimeAffectedPackages(directlyChangedPackages),
    );
const lintAffectedPackages = manualDispatch
  ? new Set(allWorkspacePackageNames)
  : findTurboAffectedPackages("lint", directlyChangedPackages);

const hasScript = (workspacePackage, script) =>
  Object.hasOwn(workspacePackage.scripts, script);

const hasSqlTaskDependency = (workspacePackage) => {
  const taskPrefix = `${workspacePackage.name}#`;

  return Object.entries(turboConfig.tasks ?? {}).some(([taskName, task]) => {
    if (!taskName.startsWith(taskPrefix) || !Array.isArray(task.dependsOn)) {
      return false;
    }

    return task.dependsOn.includes("@qmr/database#build:sql");
  });
};

const toCiScope = (workspacePackage) => {
  const scope = toScope(workspacePackage.name);
  const coverage = hasScript(workspacePackage, "test:coverage");

  return {
    scope,
    package: workspacePackage.name,
    checkTypes: hasScript(workspacePackage, "check-types"),
    build: hasScript(workspacePackage, "build"),
    coverage,
    needsSql:
      hasScript(workspacePackage, "generate:sql") ||
      hasSqlTaskDependency(workspacePackage),
    ...(coverage
      ? {
          coverageName: toDisplayName(scope),
          coveragePath: `${workspacePackage.path}coverage`,
        }
      : {}),
  };
};

const ciMatrix = workspacePackages
  .filter((workspacePackage) => ciAffectedPackages.has(workspacePackage.name))
  .map(toCiScope)
  .filter((scope) => scope.checkTypes || scope.build || scope.coverage);
const coverageMatrix = ciMatrix.filter((scope) => scope.coverage);
const lintMatrix = workspacePackages
  .filter((workspacePackage) => lintAffectedPackages.has(workspacePackage.name))
  .filter((workspacePackage) => hasScript(workspacePackage, "lint"))
  .map((workspacePackage) => ({
    scope: toScope(workspacePackage.name),
    package: workspacePackage.name,
  }));

const outputs = [
  ["ci_matrix", ciMatrix],
  ["coverage_matrix", coverageMatrix],
  ["lint_matrix", lintMatrix],
  ["has_checks", ciMatrix.length > 0],
  ["has_coverage", coverageMatrix.length > 0],
  ["has_lint", lintMatrix.length > 0],
];

fs.appendFileSync(
  outputPath,
  outputs
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join("\n") + "\n",
);

console.log(
  `Changed files: ${changedFiles.length === 0 ? "(workflow dispatch)" : changedFiles.join(", ")}`,
);
console.log(
  `Selected CI scopes: ${ciMatrix.map((scope) => scope.scope).join(", ") || "(none)"}`,
);
console.log(
  `Selected lint scopes: ${lintMatrix.map((scope) => scope.scope).join(", ") || "(none)"}`,
);
