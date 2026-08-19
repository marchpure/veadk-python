import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const require = createRequire(import.meta.url);
const workbenchSource = readFileSync(
  new URL("../src/knowledge-center/KnowledgeCenter.tsx", import.meta.url),
  "utf8",
);
const workbenchStyles = readFileSync(
  new URL("../src/knowledge-center/KnowledgeCenter.css", import.meta.url),
  "utf8",
);
const clientSource = readFileSync(
  new URL("../src/adk/knowledgeAssets.ts", import.meta.url),
  "utf8",
);
const slotSource = readFileSync(
  new URL("../src/knowledge-center/capabilitySlots.ts", import.meta.url),
  "utf8",
);
const evaluationSource = readFileSync(
  new URL("../src/knowledge-center/EvaluationWorkbench.tsx", import.meta.url),
  "utf8",
);
const evaluationSuiteListSource = readFileSync(
  new URL("../src/knowledge-center/EvaluationSuiteList.tsx", import.meta.url),
  "utf8",
);
const evaluationCaseTableSource = readFileSync(
  new URL("../src/knowledge-center/EvaluationCaseTable.tsx", import.meta.url),
  "utf8",
);
const evaluationRunDetailSource = readFileSync(
  new URL("../src/knowledge-center/EvaluationRunDetail.tsx", import.meta.url),
  "utf8",
);
const evaluationOptimizationSource = readFileSync(
  new URL("../src/knowledge-center/EvaluationOptimizationPanel.tsx", import.meta.url),
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
  const outFile = join(outDir, `knowledge-asset-${id}.cjs`);
  await writeFile(outFile, result.outputFiles[0].contents);
  delete require.cache[outFile];
  return require(outFile);
}

test("native workbench uses first-level tabs and manifest-driven connector wizard", () => {
  for (const label of ["概览", "数据源", "语义构建", "AskTable / Dashboard", "测评", "能力", "构建任务", "设置"]) {
    assert.match(workbenchSource, new RegExp(`label: "${label}"`));
  }
  assert.match(workbenchSource, /AddContentWizard/);
  assert.match(workbenchSource, /Connector Gallery/);
  assert.match(workbenchSource, /galleryFilters/);
  for (const filter of ["全部", "资料", "业务数据", "个人上下文", "需要授权", "本地", "预览中"]) {
    assert.match(workbenchSource, new RegExp(`"${filter}"`));
  }
  assert.match(workbenchSource, /搜索内容、provider 或能力/);
  assert.match(workbenchSource, /connectorProviderName/);
  assert.match(workbenchSource, /connectorRequiredPermissionLabel/);
  assert.match(workbenchSource, /connectorCopyLabel/);
  assert.match(workbenchSource, /connectorPrimaryActionLabel/);
  assert.match(workbenchSource, /了解要求/);
  assert.match(workbenchSource, /申请启用/);
  assert.match(workbenchSource, /listKnowledgeConnectorDefinitions/);
  assert.match(workbenchSource, /listKnowledgeSourceResources/);
  assert.match(workbenchSource, /enabledConnectorStates/);
  assert.doesNotMatch(workbenchSource, /"preview",\s*\]\);/);
  assert.match(workbenchSource, /"content" \| "auth" \| "scope" \| "governance" \| "publish"/);
  assert.match(workbenchSource, /选择内容/);
  assert.match(workbenchSource, /连接与授权/);
  assert.match(workbenchSource, /选择范围/);
  assert.match(workbenchSource, /预览与治理/);
  assert.match(workbenchSource, /同步并发布能力/);
  assert.match(workbenchSource, /Schema Snapshot/);
  assert.match(workbenchSource, /需要 OAuth/);
  assert.match(workbenchSource, /type="file"/);
  assert.match(workbenchSource, /readSourceFile/);
  assert.match(workbenchSource, /metadata JSON/);
  assert.match(workbenchSource, /Metadata JSON 无效/);
  assert.match(workbenchSource, /空范围不会触发全量采集/);
  assert.match(workbenchSource, /高级连接选项/);
  assert.match(workbenchSource, /这些设置通常不需要修改/);
  assert.match(workbenchSource, /客户端预检查检测到疑似浏览器凭据/);
  assert.match(clientSource, /\/api\/knowledge-assets\/connectors/);
  assert.match(clientSource, /\/api\/knowledge-assets\/source-resources/);
  assert.match(clientSource, /provider_name\?: string/);
  assert.match(clientSource, /copies_data\?: boolean/);
  assert.doesNotMatch(workbenchSource, /sourceTypeGroups/);
  assert.doesNotMatch(workbenchSource, /<select\b|<option\b/);
});

test("native workbench keeps implementation details out of the main product view", () => {
  const settingsIndex = workbenchSource.indexOf("SettingsTab");
  const sqliteIndex = workbenchSource.indexOf("SQLite Asset Store");
  assert.ok(sqliteIndex > settingsIndex, "SQLite detail belongs under SettingsTab");
  assert.doesNotMatch(workbenchSource, /高级调试入口/);
  assert.doesNotMatch(workbenchSource, /<iframe/);
  assert.doesNotMatch(workbenchSource, /DATASTUDIO_BASE_URL|DATASTUDIO_API_KEY/);
  assert.doesNotMatch(workbenchSource, /<dt>Asset ID<\/dt>/);
});

