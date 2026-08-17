import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { dataStudioAssetToHit } from "../src/create/skills/datastudio.ts";
import { toggleDataStudioSelection, dataStudioEmptyStateText } from "../src/create/datastudioSelection.ts";
import { codegenDraft } from "../src/create/codegenDraft.ts";
import { draftToYaml, yamlToDraft } from "../src/create/configYaml.ts";

const knowledgeSource = readFileSync(new URL("../src/knowledge-center/KnowledgeCenter.tsx", import.meta.url), "utf8");

test("Data Studio asset adapter preserves REST query_url for picker cards", () => {
  const hit = dataStudioAssetToHit({
    asset_type: "dashboard",
    asset_id: "sales",
    name: "Sales Dashboard",
    description: "Daily revenue",
    status: "published",
    publish_state: "published",
    gate: { score: 91 },
    version: "v1",
    consumers: ["agent"],
    capabilities: {
      metrics: ["GMV", "Orders"],
      dimensions: ["Channel"],
      time_field: "pay_date",
      example_questions: ["GMV by channel?"],
    },
    freshness: {},
    provenance: {},
    usage_policy: { permission_hint: "Aggregated only" },
    sample_evidence: [{ type: "sql", content: "select sum(gmv)" }],
    query_url: "https://byaan.example/api/external/assets/dashboard/sales/query",
  });

  assert.equal(hit.source, "datastudio");
  assert.equal(hit.dataStudioAssetType, "dashboard");
  assert.equal(hit.dataStudioAssetId, "sales");
  assert.equal(hit.dataStudioGateScore, 91);
  assert.deepEqual(hit.dataStudioMetrics, ["GMV", "Orders"]);
  assert.equal(hit.dataStudioQueryUrl, "https://byaan.example/api/external/assets/dashboard/sales/query");
  assert.equal(hit.dataStudioPermissionHint, "Aggregated only");
  assert.equal(hit.dataStudioMcpUrl, undefined);
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
  assert.equal(dataStudioEmptyStateText({ error: null, query: "gmv" }), "搜索无结果，换个关键词试试。");

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

test("Data Studio assets round-trip through YAML and codegen draft without MCP URLs", () => {
  const source = {
    name: "datastudio_agent",
    description: "Uses governed BI assets",
    instruction: "Answer with evidence.",
    agentType: "llm",
    tools: [],
    skills: [],
    customTools: [],
    mcpTools: [],
    selectedSkills: [],
    subAgents: [],
    deployment: { feishuEnabled: false },
    dataAssets: [
      {
        source: "datastudio",
        folder: "datastudio-dashboard-sales",
        name: "Sales Dashboard",
        description: "Daily sales KPIs",
        dataStudioAssetType: "dashboard",
        dataStudioAssetId: "sales-dashboard",
        dataStudioVersion: "v3",
        dataStudioGateScore: 94,
        dataStudioQueryUrl: "https://byaan.example/api/external/assets/dashboard/sales-dashboard/query",
        dataStudioMetrics: ["GMV", "Orders"],
        dataStudioPermissionHint: "Aggregated metrics only",
      },
    ],
  };

  const yaml = draftToYaml(source);
  assert.match(yaml, /dataAssets:/);
  assert.match(yaml, /dataStudioQueryUrl:/);
  assert.doesNotMatch(yaml, /BYAAN_MCP_API_KEY/);
  assert.doesNotMatch(yaml, /api\/mcp\/assets/);

  const restored = yamlToDraft(yaml);
  assert.equal(restored.dataAssets[0].dataStudioQueryUrl, source.dataAssets[0].dataStudioQueryUrl);

  const codegen = codegenDraft(restored);
  assert.deepEqual(codegen.mcpTools, []);
  assert.equal(codegen.dataAssets[0].dataStudioMcpUrl, "");
  assert.equal(codegen.dataAssets[0].dataStudioQueryUrl, source.dataAssets[0].dataStudioQueryUrl);
});

test("Knowledge Center shell has locked embed and trusted postMessage contract", () => {
  assert.match(knowledgeSource, /KnowledgeCenterMessage/);
  assert.match(knowledgeSource, /eventOrigin !== trustedOrigin/);
  assert.match(knowledgeSource, /veadk\.knowledge-center\.asset-published/);
  assert.match(knowledgeSource, /unconfigured/);
  assert.match(knowledgeSource, /unauthenticated/);
  assert.match(knowledgeSource, /unreachable/);
  assert.doesNotMatch(knowledgeSource, /DATASTUDIO_API_KEY/);
  assert.doesNotMatch(knowledgeSource, /api\/mcp\/assets/);
});
