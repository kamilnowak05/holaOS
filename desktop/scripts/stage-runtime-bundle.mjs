import { createWriteStream, existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const stageParentDir = path.resolve(repoRoot, "..", "out", "desktop");
const stageDir = path.join(stageParentDir, "runtime-macos");
const defaultLocalRuntimeDir = "/tmp/holaboss-runtime-macos-full";
const manifestPath = path.join(repoRoot, "runtime-manifest.json");

function log(message) {
  process.stdout.write(`[stage-runtime] ${message}\n`);
}

async function pathExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function loadRuntimeManifest() {
  if (!(await pathExists(manifestPath))) {
    return null;
  }

  return JSON.parse(await fs.readFile(manifestPath, "utf-8"));
}

async function ensureCleanStageDir() {
  await fs.rm(stageDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  await fs.mkdir(stageParentDir, { recursive: true });
}

async function copyRuntimeDirectory(sourceDir) {
  log(`copying runtime directory from ${sourceDir}`);
  await fs.cp(sourceDir, stageDir, { recursive: true });
}

async function extractRuntimeTarball(tarballPath) {
  log(`extracting runtime tarball from ${tarballPath}`);
  const extractDir = await fs.mkdtemp(path.join(os.tmpdir(), "holaboss-runtime-extract-"));
  await execFileAsync("tar", ["-xzf", tarballPath, "-C", extractDir]);

  const entries = await fs.readdir(extractDir);
  if (entries.length === 0) {
    throw new Error(`Runtime tarball ${tarballPath} extracted no files.`);
  }

  const rootEntry = entries.length === 1 ? path.join(extractDir, entries[0]) : extractDir;
  const runtimeRoot = await pathExists(path.join(rootEntry, "bin", "sandbox-runtime")) ? rootEntry : null;
  if (!runtimeRoot) {
    throw new Error(`Runtime tarball ${tarballPath} did not contain a runtime root with bin/sandbox-runtime.`);
  }

  await fs.cp(runtimeRoot, stageDir, { recursive: true });
}

async function extractArtifactZip(zipPath, destinationDir) {
  await fs.mkdir(destinationDir, { recursive: true });
  await execFileAsync("unzip", ["-oq", zipPath, "-d", destinationDir]);
}

async function downloadRuntimeTarball(url, destinationTarball) {
  log(`downloading runtime tarball from ${url}`);
  const headers = {};
  if (process.env.HOLABOSS_RUNTIME_BUNDLE_TOKEN) {
    headers.Authorization = `Bearer ${process.env.HOLABOSS_RUNTIME_BUNDLE_TOKEN}`;
  }

  const response = await fetch(url, { headers });
  if (!response.ok || !response.body) {
    throw new Error(`Failed to download runtime bundle (${response.status} ${response.statusText}).`);
  }

  await pipeline(Readable.fromWeb(response.body), createWriteStream(destinationTarball));
}

async function githubApiFetchJson(url, token) {
  const response = await fetch(url, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "User-Agent": "holaboss-desktop-runtime-stager"
    }
  });

  if (!response.ok) {
    throw new Error(`GitHub API request failed (${response.status} ${response.statusText}) for ${url}`);
  }

  return response.json();
}

async function downloadGithubReleaseAsset(url, destinationTarball, token) {
  const response = await fetch(url, {
    headers: {
      Accept: "application/octet-stream",
      Authorization: `Bearer ${token}`,
      "User-Agent": "holaboss-desktop-runtime-stager"
    },
    redirect: "follow"
  });

  if (!response.ok || !response.body) {
    throw new Error(`Failed to download GitHub release asset (${response.status} ${response.statusText}).`);
  }

  await pipeline(Readable.fromWeb(response.body), createWriteStream(destinationTarball));
}

async function downloadGithubArtifactZip(url, destinationZip, token) {
  const response = await fetch(url, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "User-Agent": "holaboss-desktop-runtime-stager"
    },
    redirect: "follow"
  });

  if (!response.ok || !response.body) {
    throw new Error(`Failed to download GitHub artifact (${response.status} ${response.statusText}).`);
  }

  await pipeline(Readable.fromWeb(response.body), createWriteStream(destinationZip));
}

function matchesWorkflow(run, manifest) {
  const workflowFile = manifest.workflowFile ?? "";
  const workflowName = manifest.workflowName ?? "";
  return (
    (workflowFile && typeof run.path === "string" && run.path.includes(workflowFile)) ||
    (workflowName && run.name === workflowName)
  );
}

