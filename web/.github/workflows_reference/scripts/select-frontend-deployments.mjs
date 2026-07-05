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
const inputApp = process.env.INPUT_APP || "all";
const deployTarget = process.env.DEPLOY_TARGET;
const buildArg = process.env.BUILD_ARG ?? "";
const outputPath = process.env.GITHUB_OUTPUT;

if (!outputPath) {
  throw new Error("GITHUB_OUTPUT is required");
}

if (!deployTarget) {
  throw new Error("DEPLOY_TARGET is required");
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

const toDisplayName = (app) => {
  const displayName = app
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

  return ["backoffice", "frontend"].includes(app)
    ? displayName
    : `${displayName} Frontend`;
};

const findWorkspacePackages = () => {
  const workspaceRoots = ["apps", "packages", "tests"];
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
        app: root === "apps" ? entry.name : undefined,
        name: manifest.name,
        path: `${packagePath}/`,
      });
    }
  }

  return packages;
};

const workspacePackages = findWorkspacePackages();
const globalDeploymentChange = hasChangedPath([
  ".github/workflows/frontend-develop.yaml",
  ".github/workflows/frontend-main.yaml",
  ".github/workflows/frontend-staging.yaml",
  ".github/workflows/scripts/",
  ".node-version",
  "package.json",
  "pnpm-workspace.yaml",
  "turbo.json",
]);
const directlyChangedPackages = new Set();

for (const workspacePackage of workspacePackages) {
  if (hasChangedPath([workspacePackage.path])) {
    directlyChangedPackages.add(workspacePackage.name);
  }
}

const affectedPackages =
  eventName === "workflow_dispatch" || globalDeploymentChange
    ? new Set()
    : findTurboAffectedPackages("build", directlyChangedPackages);

const frontendApps = workspacePackages
  .filter(
    (workspacePackage) =>
      workspacePackage.app && workspacePackage.app !== "backend",
  )
  .sort((left, right) => left.app.localeCompare(right.app));
const selectedApps =
  eventName === "workflow_dispatch" && inputApp !== "all"
    ? frontendApps.filter((workspacePackage) => workspacePackage.app === inputApp)
    : frontendApps;

const deployMatrix = [];

for (const app of selectedApps) {
  const appChanged =
    eventName === "workflow_dispatch" ||
    globalDeploymentChange ||
    affectedPackages.has(app.name);

  if (!appChanged) {
    continue;
  }

  deployMatrix.push({
    app: app.app,
    displayName: toDisplayName(app.app),
    target: deployTarget,
    environment: `${app.app}-${deployTarget}`,
    buildArg,
    buildScript: `${app.path}scripts/build.sh`,
    distPath: `${app.path}dist`,
  });
}

const outputs = [
  ["deploy_matrix", deployMatrix],
  ["has_deployments", deployMatrix.length > 0],
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
  `Selected deployments: ${deployMatrix
    .map((deployment) => `${deployment.app}:${deployment.target}`)
    .join(", ") || "(none)"}`,
);
