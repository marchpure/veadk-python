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
const wrenSourcePortSource = readFileSync(
  new URL("../src/features/knowledge-assets/source-ports/wren/WrenModelingSourcePort.tsx", import.meta.url),
  "utf8",
);
const wrenOriginalDiagramSource = readFileSync(
  new URL("../src/features/knowledge-assets/source-ports/wren/original/diagram/index.tsx", import.meta.url),
  "utf8",
);
const wrenOriginalModelNodeSource = readFileSync(
  new URL("../src/features/knowledge-assets/source-ports/wren/original/customNode/ModelNode.tsx", import.meta.url),
  "utf8",
);
const wrenOriginalSidebarSource = readFileSync(
  new URL("../src/features/knowledge-assets/source-ports/wren/original/sidebar/Modeling.tsx", import.meta.url),
  "utf8",
);
const wrenAdapterSource = readFileSync(
  new URL("../src/features/knowledge-assets/adapters/wrenSemanticAdapter.ts", import.meta.url),
  "utf8",
);
const byaanAdapterSource = readFileSync(
  new URL("../src/features/knowledge-assets/adapters/byaanAskTableAdapter.ts", import.meta.url),
  "utf8",
);
const byaanNotebookSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/ByaanNotebook.tsx", import.meta.url),
  "utf8",
);
const byaanNotebookAdapterSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/adapter.ts", import.meta.url),
  "utf8",
);
const byaanDashboardPreviewSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/DashboardPreviewPanel.tsx", import.meta.url),
  "utf8",
);
const byaanQueryPanelSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/NotebookQueryPanel.tsx", import.meta.url),
  "utf8",
);
const byaanQueryRunnerDockedSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/QueryRunnerDocked.tsx", import.meta.url),
  "utf8",
);
const byaanQueryResultsSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/QueryResults.tsx", import.meta.url),
  "utf8",
);
const byaanSemanticEvidenceSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/SemanticEvidencePanel.tsx", import.meta.url),
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
  assert.match(wrenOriginalDiagramSource, /ReactFlow/);
  assert.match(wrenOriginalDiagramSource, /MiniMap/);
  assert.match(wrenOriginalDiagramSource, /Controls/);
  assert.match(wrenOriginalDiagramSource, /Background/);
  assert.match(wrenOriginalDiagramSource, /dagre/);
  assert.match(panelSource, /buildSemanticSkill/);
  assert.match(panelSource, /WrenModelingSourcePort/);
  assert.match(panelSource, /createWrenSemanticSourcePortViewModel/);
  assert.match(panelSource, /aria-label="Semantic Skill"/);
  assert.match(wrenSourcePortSource, /Source-level port of Wren UI modeling workspace/);
  assert.match(wrenSourcePortSource, /original\/diagram/);
  assert.match(wrenSourcePortSource, /original\/sidebar\/Modeling/);
  assert.match(wrenOriginalSidebarSource, /ModelTree/);
  assert.match(wrenOriginalSidebarSource, /ViewTree/);
  assert.match(wrenOriginalModelNodeSource, /export const ModelNode/);
  assert.match(wrenSourcePortSource, /kc-wren-diagram-empty/);
  assert.match(wrenOriginalSidebarSource, /GroupTreeTitle/);
  assert.match(wrenAdapterSource, /blockedReason/);
  assert.match(wrenOriginalModelNodeSource, /Calculated Fields/);
  assert.match(panelSource, /relationshipFieldHighlights/);
  assert.match(wrenOriginalDiagramSource, /onEdgeMouseEnter/);
  assert.match(wrenSourcePortSource, /kc-mobile-workbench-tabs/);
  assert.match(wrenAdapterSource, /mdlToModelingViewModel/);
  assert.match(wrenAdapterSource, /agent_status/);
  assert.doesNotMatch(panelSource, /<iframe/);
  assert.doesNotMatch([wrenSourcePortSource, wrenOriginalDiagramSource, wrenOriginalModelNodeSource, wrenOriginalSidebarSource].join("\n"), /<iframe|from ["'][^"']*(Apollo|ApiService)|localhost:3011/);
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
  assert.doesNotMatch(cssSource, /wren-ui|wrenai-legacy|byaan-knowledge-center|localhost:15183|localhost:3011/);
});

