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
const wrenGroupTreeTitleSource = readFileSync(
  new URL("../src/features/knowledge-assets/source-ports/wren/original/sidebar/modeling/GroupTreeTitle.tsx", import.meta.url),
  "utf8",
);
const semanticBuildPanelSource = readFileSync(
  new URL("../src/knowledge-center/SemanticBuildPanel.tsx", import.meta.url),
  "utf8",
);
const semanticBuilderE2eSource = readFileSync(
  new URL("../../docs/knowledge-center/session-reports/session-j-semantic-builder-agentization/e2e_semantic_builder.py", import.meta.url),
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
  assert.match(panelSource, /streamSemanticBuild/);
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
  assert.match(wrenSourcePortSource, /DraftEditor/);
  assert.match(wrenSourcePortSource, /New Model/);
  assert.match(wrenOriginalSidebarSource, /Relationships" count=\{relationshipRows\.length\} onAction/);
  assert.match(wrenOriginalSidebarSource, /Metrics" count=\{metricRows\.length\} onAction/);
  assert.match(wrenSourcePortSource, /Publish/);
  assert.match(wrenSourcePortSource, /publishActionDisabledReason/);
  assert.match(wrenSourcePortSource, /onPublish/);
  assert.match(wrenSourcePortSource, /const canPublish/);
  assert.match(wrenSourcePortSource, /New View/);
  assert.match(wrenSourcePortSource, /onCreateView/);
  assert.match(wrenSourcePortSource, /Review/);
  assert.match(wrenSourcePortSource, /Advanced/);
  assert.match(wrenSourcePortSource, /语义草案 Review/);
  assert.doesNotMatch(wrenSourcePortSource, /StatusChip label="Runner"|StatusChip label="Mode"|StatusChip label="Drafts"/);
  assert.doesNotMatch(wrenGroupTreeTitleSource, /MoreHorizontal|adm-tree-more|aria-label=\{`\$\{title\} actions`\}/);
  assert.doesNotMatch(wrenOriginalSidebarSource, /Semantic Skills" count=\{semanticRows\.length\} onAction/);
  assert.match(wrenSourcePortSource, /Selected Raw JSON/);
  assert.match(wrenSourcePortSource, /No doc-to-MDL alignments persisted yet/);
  assert.match(wrenSourcePortSource, /Save Draft/);
  assert.doesNotMatch(wrenSourcePortSource, />Build</);
  assert.doesNotMatch(wrenSourcePortSource, />Deploy</);
  assert.match(wrenAdapterSource, /mdlToModelingViewModel/);
  assert.match(wrenAdapterSource, /agent_status/);
  assert.doesNotMatch(panelSource, /<iframe/);
  assert.doesNotMatch([wrenSourcePortSource, wrenOriginalDiagramSource, wrenOriginalModelNodeSource, wrenOriginalSidebarSource].join("\n"), /<iframe|from ["'][^"']*(Apollo|ApiService)|localhost:3011/);
  assert.doesNotMatch(panelSource, /DATASTUDIO_API_KEY/);
  assert.match(knowledgeCenterSource, /<SemanticModelingWorkbench/);
});

test("Semantic builder exposes persisted few-shot, instruction, feedback, view, and publish actions", () => {
  assert.match(semanticBuildPanelSource, /data-testid="semantic-few-shot-panel"/);
  assert.match(semanticBuildPanelSource, /data-testid="semantic-instructions-panel"/);
  assert.match(semanticBuildPanelSource, /createSemanticQuestionSqlPair/);
  assert.match(semanticBuildPanelSource, /updateSemanticQuestionSqlPair/);
  assert.match(semanticBuildPanelSource, /deleteSemanticQuestionSqlPair/);
  assert.match(semanticBuildPanelSource, /createSemanticInstruction/);
  assert.match(semanticBuildPanelSource, /updateSemanticInstruction/);
  assert.match(semanticBuildPanelSource, /deleteSemanticInstruction/);
  assert.match(semanticBuildPanelSource, /aria-label="Question"/);
  assert.match(semanticBuildPanelSource, /aria-label="SQL"/);
  assert.match(semanticBuildPanelSource, /aria-label="Instruction"/);
  assert.match(semanticBuildPanelSource, /告诉 Agent 如何调整语义/);
  assert.match(semanticBuildPanelSource, /data-testid="semantic-feedback-input"/);
  assert.match(semanticBuildPanelSource, /refineSemanticBuilderConversation/);
  assert.match(semanticBuildPanelSource, /data-testid="semantic-patch-diff"/);
  assert.match(semanticBuildPanelSource, /createSemanticBuilderViewDraft/);
  assert.match(semanticBuildPanelSource, /ViewDraftDialog/);
  assert.match(semanticBuildPanelSource, /publishSemanticBuilderDraft/);
  assert.match(semanticBuildPanelSource, /getSemanticBuilderConversation/);
  assert.match(semanticBuildPanelSource, /document_source_ids: selectedDocIds/);
  assert.match(semanticBuildPanelSource, /source_ids: selectedSourceId \? \[selectedSourceId\] : \[\]/);
  assert.match(semanticBuildPanelSource, /publish: false/);
  assert.doesNotMatch(semanticBuildPanelSource, /source_ids: \[selectedSourceId, \.\.\.selectedDocIds\]/);
  assert.match(semanticBuildPanelSource, /setInspector\("review"\)/);
  assert.match(semanticBuildPanelSource, /教 Agent 问数口径/);
  assert.doesNotMatch(semanticBuildPanelSource, /Training & Governance/);
});

test("Semantic builder keeps publish policy explicit and internal status copy hidden", () => {
  assert.match(semanticBuildPanelSource, /让 Agent 分析数据并生成语义草案/);
  assert.match(semanticBuildPanelSource, /草案已生成，等待你确认/);
  assert.match(wrenSourcePortSource, /Semantic Builder 高级设置/);
  assert.match(wrenSourcePortSource, /发布策略：生成后仍保存为 Draft，发布必须在 Review 后显式确认/);
  assert.doesNotMatch(wrenSourcePortSource, /Publish after build/);
  assert.doesNotMatch(`${semanticBuildPanelSource}\n${wrenSourcePortSource}`, /Runner pending|agent_tool_stream|Build succeeded/);
});

test("Session J Playwright gate covers browser CRUD and reload persistence", () => {
  assert.match(semanticBuilderE2eSource, /add_browser_few_shot/);
  assert.match(semanticBuilderE2eSource, /add_browser_instruction/);
  assert.match(semanticBuilderE2eSource, /verify_reload_persistence/);
  assert.match(semanticBuilderE2eSource, /page\.reload\(wait_until="networkidle"\)/);
  assert.match(semanticBuilderE2eSource, /Browser E2E sales by month/);
  assert.match(semanticBuilderE2eSource, /Use order_date as the default sales time grain/);
});

test("knowledgeAssets client exposes semantic builder stream and draft endpoints", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, headers: init.headers ?? {} });
    const path = String(url);
    if (path.includes("/semantic-builder/conversations") && path.endsWith("/messages")) {
      return Response.json({
        schema: "agentkit.semantic_builder.conversation.v1",
        id: "sbc_1",
        space_id: "space_1",
        semantic_pack_id: "sales_semantic",
        draft_pack_id: "sales_semantic",
        title: "Refine",
        source_ids: [],
        snapshot_ids: [],
        metadata: {},
        revisions: [],
        latest_revision: {
          schema: "agentkit.semantic_builder.revision.v1",
          id: "rev_1",
          conversation_id: "sbc_1",
          semantic_pack_id: "sales_semantic",
          revision_number: 2,
          author_role: "user",
          message: "hide phone",
          patch: {},
          diff: [],
          status: "draft",
        },
        draft: { schema: "agentkit.semantic_pack.detail.v1", semantic_pack_id: "sales_semantic", asset: {}, structured_mdl: {}, doc_graph: {}, alignments: [], few_shot: [], instructions: [], graph_objects: [], graph_relations: [], provenance: {}, policy: {}, eval_seed: {}, skill_runtime: {} },
        diff: [{ kind: "policy", action: "updated" }],
      });
    }
    if (path.includes("/semantic-builder/conversations")) {
      return Response.json({
        schema: "agentkit.semantic_builder.conversation.v1",
        id: "sbc_1",
        space_id: "space_1",
        semantic_pack_id: "sales_semantic",
        draft_pack_id: "sales_semantic",
        title: "Refine",
        source_ids: [],
        snapshot_ids: [],
        metadata: {},
        revisions: [],
      });
    }
    if (path.includes("/views")) {
      return Response.json({ schema: "agentkit.semantic_builder.view_draft.v1", semantic_pack_id: "sales_semantic", view: { id: "view_1" }, diff: [], draft: {} });
    }
    if (path.includes("/publish")) {
      return Response.json({ schema: "agentkit.semantic_builder.publish.v1", semantic_pack_id: "sales_semantic", asset: { publish_state: "published" }, publish_state: "published" });
    }
    return new Response(
      [
        "event: agent_message",
        'data: {"event_type":"agent_message","sequence":1,"payload":{"message":"start"}}',
        "",
        "event: job_status",
        'data: {"event_type":"job_status","sequence":2,"payload":{"job_id":"job_1","status":"blocked"}}',
        "",
      ].join("\n"),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
  };
  try {
    const {
      createSemanticBuilderConversation,
      createSemanticBuilderViewDraft,
      publishSemanticBuilderDraft,
      refineSemanticBuilderConversation,
      streamSemanticBuild,
    } = await loadTypeScriptModule("../src/adk/knowledgeAssets.ts");
    const observed = [];
    const events = await streamSemanticBuild({
      space_id: "space_1",
      source_ids: ["src_1"],
      document_source_ids: ["doc_1"],
      snapshot_ids: ["snap_1"],
      name: "Sales Semantic",
      publish: false,
    }, (event) => observed.push(event));
    await createSemanticBuilderConversation({ space_id: "space_1", semantic_pack_id: "sales_semantic", document_source_ids: ["doc_1"] });
    await refineSemanticBuilderConversation("sbc_1", { message: "hide phone", semantic_pack_id: "sales_semantic" });
    await createSemanticBuilderViewDraft("sales_semantic", { name: "Monthly trend", base_metric: "gmv" });
    await publishSemanticBuilderDraft("sales_semantic");
    assert.equal(events.at(-1).payload.status, "blocked");
    assert.equal(observed.length, 2);
    assert.equal(calls[0].url, "/api/knowledge-assets/semantic-build/stream");
    assert.equal(calls[0].method, "POST");
    assert.equal(calls[0].headers.accept, "text/event-stream");
    assert.deepEqual(JSON.parse(calls[0].body), {
      space_id: "space_1",
      source_ids: ["src_1"],
      document_source_ids: ["doc_1"],
      snapshot_ids: ["snap_1"],
      name: "Sales Semantic",
      publish: false,
    });
    assert.equal(calls[1].url, "/api/knowledge-assets/semantic-builder/conversations");
    assert.match(calls[2].url, /\/api\/knowledge-assets\/semantic-builder\/conversations\/sbc_1\/messages/);
    assert.match(calls[3].url, /\/api\/knowledge-assets\/semantic-builder\/drafts\/sales_semantic\/views/);
    assert.match(calls[4].url, /\/api\/knowledge-assets\/semantic-builder\/drafts\/sales_semantic\/publish/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Semantic build CSS is responsive without product iframe shell", () => {
  assert.match(cssSource, /\.kc-semantic-agent-workbench/);
  assert.match(cssSource, /\.kc-agent-timeline/);
  assert.match(cssSource, /\.kc-semantic-feedback/);
  assert.match(cssSource, /\.kc-semantic-patch-diff/);
  assert.match(cssSource, /\.kc-semantic-view-dialog/);
  assert.match(cssSource, /\.kc-review-grid/);
  assert.match(cssSource, /\.kc-native-sidebar:hover/);
  assert.match(cssSource, /\.adm-draft-editor/);
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
