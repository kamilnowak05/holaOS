import path from "node:path";
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const repoRoot = process.cwd();
const explicitRuntimeRepoRoot = process.env.HOLABOSS_OSS_ROOT || process.env.HOLABOSS_RUNTIME_REPO_ROOT;
const monorepoRuntimeRepoRoot = path.resolve(repoRoot, "..");
const legacySiblingRuntimeRepoRoot = path.resolve(repoRoot, "../hola-boss-oss");
const inferredRuntimeRepoRoot = existsSync(
  path.join(monorepoRuntimeRepoRoot, "runtime", "deploy", "package_macos_runtime.sh")
)
  ? monorepoRuntimeRepoRoot
  : legacySiblingRuntimeRepoRoot;
const runtimeRepoRoot = path.resolve(repoRoot, explicitRuntimeRepoRoot || inferredRuntimeRepoRoot);
const runtimeOutDir = path.resolve(runtimeRepoRoot, process.env.HOLABOSS_RUNTIME_OUT_DIR || "out/runtime-macos");
const packagerPath = path.join(runtimeRepoRoot, "runtime", "deploy", "package_macos_runtime.sh");

if (!existsSync(packagerPath)) {
  console.error(`[prepare-runtime:local] package script not found: ${packagerPath}`);
  console.error("Set HOLABOSS_OSS_ROOT to your local hola-boss-oss checkout.");
  process.exit(1);
}

console.log(`[prepare-runtime:local] runtime repo root: ${runtimeRepoRoot}`);
console.log(`[prepare-runtime:local] runtime out: ${runtimeOutDir}`);

const buildRuntime = spawnSync("bash", [packagerPath, runtimeOutDir], {
  stdio: "inherit",
  env: process.env
});

if ((buildRuntime.status ?? 1) !== 0) {
  process.exit(buildRuntime.status ?? 1);
}

const stageRuntime = spawnSync(process.execPath, [path.join(repoRoot, "scripts", "stage-runtime-bundle.mjs")], {
  stdio: "inherit",
  env: {
    ...process.env,
    HOLABOSS_RUNTIME_DIR: runtimeOutDir
  }
});

if ((stageRuntime.status ?? 1) !== 0) {
  process.exit(stageRuntime.status ?? 1);
}

console.log("[prepare-runtime:local] staged local runtime into ../out/desktop/runtime-macos");
