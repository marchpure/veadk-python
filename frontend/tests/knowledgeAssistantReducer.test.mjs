import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";

const result = await build({
  entryPoints: [fileURLToPath(new URL(
    "../src/features/knowledge-workspace/assistant/assistant-reducer.ts",
    import.meta.url,
  ))],
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  write: false,
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].contents).toString("base64")}`;
const { assistantReducer, initialAssistantState } = await import(moduleUrl);

function invocation(id, message, status = "running") {
  return {
    invocation_id: id,
    kind: "run",
    status,
    message,
    created_at: `2026-08-28T00:00:0${id.at(-1)}Z`,
    event_url: `/events/${id}`,
  };
}

function event(invocationId, id, cursor, type, data, parent_id) {
  return {
    id,
    cursor: String(cursor),
    type,
    invocation_id: invocationId,
    occurred_at: `2026-08-28T00:00:${String(cursor).padStart(2, "0")}Z`,
    ...(parent_id ? { parent_id } : {}),
    data,
  };
}

test("retains two messages and merges action observation by call_id during replay", () => {
  const firstEvents = [
    event("inv-1", "turn-1", 1, "turn.started", {
      turn_number: 1, title: "Turn 1", status: "running",
    }),
    event("inv-1", "action-1", 2, "activity.started", {
      activity_id: "call-1", activity_kind: "tool", call_id: "call-1",
      tool_name: "search", status: "running", input_summary: "query",
    }, "1"),
    event("inv-1", "observation-1", 3, "activity.completed", {
      activity_id: "call-1", activity_kind: "tool", call_id: "call-1",
      status: "succeeded", output_summary: "found",
      duration_ms: 12,
    }, "call-1"),
    event("inv-1", "final-1", 4, "assistant.final", { content: "# First" }),
  ];
  const state = assistantReducer(initialAssistantState, {
    type: "history.restored",
    entries: [
      { invocation: invocation("inv-1", "first"), events: firstEvents },
      {
        invocation: invocation("inv-2", "second", "succeeded"),
        events: [event("inv-2", "final-2", 1, "assistant.final", { content: "Second" })],
      },
    ],
  });
  const replayed = assistantReducer(state, {
    type: "event.received",
    event: firstEvents[2],
  });

  assert.deepEqual(replayed.turns.map((turn) => turn.userMessage), ["first", "second"]);
  assert.equal(replayed.turns[0].activities.length, 2);
  assert.equal(replayed.turns[0].activities[1].callId, "call-1");
  assert.equal(replayed.turns[0].activities[1].status, "succeeded");
  assert.equal(replayed.turns[0].activities[1].title, "search");
  assert.equal(replayed.turns[0].activities[1].startedAt, "2026-08-28T00:00:02Z");
  assert.equal(replayed.turns[0].activities[1].durationMs, 12);
  assert.equal(replayed.turns[0].activities[1].outputSummary, "found");
  assert.equal(replayed.turns[0].eventIds.length, 4);
  assert.equal(replayed.turns[0].assistantContent, "# First");
});

test("history restore replays completed invocation events before applying terminal state", () => {
  const events = [
    event("inv-1", "turn-1", 1, "turn.started", {
      turn_number: 1, title: "Restored turn", status: "running",
    }),
    event("inv-1", "final-1", 2, "assistant.final", {
      content: "# Restored answer",
    }),
  ];
  const state = assistantReducer(initialAssistantState, {
    type: "history.restored",
    entries: [{ invocation: invocation("inv-1", "question", "succeeded"), events }],
  });

  assert.equal(state.turns[0].status, "succeeded");
  assert.equal(state.turns[0].assistantContent, "# Restored answer");
  assert.equal(state.turns[0].activities[0].title, "Restored turn");
  assert.deepEqual(state.turns[0].eventIds, ["turn-1", "final-1"]);
});

test("derives tool duration from action and observation timestamps when provider omits it", () => {
  const events = [
    event("inv-1", "action-1", 2, "activity.started", {
      activity_id: "call-1", activity_kind: "tool", call_id: "call-1",
      tool_name: "search", status: "running",
    }),
    event("inv-1", "observation-1", 5, "activity.completed", {
      activity_id: "call-1", activity_kind: "tool", call_id: "call-1",
      status: "succeeded",
    }),
  ];
  const state = assistantReducer(initialAssistantState, {
    type: "history.restored",
    entries: [{ invocation: invocation("inv-1", "question"), events }],
  });

  assert.equal(state.turns[0].activities[0].durationMs, 3000);
});

test("state updates do not replace planning and terminal states retain partial content", () => {
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: invocation("inv-1", "question"),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "plan-1", 1, "activity.started", {
      activity_id: "plan-1", activity_kind: "planning", title: "Plan",
      status: "running", summary: "Safe plan", steps: [],
    }),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "state-1", 2, "state.updated", {
      state_ready: true, remote_saved: true,
    }),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "delta-1", 3, "assistant.delta", {
      text: "partial", sequence: 1,
    }),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "cancel-1", 4, "run.cancelled", {
      status: "cancelled", finished_at: "2026-08-28T00:00:04Z",
    }),
  });

  assert.equal(state.turns[0].activities[0].kind, "planning");
  assert.equal(state.turns[0].stateUpdate?.stateReady, true);
  assert.equal(state.turns[0].assistantContent, "partial");
  assert.equal(state.turns[0].status, "cancelled");
});

test("remote-only state updates do not invent a failed state_ready flag", () => {
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: invocation("inv-1", "question"),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "state-1", 1, "state.updated", {
      remote_saved: true,
    }),
  });

  assert.equal(state.turns[0].stateUpdate?.remoteSaved, true);
  assert.equal(state.turns[0].stateUpdate?.stateReady, undefined);
});

test("shows a submitted user turn immediately and reconciles the server invocation", () => {
  const optimistic = invocation("client-1", "new question", "queued");
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: optimistic,
  });
  assert.equal(state.turns[0].userMessage, "new question");

  state = assistantReducer(state, {
    type: "invocation.confirmed",
    optimisticId: "client-1",
    invocation: invocation("inv-3", "new question"),
  });
  assert.equal(state.turns.length, 1);
  assert.equal(state.turns[0].invocationId, "inv-3");
  assert.equal(state.turns[0].userMessage, "new question");
});

test("history restore does not overwrite a live invocation receiving events", () => {
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: invocation("inv-live", "live question"),
  });
  state = assistantReducer(state, {
    type: "connection.changed",
    invocationId: "inv-live",
    state: "connected",
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-live", "started", 1, "run.started", {
      kind: "run", status: "running",
    }),
  });

  state = assistantReducer(state, {
    type: "history.restored",
    entries: [{
      invocation: invocation("inv-live", "live question"),
      events: [],
    }],
  });

  assert.deepEqual(state.turns[0].eventIds, ["started"]);
  assert.equal(state.turns[0].connectionState, "connected");
  assert.equal(state.turns[0].status, "running");
});

test("normalizes modern event aliases, merges duplicate tool calls, and keeps late events after done from changing terminal state", () => {
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: invocation("inv-1", "question"),
  });

  for (const nextEvent of [
    event("inv-1", "tool-done-first", 3, "tool_output", {
      call_id: "call-a",
      name: "query_table",
      ok: true,
      output: { rows: 3, debug: { hidden: true } },
      duration_ms: 42,
    }),
    event("inv-1", "plan", 1, "planning", {
      summary: "Use the authorized connection, then render the real report.",
      steps: [{ id: "step-1", label: "读取真实数据", status: "completed" }],
    }),
    event("inv-1", "tool-start", 2, "tool_call", {
      call_id: "call-a",
      name: "query_table",
      input: { sql: "select * from sales" },
    }),
    event("inv-1", "delta", 4, "message.delta", { text: "hello", sequence: 1 }),
    event("inv-1", "done", 5, "done", { finished_at: "2026-08-28T00:00:05Z" }),
    event("inv-1", "late-error", 6, "error", {
      code: "MODEL_ERROR",
      message: "late provider duplicate",
      retryable: true,
      category: "model",
    }),
    event("inv-1", "tool-done-duplicate", 7, "tool_output", {
      call_id: "call-a",
      name: "query_table",
      ok: true,
      output_summary: "duplicate replay",
      duration_ms: 50,
    }),
  ]) {
    state = assistantReducer(state, { type: "event.received", event: nextEvent });
  }

  assert.equal(state.turns[0].status, "succeeded");
  assert.equal(state.turns[0].error, undefined);
  assert.equal(state.turns[0].assistantContent, "hello");
  assert.equal(state.turns[0].activities.length, 2);
  assert.equal(state.turns[0].activities[0].kind, "planning");
  assert.equal(state.turns[0].activities[0].steps[0].status, "completed");
  assert.equal(state.turns[0].activities[1].kind, "tool");
  assert.equal(state.turns[0].activities[1].callId, "call-a");
  assert.equal(state.turns[0].activities[1].status, "succeeded");
  assert.equal(state.turns[0].activities[1].durationMs, 42);
  assert.match(state.turns[0].activities[1].inputSummary, /select/);
  assert.match(state.turns[0].activities[1].outputSummary, /rows/);
});

test("tracks artifact preview snapshots without inventing final artifacts", () => {
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: invocation("inv-1", "question"),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "preview", 1, "artifact.preview", {
      artifact_id: "preview-1",
      revision_id: "rev-1",
      media_type: "text/html",
      sha256: "a".repeat(64),
      uri: "/api/knowledge/v1/artifact-snapshots/snapshot-1/content",
      title: "临时预览",
      source: "<!doctype html><html><body>real</body></html>",
      log: "validated preview snapshot",
    }),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "blocked", 2, "artifact.preview", {
      status: "blocked",
      message: "AutoSkill has not emitted a complete legal HTML snapshot.",
      log: ["blocked"],
    }),
  });

  assert.equal(state.turns[0].artifactPreview.status, "blocked");
  assert.equal(state.turns[0].artifactPreview.artifactId, "preview-1");
  assert.equal(state.turns[0].artifactPreview.revisionId, "rev-1");
  assert.equal(state.turns[0].artifactPreview.uri, "/api/knowledge/v1/artifact-snapshots/snapshot-1/content");
  assert.match(state.turns[0].artifactPreview.source, /real/);
  assert.deepEqual(state.turns[0].artifactPreview.log, [
    "validated preview snapshot",
    "blocked",
  ]);

  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "final", 3, "artifact.final", {
      artifact_id: "artifact-final",
      revision_id: "rev-2",
      media_type: "text/html",
      sha256: "b".repeat(64),
      uri: "/api/knowledge/v1/artifacts/artifact-final/content",
      title: "最终产物",
    }),
  });

  assert.equal(state.turns[0].artifactPreview.status, "final");
  assert.equal(state.turns[0].artifactPreview.artifactId, "artifact-final");
  assert.equal(state.turns[0].artifactPreview.sha256, "b".repeat(64));
});

test("keeps immutable final artifact ahead of late preview replay", () => {
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: invocation("inv-1", "question"),
  });

  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "final", 1, "artifact.final", {
      artifact_id: "artifact-final",
      revision_id: "rev-final",
      media_type: "text/html",
      sha256: "f".repeat(64),
      uri: "/api/knowledge/v1/artifacts/artifact-final/content",
      title: "最终产物",
      log: "immutable final artifact recorded",
    }),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "late-preview", 2, "artifact.preview", {
      artifact_id: "snapshot-late",
      snapshot_id: "snapshot-late",
      revision_id: "rev-old",
      media_type: "text/html",
      sha256: "p".repeat(64),
      uri: "/api/knowledge/v1/artifact-snapshots/snapshot-late/content",
      title: "迟到预览",
      status: "preview",
      log: "late preview replayed",
    }),
  });

  assert.equal(state.turns[0].artifactPreview.status, "final");
  assert.equal(state.turns[0].artifactPreview.artifactId, "artifact-final");
  assert.equal(state.turns[0].artifactPreview.revisionId, "rev-final");
  assert.equal(state.turns[0].artifactPreview.uri, "/api/knowledge/v1/artifacts/artifact-final/content");
  assert.equal(state.turns[0].artifactPreview.sha256, "f".repeat(64));
  assert.deepEqual(state.turns[0].artifactPreview.log, [
    "immutable final artifact recorded",
    "late preview replayed",
  ]);
});

test("artifact.created after artifact.final only appends evidence without losing final uri", () => {
  let state = assistantReducer(initialAssistantState, {
    type: "invocation.started",
    invocation: invocation("inv-1", "question"),
  });

  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "final", 1, "artifact.final", {
      artifact_id: "artifact-final",
      revision_id: "rev-final",
      media_type: "text/html",
      sha256: "f".repeat(64),
      uri: "/api/knowledge/v1/artifacts/artifact-final/content",
      title: "最终产物",
      source: "{\"lineage\":\"final\"}",
      log: "immutable final artifact recorded",
    }),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "created", 2, "artifact.created", {
      artifact_id: "artifact-final",
      revision_id: "rev-final",
      media_type: "text/html",
      sha256: "f".repeat(64),
      title: "最终产物",
    }),
  });
  state = assistantReducer(state, {
    type: "event.received",
    event: event("inv-1", "late-preview", 3, "artifact.preview", {
      snapshot_id: "snapshot-late",
      revision_id: "rev-preview",
      media_type: "text/html",
      uri: "/api/knowledge/v1/artifact-snapshots/snapshot-late/content",
      source: "<!doctype html><html><body>late</body></html>",
      log: "late preview replayed",
    }),
  });

  assert.equal(state.turns[0].artifactPreview.status, "final");
  assert.equal(state.turns[0].artifactPreview.artifactId, "artifact-final");
  assert.equal(state.turns[0].artifactPreview.uri, "/api/knowledge/v1/artifacts/artifact-final/content");
  assert.equal(state.turns[0].artifactPreview.source, "{\"lineage\":\"final\"}");
  assert.deepEqual(state.turns[0].artifactPreview.log, [
    "immutable final artifact recorded",
    "final artifact artifact-final recorded",
    "late preview replayed",
  ]);
});
