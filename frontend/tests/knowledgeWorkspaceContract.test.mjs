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
