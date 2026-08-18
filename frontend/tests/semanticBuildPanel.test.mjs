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
  new URL("../src/knowledge-center/SemanticModelingWorkbench.tsx", import.meta.url),
  "utf8",
);
const askDashboardSource = readFileSync(
  new URL("../src/knowledge-center/AskDashboardWorkbench.tsx", import.meta.url),
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

test("SemanticModelingWorkbench uses React Flow canvas and native build API", () => {
  assert.match(panelSource, /ReactFlow/);
  assert.match(panelSource, /MiniMap/);
  assert.match(panelSource, /Controls/);
  assert.match(panelSource, /Background/);
  assert.match(panelSource, /dagre/);
  assert.match(panelSource, /buildSemanticSkill/);
  assert.match(panelSource, /SemanticModelTree/);
  assert.match(panelSource, /SemanticGraphCanvas/);
  assert.match(panelSource, /SemanticMetadataDrawer/);
  assert.match(panelSource, /查看 MDL/);
  assert.match(panelSource, /查看评测/);
  assert.match(panelSource, /agent_status/);
  assert.doesNotMatch(panelSource, /<iframe/);
  assert.doesNotMatch(panelSource, /DATASTUDIO_API_KEY/);
  assert.match(knowledgeCenterSource, /<SemanticModelingWorkbench/);
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
  assert.match(cssSource, /\.kc-semantic-workbench/);
  assert.match(cssSource, /\.kc-semantic-canvas/);
  assert.match(cssSource, /\.kc-semantic-layout/);
  assert.match(cssSource, /@media \(max-width: 980px\)/);
  assert.doesNotMatch(cssSource, /iframe/);
});

test("AskDashboardWorkbench renders BYAAN-style preview code and query evidence tabs", () => {
  assert.match(askDashboardSource, /AskTablePanel/);
  assert.match(askDashboardSource, /DashboardPreviewWorkspace/);
  assert.match(askDashboardSource, /DashboardQueryEvidencePanel/);
  assert.match(askDashboardSource, /Preview/);
  assert.match(askDashboardSource, /Code/);
  assert.match(askDashboardSource, /Queries/);
  assert.match(askDashboardSource, /policyDecision/);
  assert.match(askDashboardSource, /freshness/);
  assert.match(askDashboardSource, /metricDefinition/);
  assert.match(askDashboardSource, /title="后端导出能力尚未启用"/);
  assert.match(knowledgeCenterSource, /<AskDashboardWorkbench/);
});
