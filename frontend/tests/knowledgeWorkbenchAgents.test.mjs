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

test("AskDashboard workspace renders native notebook portal, chat answers, preview tabs, and honest blocked states", () => {
  assert.match(askDashboardSource, /kc-askdash-portal-stage/);
  assert.match(askDashboardSource, /What do you need to know\?/);
  assert.match(askDashboardSource, /kc-askdash-composer/);
  assert.match(askDashboardSource, /kc-askdash-example-chips/);
  assert.match(askDashboardSource, /kc-askdash-notebook-shell/);
  assert.match(askDashboardSource, /kc-askdash-chat-area/);
  assert.match(askDashboardSource, /kc-askdash-message-list/);
  assert.match(askDashboardSource, /kc-askdash-preview-panel/);
  assert.match(askDashboardSource, /MobilePaneTabs/);
  assert.match(askDashboardSource, /PreviewTabButton/);
  assert.match(askDashboardSource, /QueriesPanel/);
  assert.match(askDashboardSource, /LineagePanel/);
  assert.match(askDashboardSource, /CodePanel/);
  assert.match(askDashboardSource, /EvidenceGrid/);
  assert.match(askDashboardSource, /MiniResultTable/);
  assert.match(askDashboardSource, /queryAskData/);
  assert.match(askDashboardSource, /buildDashboardSkill/);
  assert.match(askDashboardSource, /\/api\/knowledge-assets\/askdata\/query|queryAskData/);
  assert.match(askDashboardSource, /\/api\/knowledge-assets\/build\/dashboard-skill|buildDashboardSkill/);
  assert.match(askDashboardSource, /askDataToNotebookViewModel/);
  assert.match(askDashboardSource, /dashboardSpecToByaanViewModel/);
  assert.match(askDashboardSource, /blocked_no_semantic_skill/);
  assert.match(askDashboardSource, /no published Semantic Skill/);
  assert.match(askDashboardSource, /不会伪造 query 或 dashboard 成功/);
  assert.match(askDashboardSource, /SQL/);
  assert.match(askDashboardSource, /Metric definition/);
  assert.match(askDashboardSource, /Permission policy/);
  assert.match(askDashboardSource, /Freshness/);
  assert.match(askDashboardSource, /Lineage/);
  assert.match(askDashboardSource, /Evidence/);
  assert.match(askDashboardSource, /Generate Dashboard/);
  assert.match(askDashboardSource, /data-asktable-state="portal"/);
  assert.match(cssSource, /\.kc-askdash-native/);
  assert.match(cssSource, /\.kc-askdash-portal-stage/);
  assert.match(cssSource, /\.kc-askdash-notebook-shell/);
  assert.match(cssSource, /\.kc-askdash-preview-panel/);
  assert.match(cssSource, /\.kc-askdash-mobile-tabs/);
  assert.match(cssSource, /\.kc-askdash-notebook-shell\.is-mobile-answer \.kc-askdash-preview-panel/);
  assert.doesNotMatch(askDashboardSource, /ByaanNotebookDashboardSourcePort|QueryRunnerDocked|Source-level port|Source-ported BYAAN workspace/);
  assert.doesNotMatch(
    askDashboardSource,
    /from ["'][^"']*(ApiService|Tauri)|<iframe|localhost:15183/,
  );
  assert.match(byaanAdapterSource, /agentkit_native_asktable_dashboard/);
  assert.match(byaanAdapterSource, /agentkit_governed_rest/);
});

test("AskDashboard no-model path renders blocked native notebook shell", async () => {
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

  assert.match(markup, /data-testid="askdashboard-not-configured-blocked"/);
  assert.match(markup, /blocked_no_semantic_skill/);
  assert.match(markup, /not_configured/);
  assert.match(markup, /No Semantic Skill/);
  assert.match(markup, /Publish a Semantic Skill before asking data questions/);
  assert.match(markup, /What do you need to know\?/);
  assert.match(markup, /不会伪造 query 或 dashboard 成功/);
  assert.match(markup, /class="kc-askdash-composer is-portal"/);
  assert.match(markup, /class="kc-askdash-example-chips"/);
  assert.match(markup, /<button type="submit" class="kc-askdash-send" disabled="">/);
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
  assert.match(cssSource, /\.kc-mobile-workbench-tabs\s*\{[\s\S]*?display:\s*none;/);
  assert.match(cssSource, /\.kc-wren-modeling-layout\.is-tree-collapsed \.kc-wren-sidebar/);
  assert.match(cssSource, /@media \(max-width: 980px\)[\s\S]*?\.kc-wren-modeling-layout,[\s\S]*?\.kc-byaan-workspace-grid\s*\{[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(cssSource, /\.kc-wren-diagram\s*\{[\s\S]*?overflow:\s*hidden;/);
  assert.match(cssSource, /\.kc-byaan-query-editor/);
  assert.doesNotMatch(cssSource, /iframe|wren-ui|wrenai-legacy|byaan-knowledge-center|localhost:15183|localhost:3011/);
});
