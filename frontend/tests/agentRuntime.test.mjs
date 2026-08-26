import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const require = createRequire(import.meta.url);

const root = join(
  import.meta.dirname,
  "../src/knowledge-workspace/agent-runtime",
);

async function importTypescript(moduleName) {
  const source = readFileSync(join(root, moduleName), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  return import(
    `data:text/javascript;base64,${Buffer.from(output).toString("base64")}`
  );
}

async function importBundled(moduleName) {
  const result = await build({
    absWorkingDir: root,
    entryPoints: [moduleName],
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    write: false,
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`
  );
}

async function requireComponent(moduleName, exportName) {
  const result = await build({
    absWorkingDir: root,
    entryPoints: [moduleName],
    bundle: true,
    external: ["react", "react-dom", "react-dom/*"],
    format: "cjs",
    platform: "node",
    target: "es2022",
    write: false,
    loader: { ".css": "empty" },
  });
  const module = { exports: {} };
  Function("require", "module", "exports", result.outputFiles[0].text)(
    require,
    module,
    module.exports,
  );
  return module.exports[exportName];
}

test("SSE parser handles split frames, comments, and canonical event IDs", async () => {
  const { parseAuthoringSse } = await importTypescript("sse.ts");
  const encoder = new TextEncoder();
  const response = new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(": heartbeat\n\nid: op_1:"));
        controller.enqueue(
          encoder.encode(
            '2\nevent: answer.delta\ndata: {"operation_id":"op_1","event_id":"evt_2","sequence":2,"event_type":"answer.delta","type":"answer.delta","payload":{"text":"你好"},"public_summary":"Answer updated","terminal":false,"occurred_at":"2026-08-25T00:00:00Z"}\n\n',
          ),
        );
        controller.close();
      },
    }),
    { headers: { "content-type": "text/event-stream" } },
  );
  const events = [];
  for await (const event of parseAuthoringSse(response)) events.push(event);
  assert.equal(events.length, 1);
  assert.equal(events[0].cursor, "op_1:2");
  assert.equal(events[0].type, "answer.delta");
  assert.equal(events[0].payload.text, "你好");
});

test("SSE parser applies its size limit to each frame, not a multi-frame chunk", async () => {
  const { parseAuthoringSse } = await importTypescript("sse.ts");
  const encoder = new TextEncoder();
  const frame = (sequence, text) =>
    `id: op_1:${sequence}\nevent: answer.delta\ndata: ${JSON.stringify({
      operation_id: "op_1",
      event_id: `evt_${sequence}`,
      sequence,
      event_type: "answer.delta",
      type: "answer.delta",
      payload: { text },
      public_summary: "Answer updated",
      terminal: false,
      occurred_at: "2026-08-25T00:00:00Z",
    })}\n\n`;
  const response = new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(frame(1, "a".repeat(140_000)) + frame(2, "b".repeat(140_000))),
        );
        controller.close();
      },
    }),
    { headers: { "content-type": "text/event-stream" } },
  );

  const events = [];
  for await (const event of parseAuthoringSse(response)) events.push(event);
  assert.deepEqual(events.map((event) => event.sequence), [1, 2]);
});

test("stream start client submits one idempotent turn and exposes its operation", () => {
  const client = readFileSync(join(root, "client.ts"), "utf8");
  assert.match(client, /export async function startAuthoringOperation/);
  assert.match(client, /"Idempotency-Key"/);
  assert.match(client, /"skill-authoring\.start"/);
  assert.match(client, /X-Operation-ID/);
  assert.doesNotMatch(client, /skill-authoring\.answer/);
});

test("timeline reducer deduplicates replay and merges answer deltas", async () => {
  const { createTimelineState, reduceTimelineEvent } =
    await importTypescript("timelineState.ts");
  const base = {
    cursor: "op_1:1",
    operation_id: "op_1",
    event_id: "evt_1",
    sequence: 1,
    event_type: "answer.delta",
    type: "answer.delta",
    payload: { text: "Hello" },
    public_summary: "Answer updated",
    terminal: false,
    occurred_at: "2026-08-25T00:00:00Z",
  };
  let state = reduceTimelineEvent(createTimelineState("op_1"), base);
  state = reduceTimelineEvent(state, base);
  state = reduceTimelineEvent(state, {
    ...base,
    cursor: "op_1:2",
    event_id: "evt_2",
    sequence: 2,
    payload: { text: " world" },
  });
  assert.equal(state.events.length, 2);
  assert.equal(state.answerText, "Hello world");
  assert.equal(state.lastEventId, "op_1:2");
});

test("timeline reducer uses the public tool name emitted by the Runner", async () => {
  const { createTimelineState, reduceTimelineEvent } =
    await importTypescript("timelineState.ts");
  const event = {
    cursor: "op_1:1",
    operation_id: "op_1",
    event_id: "evt_tool_1",
    sequence: 1,
    event_type: "tool.started",
    type: "tool.started",
    payload: {
      tool_name: "query_database",
      call_id: "call_1",
      input_summary: "table=orders",
    },
    public_summary: "Calling query_database",
    terminal: false,
    occurred_at: "2026-08-25T00:00:00Z",
  };

  const state = reduceTimelineEvent(createTimelineState("op_1"), event);

  assert.equal(state.tools[0]?.name, "query_database");
  assert.equal(state.tools[0]?.inputSummary, "table=orders");
});

test("timeline reducer honors a public tool category for MCP names", async () => {
  const { createTimelineState, reduceTimelineEvent } =
    await importTypescript("timelineState.ts");
  const state = reduceTimelineEvent(createTimelineState("op_mcp"), {
    cursor: "op_mcp:1",
    operation_id: "op_mcp",
    event_id: "evt_mcp",
    sequence: 1,
    event_type: "tool.started",
    type: "tool.started",
    payload: {
      tool_name: "infrastructure.metrics",
      tool_category: "mcp",
      call_id: "call_mcp",
    },
    public_summary: "Querying infrastructure metrics",
    terminal: false,
    occurred_at: "2026-08-25T00:00:00Z",
  });

  assert.equal(state.tools[0]?.category, "mcp");
});

test("timeline reducer joins tool completion when the transport omits call_id", async () => {
  const { createTimelineState, reduceTimelineEvent } =
    await importTypescript("timelineState.ts");
  const event = (sequence, type, payload) => ({
    cursor: `op_missing_id:${sequence}`,
    operation_id: "op_missing_id",
    event_id: `evt_missing_id_${sequence}`,
    sequence,
    event_type: type,
    type,
    payload,
    public_summary: type,
    terminal: false,
    occurred_at: `2026-08-25T00:00:0${sequence}Z`,
  });

  let state = reduceTimelineEvent(
    createTimelineState("op_missing_id"),
    event(1, "tool.started", {
      tool_name: "infrastructure.metrics",
      tool_category: "mcp",
      input_summary: "service=all",
    }),
  );
  state = reduceTimelineEvent(
    state,
    event(2, "tool.completed", {
      tool_name: "infrastructure.metrics",
      tool_category: "mcp",
      output_summary: "2 rows",
      duration_ms: 17,
    }),
  );

  assert.equal(state.tools.length, 1);
  assert.equal(state.tools[0]?.status, "completed");
  assert.equal(state.tools[0]?.durationMs, 17);
  assert.equal(state.tools[0]?.inputSummary, "service=all");
});

test("timeline reducer rebuilds ordered text when replay arrives out of order", async () => {
  const { createTimelineState, reduceTimelineEvent } =
    await importTypescript("timelineState.ts");
  const event = (sequence, text) => ({
    cursor: `op_1:${sequence}`,
    operation_id: "op_1",
    event_id: `evt_${sequence}`,
    sequence,
    event_type: "answer.delta",
    type: "answer.delta",
    payload: { text },
    public_summary: "Answer updated",
    terminal: false,
    occurred_at: "2026-08-25T00:00:00Z",
  });

  let state = reduceTimelineEvent(createTimelineState("op_1"), event(2, " world"));
  state = reduceTimelineEvent(state, event(1, "Hello"));
  state = reduceTimelineEvent(state, {
    ...event(2, "duplicate"),
    event_id: "evt_replayed_with_different_id",
  });

  assert.equal(state.answerText, "Hello world");
  assert.equal(state.lastEventId, "op_1:2");
  assert.deepEqual(state.events.map((item) => item.sequence), [1, 2]);
});

test("timeline reducer transitions plan, typed tools, and artifact revisions", async () => {
  const { createTimelineState, reduceTimelineEvent } =
    await importTypescript("timelineState.ts");
  const buildEvent = (sequence, type, payload) => ({
    cursor: `op_1:${sequence}`,
    operation_id: "op_1",
    event_id: `evt_${sequence}`,
    sequence,
    event_type: type,
    type,
    payload,
    public_summary: type,
    terminal: false,
    occurred_at: `2026-08-25T00:00:0${sequence}Z`,
  });
  let state = createTimelineState("op_1");
  for (const item of [
    buildEvent(1, "plan.created", {
      steps: [
        { id: "context", label: "解析上下文", status: "completed" },
        { id: "query", label: "查询数据", status: "pending" },
      ],
    }),
    buildEvent(2, "plan.step.started", { step_id: "query" }),
    buildEvent(3, "tool.started", {
      call_id: "sql_1",
      tool_name: "execute_sql_query",
      input_summary: "SELECT count(*) FROM orders",
    }),
    buildEvent(4, "tool.completed", {
      call_id: "sql_1",
      tool_name: "execute_sql_query",
      output_summary: "1 row",
      duration_ms: 42,
    }),
    buildEvent(5, "plan.step.completed", { step_id: "query" }),
    buildEvent(6, "artifact.revision.created", {
      draft_id: "draft_1",
      revision: "2",
      display_name: "订单分析",
    }),
  ]) {
    state = reduceTimelineEvent(state, item);
  }

  assert.deepEqual(state.plan.map((step) => step.status), [
    "completed",
    "completed",
  ]);
  assert.equal(state.tools[0]?.category, "database");
  assert.equal(state.tools[0]?.status, "completed");
  assert.equal(state.tools[0]?.durationMs, 42);
  assert.deepEqual(state.artifacts[0], {
    id: "draft_1",
    revision: 2,
    label: "订单分析",
    uri: undefined,
  });
});

test("timeline reducer renders typed clarification questions as the final answer", async () => {
  const { createTimelineState, reduceTimelineEvent } =
    await importTypescript("timelineState.ts");
  let state = reduceTimelineEvent(createTimelineState("op_question"), {
    cursor: "op_question:1",
    operation_id: "op_question",
    event_id: "evt_question",
    sequence: 1,
    event_type: "answer.final",
    type: "answer.final",
    payload: {
      status: "awaiting_input",
      clarification_questions: ["请选择数据范围。", "是否包含历史数据？"],
    },
    public_summary: "Clarification required",
    terminal: false,
    occurred_at: "2026-08-25T00:00:00Z",
  });

  assert.equal(
    state.answerText,
    "需要确认以下信息：\n\n- 请选择数据范围。\n- 是否包含历史数据？",
  );
  assert.equal(state.finalAnswer, state.answerText);
  state = reduceTimelineEvent(state, {
    cursor: "op_question:2",
    operation_id: "op_question",
    event_id: "evt_question_done",
    sequence: 2,
    event_type: "operation.completed",
    type: "operation.completed",
    payload: { status: "awaiting_input" },
    public_summary: "Waiting for clarification",
    terminal: true,
    occurred_at: "2026-08-25T00:00:01Z",
  });
  assert.equal(state.status, "awaiting_input");
});

test("runtime controller reconnects with Last-Event-ID and deduplicates replay", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const calls = { start: 0, follow: [] };
  const base = (sequence, type, payload, terminal = false) => ({
    cursor: `op_1:${sequence}`,
    operation_id: "op_1",
    event_id: `evt_${sequence}`,
    sequence,
    event_type: type,
    type,
    payload,
    public_summary: type,
    terminal,
    occurred_at: "2026-08-25T00:00:00Z",
  });
  const clients = {
    async start() {
      calls.start += 1;
      return {
        operationId: "op_1",
        events: (async function* () {
          yield base(1, "message.accepted", {});
          yield base(2, "answer.delta", { text: "Hello" });
          throw new TypeError("offline");
        })(),
      };
    },
    async *follow(_operationId, options) {
      calls.follow.push(options.lastEventId);
      yield base(2, "answer.delta", { text: "duplicate" });
      yield base(3, "answer.delta", { text: " world" });
      yield base(4, "answer.final", { text: "Hello world" });
      yield base(5, "operation.completed", {}, true);
    },
    async cancel() {},
    async retry() {},
  };
  const controller = new AgentRuntimeController({
    clients,
    retryDelaysMs: [0],
  });

  await controller.start({ prompt: "hello" });
  await controller.waitForSettled();

  assert.equal(calls.start, 1);
  assert.deepEqual(calls.follow, ["op_1:2"]);
  assert.equal(controller.getState().answerText, "Hello world");
  assert.equal(controller.getState().events.length, 5);
  assert.equal(controller.getState().status, "completed");
});

test("runtime controller retries an uncertain start with one idempotency key", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const keys = [];
  let attempts = 0;
  const terminal = {
    cursor: "op_once:1",
    operation_id: "op_once",
    event_id: "evt_once",
    sequence: 1,
    event_type: "operation.completed",
    type: "operation.completed",
    payload: {},
    public_summary: "done",
    terminal: true,
    occurred_at: "2026-08-25T00:00:00Z",
  };
  const controller = new AgentRuntimeController({
    clients: {
      async start(_input, options) {
        attempts += 1;
        keys.push(options.idempotencyKey);
        if (attempts === 1) throw new TypeError("connection reset");
        return {
          operationId: "op_once",
          events: (async function* () {
            yield terminal;
          })(),
        };
      },
      async *follow() {},
      async cancel() {},
      async retry() {},
    },
    retryDelaysMs: [0],
    idempotencyKeyFactory: () => "stable-key",
  });

  assert.equal(await controller.start({ prompt: "once" }), "op_once");
  await controller.waitForSettled();

  assert.equal(attempts, 2);
  assert.deepEqual(keys, ["stable-key", "stable-key"]);
});

test("runtime controller starts idle so the first message can be submitted", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const controller = new AgentRuntimeController({
    clients: {
      async start() {
        throw new Error("not used");
      },
      async *follow() {},
      async cancel() {},
      async retry() {},
    },
  });

  assert.equal(controller.active, false);
  assert.equal(controller.getState().status, "idle");
});

test("manual retry of an uncertain start keeps the original idempotency key", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const keys = [];
  let attempts = 0;
  const controller = new AgentRuntimeController({
    clients: {
      async start(_input, options) {
        attempts += 1;
        keys.push(options.idempotencyKey);
        if (attempts === 1) throw new TypeError("offline");
        return {
          operationId: "op_manual_retry",
          events: (async function* () {
            yield {
              cursor: "op_manual_retry:1",
              operation_id: "op_manual_retry",
              event_id: "evt_manual_retry",
              sequence: 1,
              event_type: "operation.completed",
              type: "operation.completed",
              payload: {},
              public_summary: "done",
              terminal: true,
              occurred_at: "2026-08-25T00:00:00Z",
            };
          })(),
        };
      },
      async *follow() {},
      async cancel() {},
      async retry() {
        throw new Error("pending starts must not call the operation retry route");
      },
    },
    retryDelaysMs: [],
    idempotencyKeyFactory: () => "manual-stable-key",
  });

  await assert.rejects(controller.start({ prompt: "只提交一次" }), /offline/);
  assert.equal(await controller.retry(), "op_manual_retry");
  await controller.waitForSettled();

  assert.deepEqual(keys, ["manual-stable-key", "manual-stable-key"]);
  assert.equal(controller.getState().operationId, "op_manual_retry");
  assert.equal(controller.getState().userPrompt, "只提交一次");
});

test("runtime controller blocks overlapping sends and stops the server Runner", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  let release;
  let cancelOperationId;
  const clients = {
    async start() {
      return {
        operationId: "op_active",
        events: (async function* () {
          yield {
            cursor: "op_active:1",
            operation_id: "op_active",
            event_id: "evt_1",
            sequence: 1,
            event_type: "answer.delta",
            type: "answer.delta",
            payload: { text: "partial" },
            public_summary: "Answering",
            terminal: false,
            occurred_at: "2026-08-25T00:00:00Z",
          };
          await new Promise((resolve) => {
            release = resolve;
          });
        })(),
      };
    },
    async *follow() {
      yield {
        cursor: "op_active:2",
        operation_id: "op_active",
        event_id: "evt_2",
        sequence: 2,
        event_type: "operation.cancelled",
        type: "operation.cancelled",
        payload: {},
        public_summary: "Operation cancelled",
        terminal: true,
        occurred_at: "2026-08-25T00:00:01Z",
      };
    },
    async cancel(operationId) {
      cancelOperationId = operationId;
      release?.();
    },
    async retry() {},
  };
  const controller = new AgentRuntimeController({
    clients,
    retryDelaysMs: [],
  });

  await controller.start({ prompt: "first" });
  await assert.rejects(
    controller.start({ prompt: "second" }),
    /已有回答正在生成/,
  );
  await controller.stop();
  await controller.waitForSettled();

  assert.equal(cancelOperationId, "op_active");
  assert.equal(controller.getState().answerText, "partial");
  assert.equal(controller.getState().status, "cancelled");
  assert.equal(controller.getState().warning, "已停止");
});

test("runtime retry follows only the replacement operation", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const followed = [];
  const clients = {
    async start() {
      throw new Error("not used");
    },
    async *follow(operationId) {
      followed.push(operationId);
      yield {
        cursor: `${operationId}:1`,
        operation_id: operationId,
        event_id: `evt_${operationId}`,
        sequence: 1,
        event_type: "operation.completed",
        type: "operation.completed",
        payload: {},
        public_summary: "done",
        terminal: true,
        occurred_at: "2026-08-25T00:00:00Z",
      };
    },
    async cancel() {},
    async retry(operationId) {
      assert.equal(operationId, "op_failed");
      return { operation: { operation_id: "op_retry" } };
    },
  };
  const controller = new AgentRuntimeController({
    clients,
    snapshotStore: {
      load: () => ({ operationId: "op_failed", lastEventId: "op_failed:4" }),
      save() {},
      clear() {},
    },
  });
  await controller.restore();
  await controller.waitForSettled();
  controller.getState().status = "failed";

  assert.equal(await controller.retry(), "op_retry");
  await controller.waitForSettled();

  assert.deepEqual(followed, ["op_failed", "op_retry"]);
  assert.equal(controller.getState().operationId, "op_retry");
  assert.equal(controller.getState().status, "completed");
});

test("runtime retry preserves the original user prompt", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const failed = {
    cursor: "op_failed:1",
    operation_id: "op_failed",
    event_id: "evt_failed",
    sequence: 1,
    event_type: "operation.failed",
    type: "operation.failed",
    payload: { code: "model_unavailable", message: "暂时不可用" },
    public_summary: "暂时不可用",
    terminal: true,
    occurred_at: "2026-08-25T00:00:00Z",
  };
  const controller = new AgentRuntimeController({
    clients: {
      async start() {
        throw new Error("not used");
      },
      async *follow(operationId) {
        yield {
          cursor: `${operationId}:1`,
          operation_id: operationId,
          event_id: "evt_retry_done",
          sequence: 1,
          event_type: "operation.completed",
          type: "operation.completed",
          payload: {},
          public_summary: "done",
          terminal: true,
          occurred_at: "2026-08-25T00:00:01Z",
        };
      },
      async cancel() {},
      async retry() {
        return { operation: { operation_id: "op_retry_prompt" } };
      },
    },
    snapshotStore: {
      load: () => ({
        operationId: "op_failed",
        events: [failed],
        userPrompt: "请重试这条问题",
      }),
      save() {},
      clear() {},
    },
  });

  await controller.restore();
  assert.equal(await controller.retry(), "op_retry_prompt");
  assert.equal(controller.getState().userPrompt, "请重试这条问题");
});

test("runtime restore keeps partial text and resumes the same operation cursor", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const partial = {
    cursor: "op_restore:2",
    operation_id: "op_restore",
    event_id: "evt_restore_2",
    sequence: 2,
    event_type: "answer.delta",
    type: "answer.delta",
    payload: { text: "已经生成" },
    public_summary: "Answering",
    terminal: false,
    occurred_at: "2026-08-25T00:00:00Z",
  };
  let followedWith;
  const controller = new AgentRuntimeController({
    clients: {
      async start() {
        throw new Error("not used");
      },
      async *follow(operationId, options) {
        assert.equal(operationId, "op_restore");
        followedWith = options.lastEventId;
        yield {
          ...partial,
          cursor: "op_restore:3",
          event_id: "evt_restore_3",
          sequence: 3,
          payload: { text: "完成" },
        };
        yield {
          ...partial,
          cursor: "op_restore:4",
          event_id: "evt_restore_4",
          sequence: 4,
          event_type: "operation.completed",
          type: "operation.completed",
          payload: {},
          terminal: true,
        };
      },
      async cancel() {},
      async retry() {},
    },
    snapshotStore: {
      load: () => ({
        operationId: "op_restore",
        lastEventId: "op_restore:2",
        events: [partial],
        userPrompt: "继续之前的回答",
      }),
      save() {},
      clear() {},
    },
  });

  assert.equal(await controller.restore(), true);
  assert.equal(controller.getState().answerText, "已经生成");
  assert.equal(controller.getState().userPrompt, "继续之前的回答");
  await controller.waitForSettled();

  assert.equal(followedWith, "op_restore:2");
  assert.equal(controller.getState().answerText, "已经生成完成");
  assert.deepEqual(
    controller.getState().events.map((event) => event.sequence),
    [2, 3, 4],
  );
});

test("runtime restore rebuilds a terminal snapshot without reconnecting", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  const events = [
    {
      cursor: "op_done:1",
      operation_id: "op_done",
      event_id: "evt_done_1",
      sequence: 1,
      event_type: "answer.final",
      type: "answer.final",
      payload: { text: "最终回答" },
      public_summary: "Answer completed",
      terminal: false,
      occurred_at: "2026-08-25T00:00:00Z",
    },
    {
      cursor: "op_done:2",
      operation_id: "op_done",
      event_id: "evt_done_2",
      sequence: 2,
      event_type: "operation.completed",
      type: "operation.completed",
      payload: {},
      public_summary: "Done",
      terminal: true,
      occurred_at: "2026-08-25T00:00:01Z",
    },
  ];
  let followCalls = 0;
  const controller = new AgentRuntimeController({
    clients: {
      async start() {
        throw new Error("not used");
      },
      async *follow() {
        followCalls += 1;
      },
      async cancel() {},
      async retry() {},
    },
    snapshotStore: {
      load: () => ({
        operationId: "op_done",
        lastEventId: "op_done:2",
        events,
        userPrompt: "刷新后保留",
      }),
      save() {},
      clear() {},
    },
  });

  assert.equal(await controller.restore(), true);
  assert.equal(controller.active, false);
  assert.equal(controller.getState().status, "completed");
  assert.equal(controller.getState().answerText, "最终回答");
  assert.equal(controller.getState().userPrompt, "刷新后保留");
  assert.equal(followCalls, 0);
});

test("disposing an active runtime releases its generation lock", async () => {
  const { AgentRuntimeController } = await importBundled("controller.ts");
  let streamStarted;
  const started = new Promise((resolve) => {
    streamStarted = resolve;
  });
  const controller = new AgentRuntimeController({
    clients: {
      async start() {
        return {
          operationId: "op_dispose",
          events: (async function* () {
            streamStarted();
            await new Promise(() => {});
          })(),
        };
      },
      async *follow() {},
      async cancel() {},
      async retry() {},
    },
  });

  await controller.start({ prompt: "dispose" });
  await started;
  assert.equal(controller.active, true);
  controller.dispose();
  assert.equal(controller.active, false);
});

test("Markdown answer renders GFM safely while a code fence is incomplete", async () => {
  const dom = new JSDOM("<!doctype html><div id=\"root\"></div>", {
    url: "http://localhost/",
    pretendToBeVisual: true,
  });
  const previous = new Map(
    [
      "window",
      "document",
      "navigator",
      "HTMLElement",
      "Node",
      "IS_REACT_ACT_ENVIRONMENT",
    ].map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]),
  );
  for (const [name, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value,
      writable: true,
    });
  }
  const React = require("react");
  const { createRoot } = require("react-dom/client");
  const { act } = require("react-dom/test-utils");
  const MarkdownAnswer = await requireComponent(
    "MarkdownAnswer.tsx",
    "MarkdownAnswer",
  );
  const container = dom.window.document.getElementById("root");
  const rendered = createRoot(container);
  try {
    await act(async () => {
      rendered.render(React.createElement(MarkdownAnswer, {
        streaming: true,
        content: [
          "# 标题",
          "",
          "| A | B |",
          "| - | - |",
          "| 1 | 2 |",
          "",
          "[安全链接](https://example.com)",
          "[危险链接](javascript:alert(1))",
          "",
          "```sql",
          "SELECT * FROM orders",
        ].join("\n"),
      }));
    });

    assert.equal(container.querySelector("h1")?.textContent, "标题");
    assert.equal(container.querySelectorAll("table").length, 1);
    assert.equal(container.querySelector("pre code")?.textContent?.trim(), "SELECT * FROM orders");
    assert.equal(
      container.querySelector('a[href="https://example.com"]')?.getAttribute("rel"),
      "noreferrer noopener",
    );
    assert.equal(container.querySelector('a[href^="javascript:"]'), null);
    assert.equal(container.querySelector("script"), null);
  } finally {
    await act(async () => rendered.unmount());
    dom.window.close();
    for (const [name, descriptor] of previous) {
      if (descriptor === undefined) delete globalThis[name];
      else Object.defineProperty(globalThis, name, descriptor);
    }
  }
});

