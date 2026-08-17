import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

const read = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");
const readRepo = (path) =>
  readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

const appSource = read("App.tsx");
const sidebarSource = read("ui/Sidebar.tsx");
const skillCenterSource = read("ui/SkillCenter.tsx");
const searchSource = read("ui/Search.tsx");
const clientSource = read("adk/client.ts");
const serverSource = readRepo("veadk/cli/cli_frontend.py");
const gatewaySource = readRepo("frontend/server/datastudio/gateways.py");
const dataStudioRoutesSource = readRepo("frontend/server/datastudio/routes.py");
const dataStudioServiceSource = readRepo("frontend/server/datastudio/service.py");
const knowledgeSource = read("knowledge-center/KnowledgeCenter.tsx");
const knowledgeStyles = read("knowledge-center/KnowledgeCenter.css");
const nativeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveSource(fromDir, specifier) {
  const base = path.resolve(fromDir, specifier);
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    `${base}.js`,
    path.join(base, "index.ts"),
  ]) {
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(`Cannot resolve ${specifier} from ${fromDir}`);
}

function loadTypeScriptCommonJs(relativePath) {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  return loadFile(resolveSource(testDir, relativePath));
}

function loadFile(filePath) {
  const key = path.resolve(filePath);
  if (key.endsWith(".css")) return {};
  const cached = moduleCache.get(key);
  if (cached) return cached.exports;

  const source = readFileSync(key, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
    fileName: key,
  });
  const module = { exports: {} };
  moduleCache.set(key, module);

  const localRequire = (specifier) => {
    if (specifier.endsWith(".css")) return {};
    return specifier.startsWith(".")
      ? loadFile(resolveSource(path.dirname(key), specifier))
      : nativeRequire(specifier);
  };

  new Function("require", "module", "exports", outputText)(
    localRequire,
    module,
    module.exports,
  );
  return module.exports;
}

const { dataStudioAssetToHit } = loadTypeScriptCommonJs(
  "../src/create/skills/datastudio.ts",
);
const {
  dataStudioLoadStateFromResponse,
  isKnowledgeCenterMessageFromTrustedOrigin,
} = loadTypeScriptCommonJs("../src/knowledge-center/KnowledgeCenter.tsx");
const {
  dataStudioEmptyStateText,
  toggleDataStudioSelection,
} = loadTypeScriptCommonJs("../src/create/DataStudioAssetPicker.tsx");

test("knowledge center is reachable from the Studio shell with active sidebar semantics", () => {
  assert.match(sidebarSource, /export type SidebarPage[\s\S]*?"knowledge-center"/);
  assert.match(sidebarSource, /activePage: SidebarPage/);
  assert.match(sidebarSource, /aria-label="知识中心"/);
  assert.match(sidebarSource, /aria-current=\{activePage === "knowledge-center" \? "page" : undefined\}/);
  assert.match(sidebarSource, /is-active/);
  assert.match(skillCenterSource, /export function SkillCenterView/);
  assert.match(searchSource, /aria-current=\{active \? "page" : undefined\}/);
  assert.match(appSource, /KnowledgeCenterView/);
  assert.match(appSource, /const \[knowledgeCenter, setKnowledgeCenter\]/);
  assert.match(appSource, /sidebarActivePage[\s\S]*?"knowledge-center"/);
  assert.match(appSource, /activePage=\{sidebarActivePage\}/);
  assert.match(clientSource, /knowledgeCenter: boolean/);
  assert.match(serverSource, /"knowledgeCenter": True/);
});