async function stageFromGithubActionsArtifact(manifest, token) {
  const [owner, repo] = manifest.sourceRepo.split("/");
  const runsUrl =
    `https://api.github.com/repos/${owner}/${repo}/actions/runs` +
    `?head_sha=${encodeURIComponent(manifest.sourceCommit)}` +
    "&status=success&per_page=50";
  const runsPayload = await githubApiFetchJson(runsUrl, token);
  const runs = Array.isArray(runsPayload.workflow_runs) ? runsPayload.workflow_runs : [];
  const run = runs.find((candidate) => matchesWorkflow(candidate, manifest));

  if (!run) {
    throw new Error(
      `No successful workflow run found for ${manifest.sourceRepo}@${manifest.sourceCommit} and ${manifest.workflowFile}.`
    );
  }

  const artifactsUrl = `https://api.github.com/repos/${owner}/${repo}/actions/runs/${run.id}/artifacts?per_page=100`;
  const artifactsPayload = await githubApiFetchJson(artifactsUrl, token);
  const artifacts = Array.isArray(artifactsPayload.artifacts) ? artifactsPayload.artifacts : [];
  const artifact = artifacts.find((candidate) => candidate.name === manifest.artifactName);

  if (!artifact) {
    throw new Error(`Artifact ${manifest.artifactName} not found for workflow run ${run.id}.`);
  }

  const downloadDir = await fs.mkdtemp(path.join(os.tmpdir(), "holaboss-runtime-artifact-"));
  const artifactZip = path.join(downloadDir, "runtime-artifact.zip");
  const extractedDir = path.join(downloadDir, "artifact");

  log(`downloading GitHub artifact ${artifact.name} from run ${run.id}`);
  await downloadGithubArtifactZip(artifact.archive_download_url, artifactZip, token);
  await extractArtifactZip(artifactZip, extractedDir);

  const tarballName = manifest.tarballName;
  const tarballPath = tarballName ? path.join(extractedDir, tarballName) : null;
  const fallbackTarballs = tarballPath && (await pathExists(tarballPath)) ? [tarballPath] : [];

  if (fallbackTarballs.length === 0) {
    const candidates = (await fs.readdir(extractedDir))
      .filter((entry) => entry.endsWith(".tar.gz"))
      .map((entry) => path.join(extractedDir, entry));
    if (candidates.length === 0) {
      throw new Error(`No runtime tarball found inside downloaded artifact ${artifact.name}.`);
    }
    fallbackTarballs.push(candidates[0]);
  }

  await extractRuntimeTarball(fallbackTarballs[0]);
}

async function stageFromGithubReleaseAsset(manifest, token) {
  const [owner, repo] = manifest.sourceRepo.split("/");
  const releaseTag = manifest.releaseTag;
  const assetName = manifest.assetName ?? manifest.tarballName;

  if (!releaseTag || !assetName) {
    throw new Error("Runtime manifest is missing releaseTag or assetName for GitHub release staging.");
  }

  const releaseUrl = `https://api.github.com/repos/${owner}/${repo}/releases/tags/${encodeURIComponent(releaseTag)}`;
  const release = await githubApiFetchJson(releaseUrl, token);
  const assets = Array.isArray(release.assets) ? release.assets : [];
  const asset = assets.find((candidate) => candidate.name === assetName);

  if (!asset) {
    throw new Error(`Release asset ${assetName} not found in ${manifest.sourceRepo} release ${releaseTag}.`);
  }

  const downloadDir = await fs.mkdtemp(path.join(os.tmpdir(), "holaboss-runtime-release-"));
  const downloadPath = path.join(downloadDir, assetName);
  log(`downloading GitHub release asset ${assetName} from release ${releaseTag}`);
  await downloadGithubReleaseAsset(asset.url, downloadPath, token);
  await extractRuntimeTarball(downloadPath);
}

async function validateStageDir() {
  const requiredPaths = [
    path.join(stageDir, "bin", "sandbox-runtime"),
    path.join(stageDir, "package-metadata.json"),
    path.join(stageDir, "runtime", "metadata.json")
  ];

  for (const requiredPath of requiredPaths) {
    if (!(await pathExists(requiredPath))) {
      throw new Error(`Staged runtime is incomplete. Missing ${requiredPath}.`);
    }
  }

  const packageMetadataPath = path.join(stageDir, "package-metadata.json");
  const packageMetadata = JSON.parse(await fs.readFile(packageMetadataPath, "utf-8"));
  const createdAt = packageMetadata.createdAt ?? packageMetadata.created_at ?? "unknown";
  log(
    `staged runtime ready at ${stageDir} (platform=${packageMetadata.platform}, createdAt=${createdAt})`
  );
}

async function stageRuntimeBundle() {
  const runtimeDir = process.env.HOLABOSS_RUNTIME_DIR?.trim();
  const runtimeTarball = process.env.HOLABOSS_RUNTIME_TARBALL?.trim();
  const runtimeBundleUrl = process.env.HOLABOSS_RUNTIME_BUNDLE_URL?.trim();
  const githubToken = process.env.HOLABOSS_GITHUB_TOKEN?.trim() || process.env.GITHUB_TOKEN?.trim();
  const manifest = await loadRuntimeManifest();

  await ensureCleanStageDir();

  if (runtimeDir) {
    await copyRuntimeDirectory(path.resolve(runtimeDir));
    await validateStageDir();
    return;
  }

  if (runtimeTarball) {
    await extractRuntimeTarball(path.resolve(runtimeTarball));
    await validateStageDir();
    return;
  }

  if (runtimeBundleUrl) {
    const downloadDir = await fs.mkdtemp(path.join(os.tmpdir(), "holaboss-runtime-download-"));
    const downloadPath = path.join(downloadDir, "runtime-macos.tar.gz");
    await downloadRuntimeTarball(runtimeBundleUrl, downloadPath);
    await extractRuntimeTarball(downloadPath);
    await validateStageDir();
    return;
  }

  if (manifest && githubToken) {
    if (manifest.releaseTag && (manifest.assetName ?? manifest.tarballName)) {
      await stageFromGithubReleaseAsset(manifest, githubToken);
      await validateStageDir();
      return;
    }

    if (manifest.artifactName) {
      await stageFromGithubActionsArtifact(manifest, githubToken);
      await validateStageDir();
      return;
    }
  }

  if (existsSync(defaultLocalRuntimeDir)) {
    await copyRuntimeDirectory(defaultLocalRuntimeDir);
    await validateStageDir();
    return;
  }

  throw new Error(
    "No runtime bundle source found. Set HOLABOSS_RUNTIME_DIR, HOLABOSS_RUNTIME_TARBALL, HOLABOSS_RUNTIME_BUNDLE_URL, or provide HOLABOSS_GITHUB_TOKEN/GITHUB_TOKEN for the pinned GitHub artifact."
  );
}

stageRuntimeBundle().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`[stage-runtime] ${message}\n`);
  process.exitCode = 1;
});
