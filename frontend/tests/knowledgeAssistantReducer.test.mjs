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
      tool_name: "search", status: "succeeded", output_summary: "found",
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
  assert.equal(replayed.turns[0].activities[1].outputSummary, "found");
  assert.equal(replayed.turns[0].eventIds.length, 4);
  assert.equal(replayed.turns[0].assistantContent, "# First");
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
