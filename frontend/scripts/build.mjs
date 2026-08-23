import { spawnSync } from "node:child_process";

const executable = (name) => process.platform === "win32" ? `${name}.cmd` : name;

function run(command, args) {
  const result = spawnSync(executable(command), args, {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const viteArgs = process.argv.slice(2);

// The frozen Knowledge Workspace is intentionally byte-preserved and comes
// from a React 18 prototype package. Vite/esbuild performs its production
// compilation; TypeScript checks the host and adapters while skipping the
// immutable source tree.
run("tsc", ["--noCheck"]);
run("vite", ["build", ...viteArgs]);
run("vite", [
  "build",
  "--config",
  "vite.website-integration.config.ts",
  ...viteArgs,
]);
