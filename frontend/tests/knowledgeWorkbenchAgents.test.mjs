import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const require = createRequire(import.meta.url);
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const semanticSource = readFileSync(
  new URL("../src/knowledge-center/SemanticModelingWorkbench.tsx", import.meta.url),
  "utf8",
);
const askDashboardSource = readFileSync(
  new URL("../src/knowledge-center/AskDashboardWorkbench.tsx", import.meta.url),
  "utf8",
);
const knowledgeAssetsSource = readFileSync(
  new URL("../src/adk/knowledgeAssets.ts", import.meta.url),
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
const wrenOriginalViewNodeSource = readFileSync(
  new URL("../src/features/knowledge-assets/source-ports/wren/original/customNode/ViewNode.tsx", import.meta.url),
  "utf8",
);
const wrenOriginalEdgeSource = readFileSync(
  new URL("../src/features/knowledge-assets/source-ports/wren/original/customEdge/ModelEdge.tsx", import.meta.url),
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
const byaanResizableSplitSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/ResizableSplitPanel.tsx", import.meta.url),
  "utf8",
);
const byaanTableMentionInputSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/TableMentionInput.tsx", import.meta.url),
  "utf8",
);
const byaanSemanticEvidenceSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/SemanticEvidencePanel.tsx", import.meta.url),
  "utf8",
);
const byaanMessageSource = readFileSync(
  new URL("../src/features/knowledge-assets/byaan-notebook/Message.tsx", import.meta.url),
  "utf8",
);

async function loadTsxModule(relativePath) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(relativePath, import.meta.url))],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "node20",
    plugins: [
      {
        name: "external-react",
        setup(pluginBuild) {
          pluginBuild.onResolve({ filter: /^react(\/jsx-runtime)?$/ }, (args) => ({
            path: require.resolve(args.path),
            external: true,
          }));
        },
      },
      {
        name: "ignore-css",
        setup(pluginBuild) {
          pluginBuild.onLoad({ filter: /\.css$/ }, () => ({
            contents: "",
            loader: "js",
          }));
        },
      },
    ],
    write: false,
  });
  const id = createHash("sha1").update(relativePath).digest("hex").slice(0, 10);
  const outDir = join(tmpdir(), "veadk-frontend-tests");
  await mkdir(outDir, { recursive: true });
  const outFile = join(outDir, `knowledge-workbench-${id}.cjs`);
  await writeFile(outFile, result.outputFiles[0].contents);
  delete require.cache[outFile];
  return require(outFile);
}

test("semantic graph helper renders fixture MDL and exposes join hover metadata", async () => {
  const { buildSemanticGraph, relationshipFieldHighlights } = await loadTsxModule(
    "../src/knowledge-center/SemanticModelingWorkbench.tsx",
  );
  const graph = buildSemanticGraph({
    entities: [
      {
        id: "sales",
        table: "sales_order",
        fields: [
          { name: "ticket_id", type: "number", primary_key: true },
          { name: "store_id", type: "number" },
        ],
      },
      {
        id: "store",
        table: "store",
        fields: [{ name: "store_id", type: "number", primary_key: true }],
      },
    ],
    metrics: [{ id: "ticket_count", entity: "sales" }],
    dimensions: [{ id: "store_name", entity: "store" }],
    relationships: [{ id: "sales_store", from: "sales", to: "store", join_fields: [{ from: "store_id", to: "store_id" }] }],
  });

  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.edges.length, 1);
  assert.equal(graph.nodes[0].type, "semanticNode");
  assert.equal(graph.edges[0].id, "sales_store");
  assert.deepEqual(relationshipFieldHighlights(graph.edges[0].data), {
    source: ["store_id"],
    target: ["store_id"],
  });
  assert.match(wrenOriginalDiagramSource, /<MiniMap/);
  assert.match(wrenOriginalDiagramSource, /<Controls/);
  assert.match(wrenOriginalDiagramSource, /<Background/);
  assert.match(semanticSource, /SemanticWorkbenchState/);
  assert.match(semanticSource, /aria-label="Semantic Skill"/);
  assert.match(semanticSource, /WrenModelingSourcePort/);
  assert.match(semanticSource, /createWrenSemanticSourcePortViewModel/);
  assert.match(wrenSourcePortSource, /Source-level port of Wren UI modeling workspace/);
  assert.match(wrenSourcePortSource, /wren-ui\/src\/pages\/modeling\.tsx/);
  assert.match(wrenSourcePortSource, /original\/diagram/);
  assert.match(wrenSourcePortSource, /original\/sidebar\/Modeling/);
  assert.match(wrenOriginalSidebarSource, /ModelTree/);
  assert.match(wrenOriginalSidebarSource, /ViewTree/);
  assert.match(wrenOriginalModelNodeSource, /export const ModelNode/);
  assert.match(wrenOriginalViewNodeSource, /export const ViewNode/);
  assert.match(wrenOriginalEdgeSource, /export const ModelEdge/);
  assert.match(wrenOriginalDiagramSource, /onEdgeMouseEnter/);
  assert.match(wrenOriginalModelNodeSource, /bg-gray-3/);
  assert.match(wrenAdapterSource, /mdlToModelingViewModel/);
  assert.match(wrenAdapterSource, /AgentKit adapter/);
  assert.doesNotMatch(
    [
      wrenSourcePortSource,
      wrenOriginalDiagramSource,
      wrenOriginalModelNodeSource,
      wrenOriginalViewNodeSource,
      wrenOriginalEdgeSource,
      wrenOriginalSidebarSource,
    ].join("\n"),
    /from ["'][^"']*(Apollo|ApiService)|<iframe|localhost:3011/,
  );
});