test("workbench failures are styled Chinese states with diagnostics", () => {
  assert.match(workbenchSource, /function asWorkbenchError/);
  assert.match(workbenchSource, /知识资产工作台暂不可用/);
  assert.match(workbenchSource, /数据源导入失败/);
  assert.match(workbenchSource, /表单数据已保留，请按诊断信息修正后重试。/);
  assert.match(workbenchSource, /className=\{`kc-error-panel/);
  assert.doesNotMatch(workbenchSource, /"Failed to fetch"/);
});

test("workbench uses import orchestration and source-level build jobs", () => {
  assert.match(clientSource, /\/api\/knowledge-assets\/sources\/import/);
  assert.match(workbenchSource, /importKnowledgeAssetSource/);
  assert.match(workbenchSource, /ConnectedContentRow/);
  assert.match(workbenchSource, /Connected Content/);
  assert.match(workbenchSource, /ConnectedContentDrawer/);
  for (const column of ["内容", "类型", "资源数", "状态", "最近同步", "Freshness", "权限", "下一步"]) {
    assert.match(workbenchSource, new RegExp(`>${column}<`));
  }
  assert.match(workbenchSource, /primaryRowActionLabel/);
  assert.match(workbenchSource, /重新授权/);
  assert.match(workbenchSource, /查看进度/);
  assert.match(workbenchSource, /查看失败资源/);
  assert.match(workbenchSource, /重新同步/);
  assert.match(workbenchSource, /查看原因 \/ 重试/);
  assert.match(workbenchSource, /重新授权或保留快照/);
  assert.match(workbenchSource, /Resource Picker/);
  for (const tab of ["概览", "资源", "同步记录", "访问权限", "Lineage", "诊断详情 Advanced"]) {
    assert.match(workbenchSource, new RegExp(`${tab}`));
  }
  assert.match(workbenchSource, /kc-resource-tabs/);
  assert.match(workbenchSource, /kc-lineage-chain/);
  assert.match(workbenchSource, /listKnowledgeAssetBuildJobs\(spaceId \|\| undefined\)/);
  assert.match(workbenchSource, /latestJobForSource\(jobs, resource\.source_id\)/);
  assert.match(workbenchSource, /kc-connected-content-table/);
  assert.match(workbenchSource, /fallback_filter_behavior/);
  assert.match(workbenchSource, /resource_ids: resourceIds/);
  assert.match(workbenchSource, /post_filter_and_report_partial_evidence/);
  assert.doesNotMatch(workbenchSource, /\/api\/knowledge-assets\/build\/semantic-skill/);
  assert.doesNotMatch(workbenchSource, /buildKnowledgeAssetSemanticSkill/);
});

test("overview next actions route to real first-level workbench tabs", () => {
  assert.match(workbenchSource, /生成语义 Skill/);
  assert.match(workbenchSource, /新建 Dashboard Skill/);
  assert.match(workbenchSource, /打开 AskData/);
  assert.match(workbenchSource, /运行测评/);
  assert.match(workbenchSource, /function openWorkbenchTarget/);
  assert.match(workbenchSource, /pendingCapabilityFocusRef/);
  assert.match(workbenchSource, /openWorkbenchTarget\("semantic", target\)/);
  assert.match(workbenchSource, /openWorkbenchTarget\("askdashboard", target\)/);
  assert.match(workbenchSource, /onOpenEvaluation=\{\(\) => openWorkbenchTarget\("evaluation"\)\}/);
  assert.match(workbenchSource, /<button type="button" className="kc-next-action" onClick=\{onClick\}>/);
  assert.match(workbenchSource, /data-workbench-target="semantic_skill"/);
  assert.match(workbenchSource, /data-workbench-target="askdata"/);
  assert.match(workbenchSource, /data-capability-target="semantic_skill"/);
  assert.match(workbenchSource, /data-capability-target="dashboard_skill"/);
  assert.doesNotMatch(workbenchSource, /function NextAction[\s\S]*?<article className="kc-next-action"/);
  assert.doesNotMatch(workbenchSource, /等待构建器接入|Builder 将挂载|AskData 入口已预留/);
});

test("capability tab only renders selectable capability lists", () => {
  const capabilitySection = workbenchSource.slice(
    workbenchSource.indexOf("function CapabilitiesTab"),
    workbenchSource.indexOf("function CapabilitySelectorList"),
  );
  assert.match(capabilitySection, /CapabilitySelectorList/);
  assert.match(capabilitySection, /Retrieval Binding/);
  assert.match(capabilitySection, /AskTable 语义能力/);
  assert.doesNotMatch(capabilitySection, /<SemanticBuildPanel|<DashboardBuildPanel|<AskDataPanel/);
});

test("evaluation tab uses native suite table detail optimization components", () => {
  assert.match(workbenchSource, /<EvaluationWorkbench/);
  assert.match(clientSource, /\/api\/knowledge-assets\/evaluation\/suites/);
  assert.match(clientSource, /\/api\/knowledge-assets\/evaluation\/runs/);
  assert.match(clientSource, /\/api\/knowledge-assets\/evaluation\/optimizations/);
  assert.match(clientSource, /importKnowledgeAssetEvalCases/);
  assert.match(clientSource, /\/api\/knowledge-assets\/evaluation\/suites\/\$\{encodeURIComponent\(suiteId\)\}\/cases\/import/);
  assert.match(evaluationSource, /Run Evaluation/);
  assert.match(evaluationSource, /Create Suite/);
  assert.match(evaluationSource, /Import Cases/);
  assert.match(evaluationSource, /Add Default Case/);
  assert.match(evaluationSource, /type="file"/);
  assert.match(evaluationSource, /accept="application\/json,\.json"/);
  assert.match(evaluationSource, /importCasesFile/);
  assert.match(evaluationSource, /importedCasesFromJson/);
  assert.match(evaluationSource, /setCreateTargetKind/);
  assert.match(evaluationSource, /createSuite\(createTargetKind\)/);
  assert.match(evaluationSource, /asktable_query/);
  assert.match(evaluationSource, /Export result\.json/);
  assert.match(evaluationSource, /Judge model not_configured/);
  assert.match(evaluationSource, /没有 Semantic Skill，请先去语义构建/);
  assert.match(evaluationSource, /没有 Dashboard Skill，dashboard 测评暂不可运行/);
  assert.match(evaluationSuiteListSource, /Semantic Skill/);
  assert.match(evaluationSuiteListSource, /AskTable Query/);
  assert.match(evaluationSuiteListSource, /Dashboard Skill/);
  assert.match(evaluationSuiteListSource, /value="asktable_query"/);
  assert.match(evaluationCaseTableSource, /expectedSqlContains/);
  assert.match(evaluationCaseTableSource, /scoreMin/);
  assert.match(evaluationCaseTableSource, /targetKindFilter/);
  assert.match(evaluationCaseTableSource, /全部对象/);
  assert.match(evaluationCaseTableSource, /value="asktable_query"/);
  assert.match(evaluationRunDetailSource, /policyDecision/);
  assert.match(evaluationRunDetailSource, /dashboardSpecDiff/);
  assert.match(evaluationOptimizationSource, /不会自动修改 MDL 或 dashboard_spec/);
  assert.doesNotMatch(evaluationSource, /<iframe|BYAAN/);
});

test("capability slot contract supports E2 and F panel mounting", async () => {
  assert.match(slotSource, /KnowledgeCapabilityCardProps/);
  assert.match(slotSource, /CapabilityBuildJobView/);
  assert.match(slotSource, /semantic_skill"\s*\|\s*"dashboard_skill"\s*\|\s*"askdata"/);
  assert.match(slotSource, /on_request_build/);

  const slots = await loadTypeScriptModule("../src/knowledge-center/capabilitySlots.ts");
  const rendered = slots.CapabilityPanelSlot({
    kind: "semantic_skill",
    capabilities: [{ id: "cap-1", name: "销售语义", kind: "semantic_skill", status: "ready", source_ids: [] }],
    build_jobs: [{ id: "job-1", status: "succeeded", job_type: "semantic_skill" }],
    render: (context) => ({
      mounted: true,
      kind: context.kind,
      capabilityCount: context.capabilities.length,
      jobCount: context.build_jobs.length,
    }),
  });
  assert.equal(rendered.props.children.mounted, true);
  assert.equal(rendered.props.children.kind, "semantic_skill");
  assert.equal(rendered.props.children.capabilityCount, 1);
  assert.equal(rendered.props.children.jobCount, 1);
});

test("mobile layout constrains the workbench to one main scroll area", () => {
  assert.match(workbenchStyles, /@media \(max-width: 820px\)/);
  assert.match(workbenchStyles, /\.kc-native-page\s*\{[\s\S]*?overflow:\s*hidden;/);
  assert.match(workbenchStyles, /\.kc-native-main\s*\{[\s\S]*?overflow:\s*hidden;/);
  assert.match(workbenchStyles, /\.kc-native-view\s*\{[\s\S]*?overflow-y:\s*auto;/);
  assert.match(workbenchStyles, /width:\s*100vw;/);
  assert.match(workbenchStyles, /grid-template-columns:\s*1fr;/);
  assert.match(workbenchStyles, /\.kc-wizard-footer\s*\{[\s\S]*?position:\s*sticky;/);
  assert.match(workbenchStyles, /\.kc-connected-content-head\s*\{[\s\S]*?display:\s*none;/);
  assert.match(workbenchStyles, /\.kc-connected-content-row\s*\{[\s\S]*?grid-template-columns:\s*1fr;/);
  assert.doesNotMatch(workbenchStyles, /kc-connected-content-row\s*\{[\s\S]*?min-width:\s*820px;/);
  assert.match(workbenchStyles, /\.kc-eval-grid[\s\S]*?grid-template-columns:\s*1fr;/);
  assert.match(workbenchStyles, /\.kc-eval-table-scroll[\s\S]*?max-width:\s*calc\(100vw - 44px\);/);
});