test("knowledge center embeds Byaan through a locked Data Studio shell", () => {
  assert.match(knowledgeSource, /<iframe/);
  assert.match(knowledgeSource, /sandbox="allow-scripts allow-same-origin allow-forms"/);
  assert.match(knowledgeSource, /\/web\/datastudio\/config/);
  assert.match(knowledgeSource, /\/sources/);
  assert.match(knowledgeSource, /\/data-models/);
  assert.match(knowledgeSource, /\/dashboard/);
  assert.match(knowledgeSource, /\/evaluation/);
  assert.match(knowledgeSource, /eventOrigin !== trustedOrigin/);
  assert.match(knowledgeSource, /isKnowledgeCenterMessageFromTrustedOrigin\(/);
  assert.match(knowledgeSource, /KnowledgeCenterMessage/);
  assert.match(knowledgeSource, /veadk\.knowledge-center\.asset-published/);
  assert.match(knowledgeSource, /未配置连接/);
  assert.match(knowledgeSource, /未登录/);
  assert.match(knowledgeSource, /Byaan 不可达/);
  assert.doesNotMatch(knowledgeSource, /DB_GPT|dbgpt|DataSourceWorkbench|KnowledgeWorkbench/);
});

test("KnowledgeCenterView classifies configuration, auth, and reachability states", () => {
  assert.equal(
    dataStudioLoadStateFromResponse({ status: 409, ok: false })?.kind,
    "unconfigured",
  );
  assert.equal(
    dataStudioLoadStateFromResponse({ status: 401, ok: false })?.kind,
    "unauthenticated",
  );
  assert.equal(
    dataStudioLoadStateFromResponse({ status: 502, ok: false })?.kind,
    "unreachable",
  );
  assert.equal(dataStudioLoadStateFromResponse({ status: 200, ok: true }), null);
});

test("KnowledgeCenterView accepts only trusted postMessage payloads", () => {
  const trusted = "https://byaan.example";
  assert.equal(
    isKnowledgeCenterMessageFromTrustedOrigin("https://evil.example", trusted, {
      type: "veadk.knowledge-center.navigate",
      step: "dashboard",
    }),
    false,
  );
  assert.equal(
    isKnowledgeCenterMessageFromTrustedOrigin(trusted, trusted, {
      type: "veadk.knowledge-center.navigate",
      step: "unknown",
    }),
    false,
  );
  assert.equal(
    isKnowledgeCenterMessageFromTrustedOrigin(trusted, trusted, {
      type: "veadk.knowledge-center.asset-published",
      assetType: "dashboard",
      assetId: "sales",
    }),
    true,
  );
  assert.equal(
    isKnowledgeCenterMessageFromTrustedOrigin(trusted, trusted, {
      type: "veadk.knowledge-center.asset-published",
      assetType: "skill",
      assetId: "sales",
    }),
    false,
  );
});

test("Data Studio server gateway keeps credentials server-side and exposes the required routes", () => {
  assert.match(dataStudioRoutesSource, /\/web\/datastudio\/config/);
  assert.match(dataStudioRoutesSource, /\/web\/datastudio\/assets/);
  assert.match(dataStudioRoutesSource, /\/web\/datastudio\/assets\/\{asset_type\}\/\{asset_id\}/);
  assert.match(serverSource, /mount_datastudio_routes\(app\)/);
  assert.match(gatewaySource, /DATASTUDIO_BASE_URL/);
  assert.match(gatewaySource, /DATASTUDIO_API_KEY/);
  assert.match(gatewaySource, /\/api\/external\/assets/);
  assert.match(gatewaySource, /status_code=409/);
  assert.match(gatewaySource, /status_code=401/);
  assert.match(gatewaySource, /status_code=502/);
  assert.match(gatewaySource, /DATASTUDIO_MOCK/);
  assert.doesNotMatch(knowledgeSource, /DATASTUDIO_API_KEY/);
});

test("Data Studio asset adapter preserves the shared contract fields for picker cards", () => {
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
    mcp_url: "https://byaan.example/api/mcp/assets/dashboard/sales",
  });

  assert.equal(hit.source, "datastudio");
  assert.equal(hit.dataStudioAssetType, "dashboard");
  assert.equal(hit.dataStudioAssetId, "sales");
  assert.equal(hit.dataStudioGateScore, 91);
  assert.deepEqual(hit.dataStudioMetrics, ["GMV", "Orders"]);
  assert.deepEqual(hit.dataStudioExampleQuestions, ["GMV by channel?"]);
  assert.equal(hit.dataStudioPermissionHint, "Aggregated only");
  assert.equal(hit.dataStudioMcpUrl, "https://byaan.example/api/mcp/assets/dashboard/sales");
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
  assert.equal(
    dataStudioEmptyStateText({ error: null, query: "gmv" }),
    "搜索无结果，换个关键词试试。",
  );
  assert.equal(
    dataStudioEmptyStateText({ error: null, query: "" }),
    "暂无已发布资产。",
  );

  const existingLocalSkill = {
    source: "local",
    folder: "local-skill",
    name: "Local Skill",
    description: "",
    localFiles: [{ path: "skills/local-skill/SKILL.md", content: "---" }],
  };
  const hit = dataStudioAssetToHit({
    asset_type: "semantic_model",
    asset_id: "retention",
    name: "Retention Model",
    description: "Retention metrics",
    status: "published",
    publish_state: "published",
    gate: { score: 88 },
    version: "v2",
    consumers: ["agent"],
    capabilities: { metrics: ["DAU"] },
    freshness: {},
    provenance: {},
    usage_policy: {},
    sample_evidence: [],
    mcp_url: "https://byaan.example/api/mcp/assets/semantic_model/retention",
  });

  const selected = toggleDataStudioSelection([existingLocalSkill], hit);
  assert.equal(selected.length, 2);
  assert.equal(selected[0], existingLocalSkill);
  assert.equal(selected[1].source, "datastudio");
  assert.equal(selected[1].dataStudioAssetId, "retention");

  const removed = toggleDataStudioSelection(selected, hit);
  assert.deepEqual(removed, [existingLocalSkill]);
});

test("knowledge center uses bounded iframe layout styles", () => {
  assert.match(knowledgeStyles, /\.kc-root/);
  assert.match(knowledgeStyles, /overflow: hidden/);
  assert.match(knowledgeStyles, /\.kc-frame/);
  assert.match(knowledgeStyles, /\.kc-step-nav/);
  assert.doesNotMatch(knowledgeStyles, /kc-gpt-card|kc-drawer|kc-modal|linear-gradient\(to right, #00daef, #105eff\)/);
});
