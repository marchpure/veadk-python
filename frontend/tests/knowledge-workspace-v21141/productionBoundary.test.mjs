import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const root = join(import.meta.dirname, "../../src/knowledge-workspace");

test("production boundary declares typed HTTP/SSE ports and no optimistic success", () => {
  const ports = readFileSync(join(root, "production/ports.ts"), "utf8");
  assert.match(ports, /export interface WorkspaceAdapter/);
  assert.match(ports, /"Idempotency-Key"/);
  assert.match(ports, /"X-Request-ID"/);
  assert.match(ports, /"Last-Event-ID"/);
  assert.match(ports, /allowOptimisticUpdates = false/);
  assert.match(ports, /KnowledgeErrorCode/);
});

test("frozen imports are redirected to production ports by the bundler", () => {
  const vite = readFileSync(join(root, "../../vite.config.ts"), "utf8");
  assert.match(vite, /knowledgeWorkspaceProductionBoundary/);
  assert.match(vite, /lib\/store\.ts/);
  assert.match(vite, /lib\/actionLoopStore\.ts/);
  assert.match(vite, /data\/mockData\.ts/);
  assert.match(vite, /localStorage/g);
});

test("adapter changes preserve all 47 frozen provenance rows", () => {
  const changes = JSON.parse(
    readFileSync(join(root, "production/adapterChanges.json"), "utf8"),
  );
  assert.equal(changes.frozen_source_count, 47);
  assert.equal(
    changes.frozen_source_tree_sha256,
    "57e97670c6091219dcf1ac35d76dd174a45c9fa69841ce5b7887caef39b27c83",
  );
  assert.ok(changes.changes.length >= 3);
});

test("deterministic adapter is test-only and emits a terminal ordered event", async () => {
  const { createDeterministicContractAdapter } = await import(
    "./deterministicContractAdapter.mjs"
  );
  const adapter = createDeterministicContractAdapter();
  const bootstrap = await adapter.bootstrap();
  assert.equal(bootstrap.resources.length, 1);
  const context = { requestId: "r-1", idempotencyKey: "i-1" };
  const result = await adapter.command("resource.update", {}, context);
  assert.equal(result.accepted, true);
  const stream = await adapter.stream("assistant.turn", {}, context);
  const events = [];
  for await (const event of stream.events()) events.push(event);
  assert.equal(events.length, 1);
  assert.equal(events[0].sequence, 1);
  assert.equal(events[0].terminal, true);
});
