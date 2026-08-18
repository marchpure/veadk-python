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

test("native workbench uses first-level tabs and type-card source flow", () => {
  for (const label of ["概览", "数据源", "能力", "构建任务", "设置"]) {
    assert.match(workbenchSource, new RegExp(`label: "${label}"`));
  }
  assert.match(workbenchSource, /SourceFlow/);
  assert.match(workbenchSource, /sourceTypeGroups/);
  assert.match(workbenchSource, /Schema Snapshot/);
  assert.match(workbenchSource, /飞书 OAuth/);
  assert.match(workbenchSource, /type="file"/);
  assert.match(workbenchSource, /readSourceFile/);
  assert.match(workbenchSource, /metadata JSON/);
  assert.match(workbenchSource, /Metadata JSON 无效/);
  assert.match(workbenchSource, /客户端预检查检测到疑似浏览器凭据/);
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
  assert.match(workbenchSource, /listKnowledgeAssetBuildJobs\(spaceId \|\| undefined\)/);
  assert.match(workbenchSource, /latestJobForSource\(jobs, source\.id\)/);
  assert.match(workbenchSource, /kc-source-job-history/);
  assert.match(workbenchSource, /jobs\.filter\(\(job\) => job\.source_id === source\.id\)/);
  assert.doesNotMatch(workbenchSource, /\/api\/knowledge-assets\/build\/semantic-skill/);
  assert.doesNotMatch(workbenchSource, /buildKnowledgeAssetSemanticSkill/);
});

test("overview next actions route to real capability panels", () => {
  assert.match(workbenchSource, /生成语义 Skill/);
  assert.match(workbenchSource, /新建 Dashboard Skill/);
  assert.match(workbenchSource, /打开 AskData/);
  assert.match(workbenchSource, /function openWorkbenchTarget/);
  assert.match(workbenchSource, /pendingCapabilityFocusRef/);
  assert.match(workbenchSource, /onOpenCapability=\{\(target\) => openWorkbenchTarget\("capabilities", target\)\}/);
  assert.match(workbenchSource, /<button type="button" className="kc-next-action" onClick=\{onClick\}>/);
  assert.match(workbenchSource, /data-capability-target="semantic_skill"/);
  assert.match(workbenchSource, /data-capability-target="dashboard_skill"/);
  assert.match(workbenchSource, /data-capability-target="askdata"/);
  assert.doesNotMatch(workbenchSource, /function NextAction[\s\S]*?<article className="kc-next-action"/);
  assert.doesNotMatch(workbenchSource, /等待构建器接入|Builder 将挂载|AskData 入口已预留/);
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
});