test("Activity is compact after answer tokens and hidden after completion", async () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const ActivityStatus = await requireComponent(
    "ActivityStatus.tsx",
    "ActivityStatus",
  );
  const state = {
    operationId: "op_activity",
    events: [{
      cursor: "op_activity:1",
      operation_id: "op_activity",
      event_id: "evt_activity",
      sequence: 1,
      event_type: "agent.started",
      type: "agent.started",
      payload: { role: "answer" },
      public_summary: "Answering",
      terminal: false,
      occurred_at: "2026-08-25T00:00:00Z",
    }],
    seenEventIds: new Set(["evt_activity"]),
    lastEventId: "op_activity:1",
    answerText: "正在流式回答",
    tools: [],
    plan: [],
    artifacts: [],
    status: "running",
  };

  const active = renderToStaticMarkup(
    React.createElement(ActivityStatus, { state }),
  );
  const completed = renderToStaticMarkup(
    React.createElement(ActivityStatus, {
      state: { ...state, status: "completed" },
    }),
  );

  assert.match(active, /agent-activity--compact/);
  assert.equal(completed, "");
});

test("Activity advances past a completed tool instead of reporting it as running", async () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const ActivityStatus = await requireComponent(
    "ActivityStatus.tsx",
    "ActivityStatus",
  );
  const event = (sequence, type, summary) => ({
    cursor: `op_activity:${sequence}`,
    operation_id: "op_activity",
    event_id: `evt_activity_${sequence}`,
    sequence,
    event_type: type,
    type,
    payload: { tool_name: "infrastructure.metrics" },
    public_summary: summary,
    terminal: false,
    occurred_at: "2026-08-25T00:00:00Z",
  });
  const markup = renderToStaticMarkup(
    React.createElement(ActivityStatus, {
      state: {
        operationId: "op_activity",
        events: [
          event(1, "tool.started", "Calling infrastructure.metrics"),
          event(2, "tool.completed", "infrastructure.metrics completed"),
        ],
        seenEventIds: new Set(["evt_activity_1", "evt_activity_2"]),
        lastEventId: "op_activity:2",
        answerText: "",
        tools: [],
        plan: [],
        artifacts: [],
        status: "running",
      },
    }),
  );

  assert.match(markup, /infrastructure\.metrics completed/);
  assert.doesNotMatch(markup, /Calling infrastructure\.metrics/);
});

