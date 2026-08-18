import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { mkdir, writeFile } from "node:fs/promises";
import test from "node:test";

import { build } from "esbuild";

const require = createRequire(import.meta.url);
const panelSource = readFileSync(
  new URL("../src/knowledge-center/SemanticBuildPanel.tsx", import.meta.url),
  "utf8",
);
const knowledgeCenterSource = readFileSync(
  new URL("../src/knowledge-center/KnowledgeCenter.tsx", import.meta.url),
  "utf8",
);
const cssSource = readFileSync(
  new URL("../src/knowledge-center/KnowledgeCenter.css", import.meta.url),
  "utf8",
);

async function loadTypeScriptModule(relativePath) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(relativePath, import.meta.url))],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "node20",
    write: false,
  });
  const id = createHash("sha1").update(relativePath).digest("hex").slice(0, 10);
  const outDir = join(tmpdir(), "veadk-frontend-tests");
  await mkdir(outDir, { recursive: true });
  const outFile = join(outDir, `semantic-build-${id}.cjs`);
  await writeFile(outFile, result.outputFiles[0].contents);
  delete require.cache[outFile];
  return require(outFile);
}

test("SemanticBuildPanel uses D3 slot and native build API", () => {
  assert.match(panelSource, /CapabilityPanelSlot/);
  assert.match(panelSource, /kind="semantic_skill"/);
  assert.match(panelSource, /buildSemanticSkill/);
  assert.match(panelSource, /Schema snapshot/);
  assert.match(panelSource, /not_configured/);
  assert.match(panelSource, /受治理 REST 查询工具/);
  assert.doesNotMatch(panelSource, /<iframe/);
  assert.doesNotMatch(panelSource, /DATASTUDIO_API_KEY/);
  assert.match(knowledgeCenterSource, /<SemanticBuildPanel/);
});

test("knowledgeAssets client exposes semantic-skill build endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    return new Response(
      JSON.stringify({ id: "job_1", job_type: "semantic_skill", status: "blocked" }),
      { status: 201, headers: { "content-type": "application/json" } },
    );
  };
  try {
    const { buildSemanticSkill } = await loadTypeScriptModule("../src/adk/knowledgeAssets.ts");
    const job = await buildSemanticSkill({
      space_id: "space_1",
      source_ids: ["src_1"],
      snapshot_ids: ["snap_1"],
      name: "Sales Semantic",
    });
    assert.equal(job.status, "blocked");
    assert.equal(calls[0].url, "/api/knowledge-assets/build/semantic-skill");
    assert.equal(calls[0].method, "POST");
    assert.deepEqual(JSON.parse(calls[0].body), {
      space_id: "space_1",
      source_ids: ["src_1"],
      snapshot_ids: ["snap_1"],
      name: "Sales Semantic",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Semantic build CSS is responsive without product iframe shell", () => {
  assert.match(cssSource, /\.kc-semantic-build/);
  assert.match(cssSource, /grid-template-columns: minmax\(0, 1fr\)/);
  assert.doesNotMatch(cssSource, /iframe/);
});
