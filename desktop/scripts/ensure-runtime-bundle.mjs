import { access } from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";

const desktopRoot = process.cwd();
const runtimeExecutable = path.join(desktopRoot, "out", "runtime-macos", "bin", "sandbox-runtime");

async function runtimeBundleExists() {
  try {
    await access(runtimeExecutable);
    return true;
  } catch {
    return false;
  }
}

if (!(await runtimeBundleExists())) {
  const result = spawnSync("npm", ["run", "prepare:runtime:local"], {
    cwd: desktopRoot,
    stdio: "inherit",
    env: process.env
  });
  process.exit(result.status ?? 1);
}