test("timeline renders typed tools, a collapsed multi-step plan, and recovery actions", async () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const AgentTimeline = await requireComponent(
    "AgentTimeline.tsx",
    "AgentTimeline",
  );
  const baseState = {
    operationId: "op_ui",
    events: [],
    seenEventIds: new Set(),
    answerText: "保留的回答",
    tools: [{
      id: "sql_1",
      name: "execute_sql_query",
      category: "database",
      status: "failed",
      inputSummary: "SELECT count(*) FROM orders",
      error: "connection timeout",
      recoveryHint: "请检查网络与数据源状态，然后重试本轮。",
      durationMs: 42,
    }],
    plan: [
      { id: "one", label: "解析上下文", status: "completed" },
      { id: "two", label: "查询数据", status: "running" },
      { id: "three", label: "生成 Skill", status: "pending" },
      { id: "four", label: "保存结果", status: "failed" },
    ],
    artifacts: [],
    status: "failed",
    error: {
      code: "MODEL_UNAVAILABLE",
      message: "Agent 暂时不可用。",
      retryable: true,
      kind: "runner",
    },
  };
  const failed = renderToStaticMarkup(
    React.createElement(AgentTimeline, {
      state: baseState,
      onRetry() {},
    }),
  );
  const disconnected = renderToStaticMarkup(
    React.createElement(AgentTimeline, {
      state: {
        ...baseState,
        status: "disconnected",
        error: {
          code: "STREAM_DISCONNECTED",
          message: "连接已中断。",
          retryable: true,
          kind: "network",
        },
      },
      onResume() {},
    }),
  );
  const singleStep = renderToStaticMarkup(
    React.createElement(AgentTimeline, {
      state: {
        ...baseState,
        tools: [],
        plan: [{ id: "one", label: "简单回答", status: "completed" }],
        status: "completed",
        error: undefined,
      },
    }),
  );
  const cancelled = renderToStaticMarkup(
    React.createElement(AgentTimeline, {
      state: {
        ...baseState,
        status: "cancelled",
        error: undefined,
        warning: "已停止",
      },
      onRetry() {},
    }),
  );

  assert.match(failed, /数据库 \/ SQL/);
  assert.match(failed, /SELECT count\(\*\) FROM orders/);
  assert.match(failed, /请检查网络与数据源状态，然后重试本轮/);
  assert.match(failed, /<details class="agent-plan">/);
  assert.doesNotMatch(failed, /<details class="agent-plan" open/);
  assert.match(failed, /查询数据/);
  assert.match(failed, /1\/4/);
  for (const status of ["已完成", "进行中", "待处理", "失败"]) {
    assert.match(failed, new RegExp(`agent-plan__step-status[^>]*>${status}<`));
  }
  assert.match(failed, />重试</);
  assert.match(disconnected, />继续连接</);
  assert.match(cancelled, />重新运行</);
  assert.doesNotMatch(singleStep, /agent-plan/);
});

