import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = dirname(fileURLToPath(import.meta.url));
const repoRoot = dirname(frontendRoot);
const contractRoot = join(
  repoRoot,
  "tests/fixtures/knowledge_workspace_v21141",
);
const harness = join(
  repoRoot,
  "tests/production_readiness/knowledge_workspace_v21141/contract_harness.py",
);
const defaultEvidenceDir =
  "/Users/bytedance/.codex/runtime/knowledge-v21141-commercial-step-1/playwright";

function expectedIdentityReport() {
  const identity = JSON.parse(
    readFileSync(join(contractRoot, "baseline-identity.json"), "utf8"),
  ).frozen_export;
  return {
    tar_sha256: identity.tar_sha256,
    source_tree_sha256: identity.source_tree_sha256,
    source_file_count: identity.source_file_count,
    source_lines_posix: identity.source_lines_posix,
    source_bytes: identity.source_bytes,
    readme_sha256: identity.readme_sha256,
    captures_sha256: identity.captures_sha256,
    root_route_manifest_sha256: identity.root_route_manifest_sha256,
    complete_route_manifest_sha256: identity.complete_route_manifest_sha256,
    dependencies_sha256: identity.dependencies_sha256,
  };
}

export function verifyBaselineIdentity({
  env = process.env,
  python = env.KNOWLEDGE_V21141_PYTHON ?? "python3",
  run = (command, args) =>
    spawnSync(command, args, { encoding: "utf8", env, timeout: 120_000 }),
} = {}) {
  const archive = env.KNOWLEDGE_V21141_ARCHIVE;
  if (!archive) {
    throw new Error(
      "KNOWLEDGE_V21141_ARCHIVE is required; identity must pass before browser/page work",
    );
  }
  const captureDir = env.KNOWLEDGE_V21141_CAPTURE_DIR;
  if (!captureDir) {
    throw new Error(
      "KNOWLEDGE_V21141_CAPTURE_DIR is required; frozen PNGs must pass before browser/page work",
    );
  }
  const identity = JSON.parse(
    readFileSync(join(contractRoot, "baseline-identity.json"), "utf8"),
  ).frozen_export;
  const result = run(python, [
    harness,
    "verify-archive",
    "--archive",
    archive,
    "--url",
    identity.url,
  ]);
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      `frozen identity verification failed: ${result.stderr || result.stdout}`,
    );
  }
  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`frozen identity verification returned invalid JSON: ${error}`);
  }
  const expected = expectedIdentityReport();
  if (report.status !== "pass") {
    throw new Error("frozen identity verification did not report pass");
  }
  for (const [field, value] of Object.entries(expected)) {
    if (report[field] !== value) {
      throw new Error(
        `frozen identity receipt mismatch for ${field}: expected ${value}, got ${report[field]}`,
      );
    }
  }
  const captureResult = run(python, [
    harness,
    "verify-captures",
    "--capture-dir",
    captureDir,
  ]);
  if (captureResult.error) throw captureResult.error;
  if (captureResult.status !== 0) {
    throw new Error(
      `frozen capture verification failed: ${captureResult.stderr || captureResult.stdout}`,
    );
  }
  let captures;
  try {
    captures = JSON.parse(captureResult.stdout);
  } catch (error) {
    throw new Error(`frozen capture verification returned invalid JSON: ${error}`);
  }
  if (
    captures.status !== "pass" ||
    captures.capture_states !== 13 ||
    captures.unique_pngs !== 12
  ) {
    throw new Error("frozen capture verification did not authenticate 13/12");
  }
  const receipt = { ...report, captures };
  const evidenceDir =
    env.KNOWLEDGE_V21141_EVIDENCE_DIR ?? defaultEvidenceDir;
  mkdirSync(evidenceDir, { recursive: true });
  writeFileSync(
    join(evidenceDir, "baseline-identity-receipt.json"),
    `${JSON.stringify(receipt, null, 2)}\n`,
  );
  return receipt;
}

export default function globalSetup() {
  verifyBaselineIdentity();
}
