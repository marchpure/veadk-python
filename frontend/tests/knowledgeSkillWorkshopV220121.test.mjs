import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const feature = path.join(root, "src/features/knowledge-workspace");
const page = await readFile(path.join(feature, "pages/KnowledgeWorkspacePage.tsx"), "utf8");
const css = await readFile(path.join(feature, "pages/knowledge-workspace.css"), "utf8");
const creator = await readFile(path.join(feature, "creator/SkillCreateLanding.tsx"), "utf8");
const composer = await readFile(path.join(feature, "creator/SkillComposer.tsx"), "utf8");
const drawer = await readFile(path.join(feature, "creator/DataToolDrawer.tsx"), "utf8");
const workspace = await readFile(path.join(feature, "workspace/SkillWorkspaceShell.tsx"), "utf8");
const conversation = await readFile(path.join(feature, "workspace/SkillConversation.tsx"), "utf8");
const artifacts = await readFile(path.join(feature, "workspace/ArtifactWorkspace.tsx"), "utf8");
const toolbar = await readFile(path.join(feature, "workspace/ArtifactToolbar.tsx"), "utf8");

test("new Skill starts with one business composer and Auto delivery", () => {
  assert.match(creator, /创建一个新技能/);
  assert.match(composer, /Auto（自动推荐）/);
  assert.match(creator, /分析华东区域异常/);
  assert.match(creator, /生成蓝牙诊断 SOP/);
  assert.match(creator, /制作门店巡检看板/);
  assert.doesNotMatch(creator, /1\.\s*选择模板|2\.\s*谁会使用|3\.\s*接入|4\.\s*先试/);
  assert.match(creator, /setGoal\(suggestion\)/);
  assert.match(creator, /if \(!selectedConnectionIds\.length && !selectedResourceIds\.length\)/);
});

test("data drawer selects only real usable contexts and preserves status semantics", () => {
  assert.match(page, /knowledgeApi\.listConnections/);
  assert.match(page, /knowledgeApi\.listResources/);
  assert.match(page, /connections=\{connections\}/);
  assert.match(drawer, /connection\.status === "ready"/);
  assert.match(drawer, /已撤销/);
  assert.match(drawer, /onInspectResource/);
  assert.match(drawer, /去配置/);
  assert.match(drawer, />查看</);
  assert.match(drawer, /数据库/);
  assert.match(drawer, /文件与表格/);
  assert.match(drawer, /对象存储/);
  assert.match(drawer, /API \/ MCP/);
  assert.match(drawer, /办公与知识/);
  assert.doesNotMatch(drawer, /verified.*ready|resourceStore|Zustand/i);
});

test("inspecting unavailable context returns to the in-progress creator", () => {
  assert.match(page, /contextReturnRouteRef/);
  assert.match(page, /contextReturnRouteRef\.current = route\.file/);
  assert.match(page, /returnFromContextDetail/);
  assert.match(page, /onBack=\{contextReturnRouteRef\.current \? returnFromContextDetail : undefined\}/);
  assert.match(page, /onInspectResource=/);
  assert.match(page, /disabled=\{resource\.status !== "verified"\}/);
});

test("first message maps to one real draft and generation invocation", () => {
  assert.match(page, /template_key: templateKey/);
  assert.match(page, /template_config: templateConfig/);
  assert.match(page, /knowledgeApi\.createDraft/);
  assert.match(page, /knowledgeApi\.generateDraft/);
  assert.match(page, /setRoute\("draft", created\.value\.data\.draft_id\)/);
  assert.match(page, /goal,\s*template_key/s);
  assert.match(page, /pendingCreatedDraftRef\.current[\s\S]*?knowledgeApi\.updateDraft/s);
});

test("draft workspace is conversation-led with invocation rail and artifact pane", () => {
  assert.match(workspace, /InvocationRail/);
  assert.match(workspace, /SkillConversation/);
  assert.match(workspace, /ArtifactWorkspace/);
  assert.match(conversation, /intent="update"/);
  assert.match(conversation, /试跑\s*\/\s*刷新/);
  assert.match(workspace, /onUpdateContext/);
  assert.match(page, /knowledgeApi\.updateDraft/);
  assert.doesNotMatch(workspace, /SkillPackagePanel/);
  assert.match(css, /grid-template-columns:\s*240px minmax\(420px,\s*min\(760px,\s*42vw\)\) minmax\(0,\s*1fr\)/);
});

test("artifacts are restored from conversation events and remain controlled", () => {
  assert.match(page, /artifact\.created/);
  assert.match(page, /knowledgeApi\.getArtifact/);
  assert.match(artifacts, /ArtifactViewer/);
  assert.match(artifacts, /url\.origin !== window\.location\.origin/);
  assert.match(artifacts, /等待产物生成/);
  assert.match(toolbar, /发布 Skill/);
  assert.match(toolbar, /添加到 Agent/);
  assert.doesNotMatch(artifacts, /dangerouslySetInnerHTML|固定销售|mock/i);
});

test("publication state is restored from the existing BFF listing endpoint", () => {
  assert.match(page, /knowledgeApi\.listPublications/);
  assert.match(page, /currentRevisionId/);
  assert.match(page, /publication\.revision_id === currentRevisionId/);
  assert.match(page, /setPublication\(restoredPublication \|\| null\)/);
});

test("responsive workshop uses full-screen mobile drawers without horizontal overflow", () => {
  assert.match(css, /@media \(max-width: 720px\)/);
  assert.match(css, /\.kw-workshop-mobile-drawer/);
  assert.match(css, /overflow-x:\s*hidden/);
  assert.match(css, /\.kw-data-tool-drawer[^}]*width:\s*min\(480px,\s*100vw\)/s);
});

test("production workshop contains no simulated success state", () => {
  for (const source of [page, creator, composer, drawer, workspace, conversation, artifacts, toolbar]) {
    assert.doesNotMatch(source, /localStorage|useAgentSimulation|mock-skill|setTimeout\s*\(/i);
  }
});
