import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const page = await readFile(path.join(root, "src/features/knowledge-workspace/pages/KnowledgeWorkspacePage.tsx"), "utf8");
const client = await readFile(path.join(root, "src/features/knowledge-workspace/api/client.ts"), "utf8");
const types = await readFile(path.join(root, "src/features/knowledge-workspace/domain/types.ts"), "utf8");

test("client covers the browser-facing REST resource groups", () => {
  for (const route of [
    "/connector-definitions",
    "/connections",
    "/connections/",
    "PATCH",
    "/skills/drafts",
    "/generate",
    "/messages",
    "/invocations/",
    "/revisions",
    "freezeRevision",
    "/artifacts/",
    "/publish",
    "/publications/",
  ]) {
    assert.match(client, new RegExp(route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("specialized adapters use real capability routes and durable resources", () => {
  assert.match(client, /discoverOracleAdapter/);
  assert.match(client, /\/adapters\/oracle\/discover/);
  assert.match(client, /saveRestResource/);
  assert.match(client, /saveOracleResource/);
  assert.match(client, /saveMcpResource/);
  assert.match(client, /callMcpAdapter/);
  assert.match(client, /\/adapters\/mcp\/call/);
  assert.match(client, /previewAdapterFile/);
  assert.match(page, /knowledgeApi\.validateOracleAdapter/);
  assert.match(page, /knowledgeApi\.discoverOracleAdapter/);
  assert.match(page, /schemaDiscovery/);
  assert.match(page, /tableDiscovery/);
  assert.match(page, /selectedSchema/);
  assert.match(page, /schemas|tables/);
  assert.match(page, /oracle-resource-discovery/);
  assert.match(page, /真实 Oracle Schema \/ Table discovery/);
  assert.match(page, /knowledgeApi\.listResources/);
  assert.match(page, /WorkspaceResourceDetail/);
  assert.match(page, /加入 Skill 上下文/);
  assert.match(page, /真实文件预览/);
  assert.match(page, /真实调用/);
  assert.match(page, /setShowConnectionForm\(false\)/);
  assert.match(page, /metadata\?\.upload_id === fileResult\.upload_id/);
  assert.doesNotMatch(page, /resource_id:\s*`upload:/);
});

test("connection chooser is card-based and OAuth/MCP states are explicit", () => {
  assert.match(page, /kw-connector-cards/);
  assert.match(page, /kw-connector-card/);
  assert.doesNotMatch(page, /<select[^>]+value=\{connectorKey\}/);
  assert.match(page, /connectorCredentialLabel/);
  assert.match(page, /需要配置 OAuth 应用并发起授权/);
  assert.match(page, /我确认这是本地开发 MCP/);
  assert.match(page, /允许的本地端口/);
});

test("connection jobs are polled to a terminal state with timeout and retry support", () => {
  assert.match(client, /getConnectionJob/);
  assert.match(client, /waitForConnectionJob/);
  assert.match(client, /\/connection-jobs\//);
  assert.match(client, /CONNECTION_JOB_TIMEOUT/);
  assert.match(client, /retryable/);
  assert.match(page, /waitForConnectionJob/);
  assert.match(page, /重试/);
});

test("workspace exposes upload, retry, team directory, published return, and failure-state behavior", () => {
  assert.match(page, /uploadSkillInput/);
  assert.match(page, /upload_ids/);
  assert.match(page, /重试本次运行/);
  assert.match(page, /团队工作区/);
  assert.match(page, /file === "published"/);
  assert.match(page, /返回工作台/);
  assert.match(page, /run\.failed/);
});

test("normalized event union contains every STEP 1 event type", () => {
  for (const eventType of [
    "run.started",
    "assistant.delta",
    "plan.updated",
    "tool.started",
    "tool.completed",
    "artifact.created",
    "revision.created",
    "run.completed",
    "run.failed",
    "run.cancelled",
  ]) {
    assert.match(types, new RegExp(`"${eventType.replace(".", "\\.")}"`));
  }
  assert.match(client, /onUnknown/);
  assert.match(client, /normalizeEvent/);
  assert.match(client, /lastEventId/);
});