test("stick-to-bottom stops on user scroll and resumes across content growth", async () => {
  const { StickToBottomController } = await importBundled("useStickToBottom.ts");
  const scrolls = [];
  const node = {
    scrollHeight: 1_000,
    scrollTop: 500,
    clientHeight: 400,
    scrollTo(options) {
      scrolls.push(options.top);
      this.scrollTop = options.top - this.clientHeight;
    },
  };
  const controller = new StickToBottomController();
  controller.attach(node);

  controller.contentChanged();
  assert.deepEqual(scrolls, [1_000]);
  node.scrollTop = 200;
  controller.userScrolled();
  node.scrollHeight = 1_200;
  controller.contentChanged();
  assert.deepEqual(scrolls, [1_000]);
  assert.equal(controller.following, false);

  controller.resume();
  node.scrollHeight = 1_400;
  controller.contentChanged();
  assert.deepEqual(scrolls, [1_000, 1_200, 1_400]);
  assert.equal(controller.following, true);
});

test("timeline follows height changes from expandable content", async () => {
  const dom = new JSDOM("<!doctype html><div id=\"root\"></div>", {
    url: "http://localhost/",
    pretendToBeVisual: true,
  });
  let resizeObserver;
  class TestResizeObserver {
    constructor(callback) {
      this.callback = callback;
      this.observed = [];
      resizeObserver = this;
    }

    observe(node) {
      this.observed.push(node);
    }

    disconnect() {}
  }
  dom.window.HTMLElement.prototype.scrollTo = () => {};
  const previous = new Map(
    [
      "window",
      "document",
      "navigator",
      "HTMLElement",
      "Node",
      "ResizeObserver",
      "IS_REACT_ACT_ENVIRONMENT",
    ].map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]),
  );
  for (const [name, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    ResizeObserver: TestResizeObserver,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value,
      writable: true,
    });
  }
  const React = require("react");
  const { createRoot } = require("react-dom/client");
  const { act } = require("react-dom/test-utils");
  const AgentTimeline = await requireComponent(
    "AgentTimeline.tsx",
    "AgentTimeline",
  );
  const container = dom.window.document.getElementById("root");
  const rendered = createRoot(container);
  try {
    await act(async () => {
      rendered.render(React.createElement(AgentTimeline, {
        state: {
          operationId: "op_resize",
          events: [],
          seenEventIds: new Set(),
          answerText: "partial",
          tools: [],
          plan: [],
          artifacts: [],
          status: "running",
        },
      }));
    });

    const scroller = container.querySelector(".agent-timeline__scroll");
    const content = container.querySelector(".agent-timeline__content");
    assert.ok(scroller);
    assert.ok(content);
    assert.ok(resizeObserver.observed.includes(content));

    const scrolls = [];
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 1_000 },
      clientHeight: { configurable: true, value: 400 },
      scrollTop: { configurable: true, value: 600, writable: true },
      scrollTo: {
        configurable: true,
        value(options) {
          scrolls.push(options.top);
        },
      },
    });
    resizeObserver.callback();
    assert.deepEqual(scrolls, [1_000]);
  } finally {
    await act(async () => rendered.unmount());
    dom.window.close();
    for (const [name, descriptor] of previous) {
      if (descriptor === undefined) delete globalThis[name];
      else Object.defineProperty(globalThis, name, descriptor);
    }
  }
});