test("AskDashboardWorkbench renders the BYAAN notebook source-port and governed query evidence tabs", () => {
  assert.match(askDashboardSource, /from "\.\.\/features\/knowledge-assets\/byaan-notebook"/);
  assert.match(askDashboardSource, /<ByaanNotebook/);
  assert.match(askDashboardSource, /streamAskData/);
  assert.match(askDashboardSource, /parseSSE/);
  assert.match(askDashboardSource, /applyEvent/);
  assert.match(askDashboardSource, /query_semantic_skill/);
  assert.match(askDashboardSource, /buildDashboardSkill/);
  assert.match(askDashboardSource, /dashboardBuildReadiness/);
  assert.match(askDashboardSource, /production_completed/);
  assert.doesNotMatch(askDashboardSource, /queryAskData/);
  assert.doesNotMatch(askDashboardSource, /dashboardResultFromEvent/);
  assert.doesNotMatch(askDashboardSource, /Returned .*governed rows/);
  assert.doesNotMatch(
    askDashboardSource,
    /function (AskTablePortal|AskComposer|QueryRoundView|DashboardNotebookPreview|DashboardCanvas|MiniResultTable)/,
  );
  assert.doesNotMatch(askDashboardSource, /kc-askdash-portal-stage|kc-askdash-dashboard-tiles/);

  assert.match(byaanNotebookSource, /data-source-port="byaan-notebook"/);
  assert.match(byaanNotebookSource, /What do you need to know\?/);
  assert.match(byaanNotebookSource, /ResizableSplitPanel/);
  assert.match(byaanNotebookSource, /MessageList/);
  assert.match(byaanNotebookSource, /DashboardPreviewPanel/);
  assert.match(byaanNotebookSource, /TableMentionInput/);
  assert.match(byaanNotebookSource, /SemanticEvidencePanel/);
  assert.match(byaanDashboardPreviewSource, /Preview/);
  assert.match(byaanDashboardPreviewSource, /Code/);
  assert.match(byaanDashboardPreviewSource, /Queries/);
  assert.match(byaanDashboardPreviewSource, /QueryRunnerDocked/);
  assert.match(byaanDashboardPreviewSource, /Export HTML/);
  assert.match(byaanDashboardPreviewSource, /Export JSON/);
  assert.match(byaanDashboardPreviewSource, /Generate/);
  assert.match(byaanDashboardPreviewSource, /PDF export not configured/);
  assert.match(byaanDashboardPreviewSource, /Create share link/);
  assert.match(byaanDashboardPreviewSource, /ShareDashboardModal/);
  assert.match(byaanDashboardPreviewSource, /navigator\.clipboard\.writeText/);
  assert.match(byaanDashboardPreviewSource, /new Blob/);
  assert.match(byaanDashboardPreviewSource, /srcDoc=\{preview\.processedHtmlContent\}/);
  assert.match(byaanQueryRunnerDockedSource, /Query Runner/);
  assert.match(byaanQueryRunnerDockedSource, /NotebookQueryPanel/);
  assert.match(byaanQueryPanelSource, /QueryResults/);
  assert.doesNotMatch(byaanQueryPanelSource, /Query Runner/);
  assert.match(byaanQueryResultsSource, /governed/);
  assert.match(byaanSemanticEvidenceSource, /Metric definition/);
  assert.match(byaanSemanticEvidenceSource, /Freshness/);
  assert.match(byaanSemanticEvidenceSource, /Lineage/);
  assert.match(byaanNotebookAdapterSource, /semantic_query_result/);
  assert.match(byaanNotebookAdapterSource, /dashboardPreviewFromAgentKit/);
  assert.match(byaanNotebookAdapterSource, /policyDecisionRaw/);
  assert.match(cssSource, /\.byaan-notebook-source-port/);
  assert.match(cssSource, /\.byaan-notebook-workspace/);
  assert.match(cssSource, /\.byaan-dashboard-preview/);
  assert.match(cssSource, /@media \(max-width: 390px\)/);
  assert.doesNotMatch(cssSource, /kc-askdash-(native|portal-stage|dashboard-tiles|notebook-shell)/);
  assert.doesNotMatch(askDashboardSource, /ByaanNotebookDashboardSourcePort|Source-level port|Source-ported BYAAN workspace/);
  assert.doesNotMatch(
    [askDashboardSource, byaanNotebookSource, byaanDashboardPreviewSource].join("\n"),
    /from ["'][^"']*(ApiService|Tauri)|localhost:15183/,
  );
  assert.match(byaanAdapterSource, /agentkit_native_asktable_dashboard/);
  assert.match(knowledgeCenterSource, /<AskDashboardWorkbench/);
  assert.match(knowledgeCenterSource, /buildJobs=\{buildJobs\}/);
});
