import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import ts from "typescript";

const root = join(import.meta.dirname, "../../src/knowledge-workspace");
const frozenRoot = join(root, "frozen-ui");
const productionRoot = join(root, "production");

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(?:tsx?|jsx?)$/.test(path) ? [path] : [];
  });
}

test("production boundary declares typed HTTP/SSE ports and no optimistic success", () => {
  const ports = readFileSync(join(root, "production/ports.ts"), "utf8");
  assert.match(ports, /export interface WorkspaceAdapter/);
  assert.match(ports, /"Idempotency-Key"/);
  assert.match(ports, /"X-Request-ID"/);
  assert.match(ports, /"Last-Event-ID"/);
  assert.match(ports, /text\/event-stream/);
  assert.match(ports, /allowOptimisticUpdates = false/);
  assert.match(ports, /KnowledgeErrorCode/);
});

test("frozen imports are redirected to production ports by the bundler", () => {
  const vite = readFileSync(join(root, "../../vite.config.ts"), "utf8");
  assert.match(vite, /knowledgeWorkspaceProductionBoundary/);
  assert.doesNotMatch(vite, /frontend\/tests/);
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

test("all 47 frozen provenance targets are tracked in the checkout", () => {
  const manifest = JSON.parse(
    readFileSync(
      join(
        import.meta.dirname,
        "../../../tests/fixtures/knowledge_workspace_v21141/source-files.json",
      ),
      "utf8",
    ),
  );
  const targets = manifest.files.map((row) => row.target_path).sort();
  const repoRoot = join(import.meta.dirname, "../../..");
  const tracked = execFileSync("git", ["ls-files", "--cached"], {
    cwd: repoRoot,
    encoding: "utf8",
  })
    .split(/\r?\n/)
    .filter((path) => targets.includes(path))
    .sort();
  assert.deepEqual(
    tracked,
    targets,
  );
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

test("production adapter sends typed context and fail-closes malformed streams", async () => {
  const source = readFileSync(join(root, "production/ports.ts"), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const { ProductionKnowledgeAdapter, KnowledgeAdapterError } = await import(
    `data:text/javascript,${encodeURIComponent(output)}`
  );
  const calls = [];
  const adapter = new ProductionKnowledgeAdapter({
    fetcher: async (url, init) => {
      calls.push({ url, init });
      return new Response(
        'data: {"schema_version":"v1","stream_id":"s","event_id":"e","sequence":1,"occurred_at":"2026-01-01T00:00:00Z","type":"terminal","payload":{},"terminal":true}\n\n',
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  const context = {
    requestId: "request-1",
    idempotencyKey: "idempotency-1",
    expectedVersion: "V1",
    lastEventId: "event-0",
  };
  const stream = await adapter.stream("assistant.turn", {}, context);
  const events = [];
  for await (const event of stream.events) events.push(event);
  assert.equal(events[0].terminal, true);
  assert.equal(calls[0].init.headers.Accept, "text/event-stream");
  assert.equal(calls[0].init.headers["X-Request-ID"], "request-1");
  assert.equal(calls[0].init.headers["Idempotency-Key"], "idempotency-1");
  assert.equal(calls[0].init.headers["If-Match"], "V1");
  assert.equal(calls[0].init.headers["Last-Event-ID"], "event-0");
  assert.equal(adapter.allowOptimisticUpdates, false);

  const malformed = new ProductionKnowledgeAdapter({
    fetcher: async () =>
      new Response("data: nope\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
  });
  const invalidStream = await malformed.stream("assistant.turn", {}, context);
  await assert.rejects(
    async () => {
      for await (const _event of invalidStream.events) {
        // consume until the parser rejects the malformed frame
      }
    },
    (error) =>
      error instanceof KnowledgeAdapterError &&
      error.issue.code === "INVALID_RESPONSE",
  );
});

test("every frozen module has a fail-closed emitted production boundary", async () => {
  const { transformFrozenProductionMutations } = await import(
    "./productionTransform.mjs"
  );
  const forbiddenRuntimeCalls = [
    /\b(?:resourceStore|connectionStore|actionLoopStore|customRegistryStore|agentPublicationStore)\.setState\s*\(/,
    /\blocalStorage\.(?:getItem|setItem|removeItem|clear)\s*\(/,
    /\bshowToast\??\(\s*["'`][^"'`]*(?:成功|已成功|发布|创建|同步|上传|执行|应用|验证|完成|提交|绑定)["'`]/,
  ];
  let transformedModules = 0;

  for (const path of sourceFiles(frozenRoot)) {
    const source = readFileSync(path, "utf8").replaceAll(
      "localStorage",
      "knowledgeWorkspaceStorage",
    );
    const transformed = transformFrozenProductionMutations(
      source,
      path,
      frozenRoot,
      productionRoot,
    );
    const emitted = transformed?.code ?? source;
    for (const pattern of forbiddenRuntimeCalls) {
      assert.doesNotMatch(
        emitted,
        pattern,
        `${path.slice(frozenRoot.length + 1)} still exposes ${pattern}`,
      );
    }
    if (transformed) transformedModules += 1;
  }

  assert.ok(transformedModules >= 15);
});
