import assert from "node:assert/strict";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mkdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const require = createRequire(import.meta.url);

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
  const outFile = join(outDir, `datastudio-${id}.cjs`);
  await writeFile(outFile, result.outputFiles[0].contents);
  delete require.cache[outFile];
  return require(outFile);
}

const { dataStudioAssetToHit } = await loadTypeScriptModule(
  "../src/create/skills/datastudio.ts",
);
const {
  dataStudioEmptyStateText,
  toggleDataStudioSelection,
} = await loadTypeScriptModule("../src/create/DataStudioAssetPicker.tsx");
const { draftToYaml, yamlToDraft } = await loadTypeScriptModule(
  "../src/create/configYaml.ts",
);

test("Data Studio asset adapter preserves REST query_url for picker cards", () => {
  const hit = dataStudioAssetToHit({
    asset_type: "dashboard",
    asset_id: "sales",
    name: "Sales Dashboard",
    description: "Daily revenue",
    publish_state: "published",
    gate: { score: 91 },
    version: "v1",
    capabilities: {
      metrics: ["GMV", "Orders"],
      dimensions: ["Channel"],
      time_field: "pay_date",
      example_questions: ["GMV by channel?"],
    },
    usage_policy: { permission_hint: "Aggregated only" },
    sample_evidence: [{ type: "sql", content: "select sum(gmv)" }],
    query_url: "/api/external/assets/dashboard/sales/query",
  });

  assert.equal(hit.source, "datastudio");
  assert.equal(hit.dataStudioAssetType, "dashboard");
  assert.equal(hit.dataStudioAssetId, "sales");
  assert.equal(hit.dataStudioGateScore, 91);
  assert.deepEqual(hit.dataStudioMetrics, ["GMV", "Orders"]);
  assert.equal(hit.dataStudioQueryUrl, "/api/external/assets/dashboard/sales/query");
  assert.equal(hit.dataStudioPermissionHint, "Aggregated only");
});

test("Data Studio asset adapter accepts live BYAAN capability objects", () => {
  const hit = dataStudioAssetToHit({
    asset_type: "dashboard",
    asset_id: "live",
    name: "Live Dashboard",
    publish_state: "published",
    capabilities: {
      metrics: [
        { id: "paid_revenue", businessName: "Paid Revenue" },
        { name: "order_count" },
      ],
      dimensions: [{ id: "order_status" }, { field: "paid_at" }],
    },
  });

  assert.deepEqual(hit.dataStudioMetrics, ["paid_revenue", "order_count"]);
  assert.deepEqual(hit.dataStudioDimensions, ["order_status", "paid_at"]);
});

test("Data Studio asset adapter preserves structured BYAAN evidence", () => {
  const hit = dataStudioAssetToHit({
    asset_type: "semantic_model",
    asset_id: "sales-model",
    name: "Sales Model",
    publish_state: "published",
    sample_evidence: [
      {
        kind: "metric_definition",
        metric: "revenue_revenue",
        definition: "Sum of paid order revenue.",
        formula: "sum(revenue)",
      },
      {
        kind: "permission_policy",
        policy: {
          allowedMetrics: ["revenue_revenue"],
          allowedDimensions: ["revenue_region"],
        },
      },
    ],
  });

  assert.deepEqual(hit.dataStudioEvidence, [
    "metric_definition: metric=revenue_revenue; definition=Sum of paid order revenue.; formula=sum(revenue)",
    'permission_policy: policy={"allowedMetrics":["revenue_revenue"],"allowedDimensions":["revenue_region"]}',
  ]);
});

test("Data Studio picker empty states and multi-select behavior are deterministic", () => {
  assert.equal(
    dataStudioEmptyStateText({ error: { status: 409, message: "" }, query: "" }),
    "未配置连接：请在服务端配置 Data Studio 连接，或临时开启 mock。",
  );
  assert.equal(
    dataStudioEmptyStateText({ error: { status: 401, message: "" }, query: "" }),
    "未登录：请先登录 Studio。",
  );

  const local = { source: "local", folder: "local-skill", name: "Local Skill", localFiles: [] };
  const hit = dataStudioAssetToHit({
    asset_type: "semantic_model",
    asset_id: "retention",
    name: "Retention Model",
    publish_state: "published",
    query_url: "/api/external/assets/semantic_model/retention/query",
  });
  const selected = toggleDataStudioSelection([local], hit);
  assert.equal(selected.length, 2);
  assert.equal(selected[1].dataStudioQueryUrl, "/api/external/assets/semantic_model/retention/query");
  assert.deepEqual(toggleDataStudioSelection(selected, hit), [local]);
});

test("Data Studio selected skill round-trips through YAML", () => {
  const source = {
    name: "datastudio_agent",
    description: "Uses governed BI assets",
    instruction: "Answer with evidence.",
    agentType: "llm",
    tools: [],
    skills: [],
    customTools: [],
    mcpTools: [],
    subAgents: [],
    selectedSkills: [
      {
        source: "datastudio",
        folder: "datastudio-dashboard-sales",
        name: "Sales Dashboard",
        description: "Daily sales KPIs",
        dataStudioAssetType: "dashboard",
        dataStudioAssetId: "sales-dashboard",
        dataStudioVersion: "v3",
        dataStudioGateScore: 94,
        dataStudioQueryUrl: "/api/external/assets/dashboard/sales-dashboard/query",
        dataStudioMetrics: ["GMV", "Orders"],
        dataStudioPermissionHint: "Aggregated metrics only",
      },
    ],
  };

  const yaml = draftToYaml(source);
  assert.match(yaml, /selectedSkills:/);
  assert.match(yaml, /source: datastudio/);
  assert.match(yaml, /dataStudioQueryUrl:/);
  assert.doesNotMatch(yaml, /BYAAN_MCP_API_KEY/);
  assert.doesNotMatch(yaml, /api\/mcp\/assets/);

  const restored = yamlToDraft(yaml);
  assert.equal(
    restored.selectedSkills[0].dataStudioQueryUrl,
    source.selectedSkills[0].dataStudioQueryUrl,
  );
});
