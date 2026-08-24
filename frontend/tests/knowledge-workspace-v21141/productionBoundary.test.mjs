import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
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

function transpileProductionModule(moduleName, replacements = {}) {
  const source = readFileSync(join(productionRoot, moduleName), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  for (const [specifier, replacement] of Object.entries(replacements)) {
    output = output.replaceAll(
      `from ${JSON.stringify(specifier)}`,
      `from ${JSON.stringify(replacement)}`,
    );
  }
  return `data:text/javascript,${encodeURIComponent(output)}`;
}

function productionModuleUrls() {
  const schemaUrl = transpileProductionModule("bootstrapSchema.ts");
  const generatedUrl = transpileProductionModule("generated.ts");
  const generatedClientUrl = transpileProductionModule("generatedClient.ts", {
    "./generated": generatedUrl,
  });
  const typedPortsUrl = transpileProductionModule("typedPorts.ts", {
    "./bootstrapSchema": schemaUrl,
    "./generatedClient": generatedClientUrl,
  });
  const httpSupportUrl = transpileProductionModule("httpSupport.ts", {
    "./bootstrapSchema": schemaUrl,
    "./generated": generatedUrl,
    "./generatedClient": generatedClientUrl,
    "./typedPorts": typedPortsUrl,
  });
  const httpAdapterUrl = transpileProductionModule("httpAdapter.ts", {
    "./bootstrapSchema": schemaUrl,
    "./generated": generatedUrl,
    "./generatedClient": generatedClientUrl,
    "./typedPorts": typedPortsUrl,
    "./httpSupport": httpSupportUrl,
  });
  const portsUrl = transpileProductionModule("ports.ts", {
    "./typedPorts": typedPortsUrl,
    "./httpAdapter": httpAdapterUrl,
  });
  const dataUrl = transpileProductionModule("data.ts", {
    "./bootstrapSchema": schemaUrl,
  });
  return { schemaUrl, generatedUrl, generatedClientUrl, portsUrl, dataUrl };
}

test("production boundary declares typed HTTP/SSE ports and no optimistic success", () => {
  const ports = [
    "ports.ts",
    "typedPorts.ts",
    "httpAdapter.ts",
    "httpSupport.ts",
  ].map((file) => readFileSync(join(root, "production", file), "utf8")).join("\n");
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
  assert.match(vite, /const cleanImporter = importer\?\.split\("\?"\)\[0\]/);
  assert.match(vite, /const cleanSource = source\.split\("\?"\)\[0\]/);
  assert.match(vite, /enforce: "pre"/);
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
  const { portsUrl } = productionModuleUrls();
  const { ProductionKnowledgeAdapter, KnowledgeAdapterError } = await import(
    portsUrl
  );
  const calls = [];
  const adapter = new ProductionKnowledgeAdapter({
    fetcher: async (url, init) => {
      calls.push({ url, init });
      return new Response(
        'data: {"schema_version":"knowledge-workspace.transport.v1","stream_id":"s","event_id":"e","sequence":1,"occurred_at":"2026-01-01T00:00:00Z","type":"terminal","payload":{},"terminal":true}\n\n',
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

test("production adapter preserves caller cancellation and sends durable stream cancellation", async () => {
  const { portsUrl } = productionModuleUrls();
  const { ProductionKnowledgeAdapter } = await import(
    portsUrl
  );
  const calls = [];
  const adapter = new ProductionKnowledgeAdapter({
    fetcher: async (url, init) => {
      calls.push({ url, init });
      if (url.endsWith("/v1/commands")) {
        return new Response(
          JSON.stringify({ accepted: true, requestId: init.headers["X-Request-ID"] }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response(
        'data: {"schema_version":"knowledge-workspace.transport.v1","stream_id":"stream-1","event_id":"event-1","sequence":1,"occurred_at":"2026-01-01T00:00:00Z","type":"progress","payload":{},"terminal":false}\n\n',
        { status: 200, headers: { "content-type": "text/event-stream" } },
      );
    },
  });
  const caller = new AbortController();
  const context = {
    requestId: "request-2",
    idempotencyKey: "idempotency-2",
    signal: caller.signal,
  };
  const stream = await adapter.stream("assistant.turn", {}, context);
  const events = stream.events[Symbol.asyncIterator]();
  const first = await events.next();
  assert.equal(first.value.stream_id, "stream-1");
  await stream.cancel();
  assert.equal(calls[1].url, "/api/knowledge-assets/v1/commands");
  assert.equal(JSON.parse(calls[1].init.body).command, "stream.cancel");
  assert.equal(JSON.parse(calls[1].init.body).payload.streamId, "stream-1");
  assert.equal(caller.signal.aborted, false);
});

test("production adapter exposes structured server errors without treating them as success", async () => {
  const { portsUrl } = productionModuleUrls();
  const { ProductionKnowledgeAdapter, KnowledgeAdapterError } = await import(
    portsUrl
  );
  const adapter = new ProductionKnowledgeAdapter({
    fetcher: async () =>
      new Response(
        JSON.stringify({
          code: "CREDENTIAL_EXPIRED",
          message: "连接凭据已过期，请重新授权。",
          retryable: false,
          request_id: "server-request-3",
          details: { connector: "oracle", token: "redacted-by-server" },
        }),
        {
          status: 401,
          headers: { "content-type": "application/problem+json", "Retry-After": "2" },
        },
      ),
  });
  await assert.rejects(
    () => adapter.command("connector.test", {}, {
      requestId: "request-3",
      idempotencyKey: "idempotency-3",
    }),
    (error) => {
      assert.ok(error instanceof KnowledgeAdapterError);
      assert.equal(error.issue.code, "CREDENTIAL_EXPIRED");
      assert.equal(error.issue.message, "连接凭据已过期，请重新授权。");
      assert.equal(error.issue.retryable, false);
      assert.equal(error.issue.retryAfterMs, 2000);
      assert.deepEqual(error.issue.details, { connector: "oracle" });
      return true;
    },
  );
});

test("production bootstrap validates and exposes server-derived workspace data", async () => {
  const { portsUrl } = productionModuleUrls();
  const { ProductionKnowledgeAdapter, KnowledgeAdapterError } = await import(
    portsUrl
  );
  const workspaceData = {
    connectorCatalog: [{
      connectorKey: "postgresql",
      category: "db",
      name: "PostgreSQL",
      desc: "真实服务端连接器目录项",
      capabilities: ["关系型"],
      inputSchema: { host: "string" },
      credentialSchema: { password: "password" },
      discoveryPipeline: ["连接测试"],
      syncModes: ["incremental"],
    }],
    datasetFields: [{ name: "order_id", type: "string", desc: "订单编号" }],
    dashboard: {
      kpis: [{ label: "总销售额", value: "¥ 1", trend: "+1%", isUp: true }],
      trendData: [{ name: "周一", sales: 1, profit: 2 }],
    },
    knowledgeGraph: {
      entities: [{ id: "e1", name: "Customer", props: 1, constraints: "ID 唯一" }],
      mappings: [{ id: "m1", onto: "Customer.id", db: "customers.id", status: "pending" }],
    },
  };
  const base = {
    resources: [],
    connections: [],
    publications: [],
    routes: ["welcome"],
    access: { spaceId: "space-1", role: "editor", capabilities: [] },
    serverTime: "2026-01-01T00:00:00.000Z",
    workspaceData,
    actionLoop: {
      signals: [],
      policies: [],
      todos: [],
      reviews: [],
      briefs: [],
    },
  };
  const adapter = new ProductionKnowledgeAdapter({
    fetcher: async () =>
      new Response(JSON.stringify(base), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  });
  const bootstrap = await adapter.bootstrap();
  assert.deepEqual(bootstrap.workspaceData, workspaceData);

  const malformed = new ProductionKnowledgeAdapter({
    fetcher: async () =>
      new Response(JSON.stringify({
        ...base,
        workspaceData: { ...workspaceData, dashboard: { kpis: [] } },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  });
  await assert.rejects(
    () => malformed.bootstrap(),
    (error) =>
      error instanceof KnowledgeAdapterError &&
      error.issue.code === "INVALID_RESPONSE",
  );
});

test("aborted bootstrap does not replace a later workspace result with a stale error", async () => {
  const { portsUrl, dataUrl } = productionModuleUrls();
  const storeOutput = ts
    .transpileModule(
      readFileSync(join(root, "production/store.ts"), "utf8"),
      {
        compilerOptions: {
          module: ts.ModuleKind.ESNext,
          target: ts.ScriptTarget.ES2022,
        },
      },
    )
    .outputText.replace('from "./ports";', `from ${JSON.stringify(portsUrl)};`)
    .replace(
      'from "./data";',
      `from ${JSON.stringify(dataUrl)};`,
    )
    .replace(
      'from "react";',
      `from ${JSON.stringify(
        pathToFileURL(join(import.meta.dirname, "../../node_modules/react/index.js")),
      )};`,
    );
  const store = await import(
    `data:text/javascript,${encodeURIComponent(storeOutput)}`
  );
  const error = new Error("aborted");
  const controller = new AbortController();
  controller.abort();
  const adapter = {
    kind: "production-http",
    allowOptimisticUpdates: false,
    async bootstrap() {
      throw error;
    },
    async command() {
      return { accepted: true, requestId: "request-1" };
    },
    async stream() {
      throw new Error("not used");
    },
  };
  store.installWorkspaceAdapter(adapter);
  await assert.rejects(
    store.bootstrapWorkspace(controller.signal),
    (received) => received === error,
  );
  assert.equal(store.getWorkspaceError(), null);
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

test("prototype catalog and seed data are stripped from production modules", async () => {
  const { stripPrototypeProductionDefaults } = await import(
    "./productionTransform.mjs"
  );
  const { transformFrozenProductionMutations } = await import(
    "./productionTransform.mjs"
  );
  const tree = stripPrototypeProductionDefaults(
    readFileSync(
      join(frozenRoot, "components/Layout/FileTreePane.tsx"),
      "utf8",
    ),
    join(frozenRoot, "components/Layout/FileTreePane.tsx"),
  );
  assert.doesNotMatch(tree, /dashboard_sales_east|team_dashboard_monthly|semantic_sales/);
  assert.match(tree, /const defaultPersonal = \[\];/);
  assert.match(tree, /const defaultTeam = \[\];/);
  assert.match(
    tree,
    /r\.resourceKind === 'artifact' \? \(r\.space === 'team' \? 'team_artifact' : 'personal_artifact'\) : r\.resourceKind/,
  );
  assert.match(tree, /r\.subtype === 'chart' \? FilePieChart/);
  assert.match(tree, /r\.subtype === 'knowledge_base' \? Library/);

  const graph = stripPrototypeProductionDefaults(
    readFileSync(
      join(frozenRoot, "components/MainArea/KnowledgeGraphView.tsx"),
      "utf8",
    ),
    join(frozenRoot, "components/MainArea/KnowledgeGraphView.tsx"),
  );
  assert.doesNotMatch(graph, /Customer \(客户\)|m_sales/);
  assert.match(graph, /const \[mappings, setMappings\] = useState<any\[\]>\(\[\]\);/);

  const mainArea = stripPrototypeProductionDefaults(
    readFileSync(
      join(frozenRoot, "components/Layout/MainAreaPane.tsx"),
      "utf8",
    ),
    join(frozenRoot, "components/Layout/MainAreaPane.tsx"),
  );
  assert.match(mainArea, /ProductionRouteUnavailable/);
  assert.match(mainArea, /isProductionRouteAvailable\(fileId\)/);

  const share = transformFrozenProductionMutations(
    readFileSync(join(frozenRoot, "components/Modals/ShareModal.tsx"), "utf8"),
    join(frozenRoot, "components/Modals/ShareModal.tsx"),
    frozenRoot,
    productionRoot,
  ).code;
  assert.doesNotMatch(share, /showToast\??\.\([^;\n]*(?:成功|已成功|创建|发布|同步|上传|执行|应用|验证|完成|提交|绑定|授权|生效)/);
  assert.match(share, /已发送请求，等待状态刷新/);

  const store = readFileSync(join(productionRoot, "store.ts"), "utf8");
  assert.match(store, /SERVER_FEATURE_ROUTES/);
  assert.match(store, /resourceStore\s*\.getState\(\)\s*\.some/);
  assert.match(store, /SERVER_FEATURE_ROUTES\.has\(fileId\) && workspaceRoutes\.has\(fileId\)/);
});

test("production transforms are idempotent for route fallback and runtime import", async () => {
  const { stripPrototypeProductionDefaults, transformFrozenProductionMutations } =
    await import("./productionTransform.mjs");
  const treeFilePath = join(
    frozenRoot,
    "components/Layout/FileTreePane.tsx",
  );
  const treeSource = readFileSync(treeFilePath, "utf8");
  const treeStrippedTwice = stripPrototypeProductionDefaults(
    stripPrototypeProductionDefaults(treeSource, treeFilePath),
    treeFilePath,
  );
  assert.match(treeStrippedTwice, /const defaultPersonal = \[\];/);
  assert.match(treeStrippedTwice, /const defaultTeam = \[\];/);
  assert.match(treeStrippedTwice, /const treeData = \[/);

  const filePath = join(frozenRoot, "components/Layout/MainAreaPane.tsx");
  const source = readFileSync(filePath, "utf8");

  const strippedOnce = stripPrototypeProductionDefaults(source, filePath);
  const strippedTwice = stripPrototypeProductionDefaults(strippedOnce, filePath);
  assert.equal(
    strippedTwice.match(/const ProductionRouteUnavailable/g)?.length ?? 0,
    1,
  );
  assert.equal(
    strippedTwice.match(
      /isWorkspaceRouteAvailable as isProductionRouteAvailable/g,
    )?.length ?? 0,
    1,
  );

  const mutationFilePath = join(
    frozenRoot,
    "components/Layout/WorkspaceLayout.tsx",
  );
  const transformedOnce = transformFrozenProductionMutations(
    readFileSync(mutationFilePath, "utf8"),
    mutationFilePath,
    frozenRoot,
    productionRoot,
  );
  assert.ok(transformedOnce);
  const transformedTwice = transformFrozenProductionMutations(
    transformedOnce.code,
    mutationFilePath,
    frozenRoot,
    productionRoot,
  );
  const emitted = transformedTwice?.code ?? transformedOnce.code;
  assert.equal(
    emitted.match(
      /import \{ runProductionMutation as __runProductionMutation \}/g,
    )?.length ?? 0,
    1,
  );
});

test("neutralized success handlers still dispatch a typed production command", async () => {
  const { transformFrozenProductionMutations } = await import(
    "./productionTransform.mjs"
  );
  const filePath = join(
    frozenRoot,
    "components/Layout/WorkspaceLayout.tsx",
  );
  const transformed = transformFrozenProductionMutations(
    readFileSync(filePath, "utf8"),
    filePath,
    frozenRoot,
    productionRoot,
  );
  assert.ok(transformed);
  const publishHandler = transformed.code.match(
    /modal === 'publish'[\s\S]{0,240}/,
  )?.[0];
  assert.match(publishHandler ?? "", /__runProductionMutation/);
  assert.match(publishHandler ?? "", /resource\.publish/);
  assert.doesNotMatch(publishHandler ?? "", /已成功发布/);
});

test("real knowledge-base create CTA dispatches the skill draft command", async () => {
  const { transformFrozenProductionMutations } = await import(
    "./productionTransform.mjs"
  );
  const filePath = join(
    frozenRoot,
    "components/MainArea/AddKnowledgeBaseView.tsx",
  );
  const transformed = transformFrozenProductionMutations(
    readFileSync(filePath, "utf8"),
    filePath,
    frozenRoot,
    productionRoot,
  );
  assert.ok(transformed);
  assert.match(transformed.code, /"command":"skill-draft\.create"/);
  assert.match(transformed.code, /handleCreate/);
  assert.doesNotMatch(transformed.code, /resourceStore\.setState\s*\(/);
});

test("local source preparation remains local until the create CTA", async () => {
  const { transformFrozenProductionMutations } = await import(
    "./productionTransform.mjs"
  );
  const source = `
    function handleLocalUpload(name) {
      setSources([...sources, { name }]);
    }
    export function AddKnowledgeBaseView() {
      return <span onClick={(event) => { event.preventDefault(); handleLocalUpload("sample.pdf"); }}>sample</span>;
    }
  `;
  const transformed = transformFrozenProductionMutations(
    source,
    "/repo/components/MainArea/AddKnowledgeBaseView.tsx",
    "/repo",
    "/repo/production",
  );
  assert.equal(transformed, null);
});

test("real Skill Builder publish CTA dispatches manifest persistence", async () => {
  const { transformFrozenProductionMutations } = await import(
    "./productionTransform.mjs"
  );
  const filePath = join(
    frozenRoot,
    "components/MainArea/SkillBuilderView.tsx",
  );
  const transformed = transformFrozenProductionMutations(
    readFileSync(filePath, "utf8"),
    filePath,
    frozenRoot,
    productionRoot,
  );
  assert.ok(transformed);
  assert.match(transformed.code, /"command":"skill-draft\.save-manifest"/);
  assert.match(transformed.code, /handlePublish/);
  assert.doesNotMatch(transformed.code, /resourceStore\.setState\s*\(/);
});

test("assistant composer keeps the frozen Enter transition behind adapter acceptance", async () => {
  const { transformFrozenProductionMutations } = await import(
    "./productionTransform.mjs"
  );
  const filePath = join(
    frozenRoot,
    "components/RightPane/ChatAssistant.tsx",
  );
  const transformed = transformFrozenProductionMutations(
    readFileSync(filePath, "utf8"),
    filePath,
    frozenRoot,
    productionRoot,
  );
  assert.ok(transformed);
  assert.match(transformed.code, /"command":"assistant\.turn"/);
  assert.match(transformed.code, /__kwAccepted/);
  assert.match(
    transformed.code,
    /key !== "Enter"[\s\S]{0,120}shiftKey/,
  );
  assert.doesNotMatch(transformed.code, /isComposing/);
  assert.doesNotMatch(
    transformed.code,
    /onKeyDown=\{\(\.\.\.__kwArgs\d+\) => \{ void __runProductionMutation\(/,
  );
});