test("AskDashboard workspace source-ports BYAAN notebook components and keeps the governed stream adapter", () => {
  assert.match(askDashboardSource, /from "\.\.\/features\/knowledge-assets\/byaan-notebook"/);
  assert.match(askDashboardSource, /<ByaanNotebook/);
  assert.match(askDashboardSource, /streamAskData/);
  assert.match(askDashboardSource, /parseSSE/);
  assert.match(askDashboardSource, /applyEvent/);
  assert.match(askDashboardSource, /query_semantic_skill/);
  assert.match(askDashboardSource, /queryResultFromEvent/);
  assert.match(askDashboardSource, /dashboardResultFromEvent/);
  assert.doesNotMatch(askDashboardSource, /queryAskData/);
  assert.doesNotMatch(askDashboardSource, /buildDashboardSkill/);
  assert.doesNotMatch(askDashboardSource, /Returned .*governed rows/);
  assert.doesNotMatch(
    askDashboardSource,
    /function (AskTablePortal|AskComposer|QueryRoundView|DashboardNotebookPreview|DashboardCanvas|MiniResultTable)/,
  );
  assert.doesNotMatch(askDashboardSource, /kc-askdash-portal-stage|kc-askdash-dashboard-tiles/);
  assert.match(knowledgeAssetsSource, /streamAskData/);
  assert.match(knowledgeAssetsSource, /\/api\/knowledge-assets\/askdata\/stream/);

  assert.match(byaanNotebookSource, /data-source-port="byaan-notebook"/);
  assert.match(byaanNotebookSource, /byaan-notebook-source-port/);
  assert.match(byaanNotebookSource, /What do you need to know\?/);
  assert.match(byaanNotebookSource, /ResizableSplitPanel/);
  assert.match(byaanNotebookSource, /MessageList/);
  assert.match(byaanNotebookSource, /DashboardPreviewPanel/);
  assert.match(byaanNotebookSource, /TableMentionInput/);
  assert.match(byaanNotebookSource, /SemanticEvidencePanel/);
  assert.match(byaanNotebookSource, /SemanticModelPicker/);
  assert.match(byaanMessageSource, /<Blocks/);
  assert.match(byaanTableMentionInputSource, /onSubmit/);
  assert.match(byaanResizableSplitSource, /role="separator"/);
  assert.match(byaanSemanticEvidenceSource, /Governed evidence/);
  assert.match(byaanSemanticEvidenceSource, /Compiled SQL/);
  assert.match(byaanSemanticEvidenceSource, /Metric definition/);
  assert.match(byaanSemanticEvidenceSource, /Freshness/);
  assert.match(byaanSemanticEvidenceSource, /Lineage/);
  assert.match(byaanDashboardPreviewSource, /processedHtmlContent/);
  assert.match(byaanDashboardPreviewSource, /Preview/);
  assert.match(byaanDashboardPreviewSource, /Code/);
  assert.match(byaanDashboardPreviewSource, /Queries/);
  assert.match(byaanDashboardPreviewSource, /QueryRunnerDocked/);
  assert.match(byaanDashboardPreviewSource, /Export HTML/);
  assert.match(byaanDashboardPreviewSource, /Fullscreen/);
  assert.match(byaanDashboardPreviewSource, /srcDoc=\{preview\.processedHtmlContent\}/);
  assert.match(byaanQueryRunnerDockedSource, /Query Runner/);
  assert.match(byaanQueryRunnerDockedSource, /NotebookQueryPanel/);
  assert.match(byaanQueryRunnerDockedSource, /Back to versions/);
  assert.match(byaanQueryPanelSource, /QueryResults/);
  assert.doesNotMatch(byaanQueryPanelSource, /Query Runner/);
  assert.match(byaanQueryResultsSource, /governed/);
  assert.match(byaanNotebookAdapterSource, /semantic_query_result/);
  assert.match(byaanNotebookAdapterSource, /askDataToSemanticQueryResultEvent/);
  assert.match(byaanNotebookAdapterSource, /dashboardPreviewFromAgentKit/);
  assert.match(byaanNotebookAdapterSource, /roundsToByaanMessages/);
  assert.match(byaanNotebookAdapterSource, /policyDecisionRaw/);
  assert.match(byaanNotebookAdapterSource, /freshness/);
  assert.match(byaanNotebookAdapterSource, /lineage/);

  assert.match(cssSource, /\.byaan-notebook-source-port/);
  assert.match(cssSource, /\.byaan-notebook-workspace/);
  assert.match(cssSource, /\.byaan-dashboard-preview/);
  assert.match(cssSource, /\.byaan-toolbar-icon/);
  assert.match(cssSource, /@media \(max-width: 390px\)/);
  assert.doesNotMatch(cssSource, /kc-askdash-(native|portal-stage|dashboard-tiles|notebook-shell)/);
  assert.doesNotMatch(askDashboardSource, /ByaanNotebookDashboardSourcePort|Source-level port|Source-ported BYAAN workspace/);
  assert.doesNotMatch(
    [askDashboardSource, byaanNotebookSource, byaanDashboardPreviewSource].join("\n"),
    /from ["'][^"']*(ApiService|Tauri)|localhost:15183/,
  );
  assert.match(byaanAdapterSource, /agentkit_native_asktable_dashboard/);
  assert.match(byaanAdapterSource, /agentkit_governed_rest/);
});

test("AskDashboard no-model path renders BYAAN source-port portal in fail-closed state", async () => {
  const { AskDashboardWorkbench } = await loadTsxModule("../src/knowledge-center/AskDashboardWorkbench.tsx");
  const markup = renderToStaticMarkup(
    React.createElement(AskDashboardWorkbench, {
      activeSpace: null,
      semanticSkills: [],
      dashboardSkills: [],
      buildJobs: [],
      onRefresh: () => {},
    }),
  );

  assert.match(markup, /data-source-port="byaan-notebook"/);
  assert.match(markup, /byaan-notebook-source-port byaan-notebook-portal/);
  assert.match(markup, /No published models/);
  assert.match(markup, /No Semantic Model/);
  assert.match(markup, /Publish a Semantic Skill before asking data questions/);
  assert.match(markup, /What do you need to know\?/);
  assert.match(markup, /byaan-table-mention-composer/);
  assert.match(markup, /disabled=""/);
});

test("workbench CSS avoids horizontal page overflow and nested card shells on mobile", () => {
  assert.match(cssSource, /\.kc-semantic-layout\s*\{[\s\S]*?grid-template-columns: minmax\(210px, 260px\) minmax\(420px, 1fr\) minmax\(260px, 340px\)/);
  assert.match(cssSource, /\.kc-wren-modeling-layout\s*\{[\s\S]*?grid-template-columns: minmax\(220px, 276px\) minmax\(480px, 1fr\) minmax\(280px, 360px\)/);
  assert.match(cssSource, /\.kc-byaan-workspace-grid/);
  assert.match(cssSource, /\.adm-styled-node/);
  assert.match(cssSource, /\.adm-node-header/);
  assert.match(cssSource, /\.adm-sidebar-tree/);
  assert.match(cssSource, /\.kc-byaan-original-query-editor/);
  assert.match(cssSource, /\.kc-byaan-dashboard-preview/);
  assert.match(cssSource, /\.kc-semantic-node__section span\.is-join-field/);
  assert.match(cssSource, /\.adm-node-column:hover,\n\.adm-node-column\.bg-gray-3/);
  assert.match(cssSource, /\.kc-byaan-preview-toolbar button\.is-active/);
  assert.match(cssSource, /\.kc-byaan-original-query-results/);
  assert.match(cssSource, /\.kc-byaan-sparkline/);
  assert.match(cssSource, /\.kc-byaan-data-views/);
  assert.match(cssSource, /\.kc-byaan-blocked-shell/);
  assert.match(cssSource, /\.byaan-notebook-source-port/);
  assert.match(cssSource, /\.byaan-notebook-source-port \.resizable-split-panel/);
  assert.match(cssSource, /\.byaan-notebook-fullscreen/);
  assert.match(cssSource, /\.byaan-menu-item/);
  assert.match(cssSource, /@media \(max-width: 560px\)[\s\S]*?\.byaan-dashboard-preview > div:first-child/);
  assert.doesNotMatch(cssSource, /kc-askdash-(native|portal-stage|dashboard-tiles|notebook-shell)/);
  assert.match(cssSource, /\.kc-mobile-workbench-tabs\s*\{[\s\S]*?display:\s*none;/);
  assert.match(cssSource, /\.kc-wren-modeling-layout\.is-tree-collapsed \.kc-wren-sidebar/);
  assert.match(cssSource, /@media \(max-width: 980px\)[\s\S]*?\.kc-wren-modeling-layout,[\s\S]*?\.kc-byaan-workspace-grid\s*\{[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(cssSource, /\.kc-wren-diagram\s*\{[\s\S]*?overflow:\s*hidden;/);
  assert.match(cssSource, /\.kc-byaan-query-editor/);
  assert.doesNotMatch(cssSource, /wren-ui|wrenai-legacy|byaan-knowledge-center|localhost:15183|localhost:3011/);
});
