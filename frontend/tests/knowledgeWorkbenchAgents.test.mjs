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

async function loadTsxModule(relativePath) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(relativePath, import.meta.url))],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "node20",
    plugins: [
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
  assert.match(semanticSource, /<MiniMap/);
  assert.match(semanticSource, /<Controls/);
  assert.match(semanticSource, /<Background/);
  assert.match(semanticSource, /onEdgeMouseEnter/);
  assert.match(semanticSource, /is-join-field/);
  assert.match(semanticSource, /relationshipHoverLabel/);
});

test("AskDashboard workspace exposes query evidence preview code tabs and disabled honest actions", () => {
  assert.match(askDashboardSource, /DashboardPreviewWorkspace/);
  assert.match(askDashboardSource, /DashboardQueryEvidencePanel/);
  assert.match(askDashboardSource, /Preview/);
  assert.match(askDashboardSource, /Code/);
  assert.match(askDashboardSource, /Queries/);
  assert.match(askDashboardSource, /SQL/);
  assert.match(askDashboardSource, /policyDecision/);
  assert.match(askDashboardSource, /freshness/);
  assert.match(askDashboardSource, /lineage/);
  assert.match(askDashboardSource, /evidence/);
  assert.match(askDashboardSource, /beginSplitResize/);
  assert.match(askDashboardSource, /kc-askdash-resizer/);
  assert.match(askDashboardSource, /aria-valuenow/);
  assert.match(askDashboardSource, /disabled title="后端导出能力尚未启用"/);
  assert.match(askDashboardSource, /disabled title="分享链接需要后端签名能力"/);
});

test("workbench CSS avoids horizontal page overflow and nested card shells on mobile", () => {
  assert.match(cssSource, /\.kc-semantic-layout\s*\{[\s\S]*?grid-template-columns: minmax\(210px, 260px\) minmax\(420px, 1fr\) minmax\(260px, 340px\)/);
  assert.match(cssSource, /\.kc-askdash-split\s*\{[\s\S]*?grid-template-columns: minmax\(320px, var\(--kc-askdash-left, 38%\)\) 8px minmax\(520px, 1fr\)/);
  assert.match(cssSource, /\.kc-askdash-resizer\s*\{[\s\S]*?cursor:\s*col-resize;/);
  assert.match(cssSource, /\.kc-semantic-node__section span\.is-join-field/);
  assert.match(cssSource, /\.kc-mobile-workbench-tabs\s*\{[\s\S]*?display:\s*none;/);
  assert.match(cssSource, /\.kc-semantic-layout\.is-tree-collapsed \.kc-semantic-tree/);
  assert.match(cssSource, /@media \(max-width: 980px\)[\s\S]*?\.kc-semantic-layout,[\s\S]*?\.kc-askdash-split\s*\{[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(cssSource, /\.kc-semantic-canvas\s*\{[\s\S]*?overflow:\s*hidden;/);
  assert.doesNotMatch(cssSource, /byaan|wrenai|iframe/);
});
