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
  assert.match(client, /Idempotency-Key/);
  assert.match(client, /If-Match/);
  assert.match(client, /Last-Event-ID/);
});

test("production feature does not carry prototype business state or outcomes", () => {
  for (const source of [page, client, artifact]) {
    assert.doesNotMatch(source, /mockData|localStorage|setTimeout|安踏|智己|海底捞|haidilao/i);
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