test("runtime components expose accessible controls without unsafe rendering", () => {
  const timeline = readFileSync(join(root, "AgentTimeline.tsx"), "utf8");
  const toolCard = readFileSync(join(root, "ToolCallCard.tsx"), "utf8");
  const plan = readFileSync(join(root, "PlanSummary.tsx"), "utf8");
  const styles = readFileSync(join(root, "agent-runtime.css"), "utf8");
  assert.match(timeline, /aria-live="polite"/);
  assert.match(timeline, /onStop/);
  assert.match(timeline, /onRetry/);
  assert.match(timeline, /onResume/);
  assert.match(toolCard, /<details/);
  assert.match(plan, /<details/);
  assert.doesNotMatch(
    `${timeline}\n${toolCard}\n${plan}`,
    /dangerouslySetInnerHTML/,
  );
  assert.match(styles, /prefers-reduced-motion:\s*reduce/);
  assert.match(styles, /@media\s*\(max-width:\s*560px\)/);
});

test("agent-runtime boundary is isolated from frozen UI", () => {
  const files = [
    "contracts.ts",
    "sse.ts",
    "client.ts",
    "timelineState.ts",
    "useStickToBottom.ts",
    "AgentTimeline.tsx",
    "ToolCallCard.tsx",
    "PlanSummary.tsx",
    "index.ts",
  ];
  for (const file of files) {
    const source = readFileSync(join(root, file), "utf8");
    assert.doesNotMatch(source, /frozen-ui/);
    assert.doesNotMatch(source, /setTimeout\s*\(/);
  }
});

test("agent runtime styling uses Studio semantic tokens and keeps multi-turn history scrollable", () => {
  const styles = readFileSync(join(root, "agent-runtime.css"), "utf8");
  const harnessStyles = readFileSync(join(root, "harness.css"), "utf8");
  assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}|rgb\(/);
  assert.doesNotMatch(harnessStyles, /#[0-9a-fA-F]{3,8}|rgb\(/);
  assert.match(styles, /\.agent-conversation__body\s*\{[\s\S]*overflow:\s*auto/);
  assert.match(styles, /--agent-bg:\s*hsl\(var\(--canvas/);
  assert.match(harnessStyles, /--harness-canvas:\s*hsl\(var\(--canvas/);
});

test("standalone harness mounts the real runtime without simulated streaming", () => {
  const htmlPath = join(root, "../../../agent-runtime-harness.html");
  const faviconPath = join(root, "../../../public/agent-runtime.svg");
  const entryPath = join(root, "harness.tsx");
  assert.equal(existsSync(htmlPath), true);
  assert.equal(existsSync(faviconPath), true);
  assert.equal(existsSync(entryPath), true);
  const html = readFileSync(htmlPath, "utf8");
  const entry = readFileSync(entryPath, "utf8");
  assert.match(html, /rel="icon"[^>]+href="\/agent-runtime\.svg"/);
  assert.match(html, /agent-runtime\/harness\.tsx/);
  assert.match(entry, /<AgentConversation/);
  assert.match(entry, /resourceRefs/);
  assert.doesNotMatch(entry, /setTimeout|mock|fixture/i);
});
