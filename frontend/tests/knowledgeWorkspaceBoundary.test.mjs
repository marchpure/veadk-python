import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const featureRoot = path.join(root, "src/features/knowledge-workspace");
const page = await readFile(path.join(featureRoot, "pages/KnowledgeWorkspacePage.tsx"), "utf8");
const client = await readFile(path.join(featureRoot, "api/client.ts"), "utf8");
const artifact = await readFile(path.join(featureRoot, "artifact/ArtifactViewer.tsx"), "utf8");
const captures = await readFile(path.join(featureRoot, "test-fixtures/captures.ts"), "utf8");

test("production feature is bound to the same-origin knowledge BFF", () => {
  assert.match(client, /const API_ROOT = "\/api\/knowledge\/v1"/);
  assert.doesNotMatch(client, /autoskill|openconnector|fixture/i);
  assert.doesNotMatch(page, /<iframe/);
  assert.match(client, /Idempotency-Key/);
  assert.match(client, /If-Match/);
  assert.match(client, /Last-Event-ID/);
  assert.match(client, /withLocalUser\(headers\)/);
  assert.match(client, /withLocalUser\(\)/);
  assert.match(client, /getConnection/);
  assert.match(client, /updateDraft/);
  assert.match(client, /freezeRevision/);
  assert.match(client, /invokePublication/);
});

test("production feature does not carry prototype business state or outcomes", () => {
  for (const source of [page, client, artifact]) {
    assert.doesNotMatch(source, /mockData|localStorage|setTimeout|安踏|智己|海底捞|haidilao/i);
    assert.doesNotMatch(source, /经营分析助手|售后诊断助手|门店运营助手|Oracle ERP 销售数据集|区域经理使用/);
  }
  assert.match(page, /knowledgeApi\.listConnections/);
  assert.match(page, /knowledgeApi\.createDraft/);
  assert.match(page, /knowledgeApi\.generateDraft/);
  assert.match(page, /knowledgeApi\.publishRevision/);
});

test("all prototype captures have explicit route/state fixture entries", () => {
  const entries = [...captures.matchAll(/stateUrl: "([^"]+)"/g)].map((match) => match[1]);
  assert.equal(entries.length, 22);
  assert.equal(new Set(entries).size, 22);
  assert.match(captures, /modal: "publish"/);
  assert.match(captures, /runState: "failed"/);
  assert.match(captures, /state: "permission"/);
});

test("artifact viewer is isolated and digest-visible", () => {
  assert.match(artifact, /sandbox="allow-scripts"/);
  assert.match(artifact, /referrerPolicy="no-referrer"/);
  assert.match(artifact, /artifact\.sha256/);
  assert.match(artifact, /startsWith\("\/api\/knowledge\/v1\/artifacts\/"\)/);
  assert.doesNotMatch(artifact, /allow-same-origin/);
});

test("route states and server errors remain actionable without client outcomes", () => {
  for (const code of [
    "WORKSPACE_NOT_FOUND",
    "LEASE_EXPIRED",
    "SKILL_ZIP_INVALID",
    "ARTIFACT_UNSAFE",
    "IDEMPOTENCY_CONFLICT",
    "PRECONDITION_FAILED",
  ]) {
    assert.match(page, new RegExp(code));
  }
  assert.match(page, /terminalInvocationRef/);
  assert.match(page, /CreationRail/);
  assert.match(page, /config_schema\.required/);
  assert.doesNotMatch(page, /route\.runState|route\.state/);
  assert.match(page, /knowledgeApi\.validateConnection\(created\.data\.connection_id\)/);
  assert.match(page, /connectionId/);
});
