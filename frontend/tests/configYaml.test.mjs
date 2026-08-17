import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

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
  const cached = moduleCache.get(key);
  if (cached) return cached.exports;

  const source = readFileSync(key, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
    fileName: key,
  });
  const module = { exports: {} };
  moduleCache.set(key, module);

  const localRequire = (specifier) =>
    specifier.startsWith(".")
      ? loadFile(resolveSource(path.dirname(key), specifier))
      : nativeRequire(specifier);

  new Function("require", "module", "exports", outputText)(
    localRequire,
    module,
    module.exports,
  );
  return module.exports;
}

const { draftToYaml, yamlToDraft } = loadTypeScriptCommonJs(
  "../src/create/configYaml.ts",
);
const { codegenDraft } = loadTypeScriptCommonJs("../src/create/codegenDraft.ts");
const { emptyDraft } = loadTypeScriptCommonJs("../src/create/types.ts");

function draft(overrides = {}) {
  return {
    ...emptyDraft(),
    ...overrides,
    memory: {
      ...emptyDraft().memory,
      ...(overrides.memory ?? {}),
    },
    subAgents: overrides.subAgents ?? [],
  };
}

test("Data Studio assets round-trip through YAML and become runtime MCP tools", () => {
  const source = draft({
    name: "datastudio_agent",
    description: "Uses governed BI assets",
    instruction: "Answer with evidence.",
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
        dataStudioMetrics: ["GMV", "Orders"],
        dataStudioExampleQuestions: ["What is GMV by channel?"],
        dataStudioPermissionHint: "Aggregated metrics only",
        dataStudioMcpUrl: "https://byaan.example/api/mcp/assets/dashboard/sales-dashboard",
        dataStudioTimeField: "pay_date",
        dataStudioDimensions: ["channel", "region"],
        dataStudioEvidence: ["sql: select sum(gmv)"],
      },
    ],
  });

  const yaml = draftToYaml(source);
  assert.match(yaml, /dataAssets:/);
  assert.match(yaml, /dataStudioAssetType: dashboard/);
  assert.match(yaml, /dataStudioAssetId: sales-dashboard/);
  assert.doesNotMatch(yaml, /BYAAN_MCP_API_KEY/);

  const restored = yamlToDraft(yaml);
  assert.deepEqual(restored.dataAssets, source.dataAssets);

  const codegen = codegenDraft(restored);
  assert.deepEqual(codegen.dataAssets, source.dataAssets);
  assert.deepEqual(codegen.mcpTools, [
    {
      name: "byaan-datastudio-dashboard-sales",
      transport: "http",
      url: "https://byaan.example/api/mcp/assets/dashboard/sales-dashboard",
      authTokenEnv: "BYAAN_MCP_API_KEY",
      command: "",
      args: [],
    },
  ]);
});
