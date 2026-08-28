import type {
  ArchivedInvocationEvent,
  Invocation,
  KnowledgeInvocationEvent,
} from "../domain/types";
import {
  emptyTurn,
  type AssistantActivity,
  type AssistantState,
  type ConversationHistoryEntry,
  type ConversationTurnModel,
  type RequestSummary,
} from "./assistant-model";

export const initialAssistantState: AssistantState = { turns: [] };

export type AssistantAction =
  | { type: "history.restored"; entries: ConversationHistoryEntry[] }
  | { type: "invocation.started"; invocation: Invocation; retryOf?: string }
  | {
      type: "invocation.confirmed";
      optimisticId: string;
      invocation: Invocation;
      retryOf?: string;
    }
  | {
      type: "invocation.rejected";
      invocationId: string;
      error: { code: string; message: string; retryable: boolean };
    }
  | {
      type: "invocation.cancelled";
      invocationId: string;
      finishedAt: string;
    }
  | { type: "event.received"; event: KnowledgeInvocationEvent }
  | {
      type: "connection.changed";
      invocationId: string;
      state: ConversationTurnModel["connectionState"];
    }
  | { type: "unknown.received"; invocationId: string; event: ArchivedInvocationEvent };

function activityFromEvent(event: KnowledgeInvocationEvent): AssistantActivity | undefined {
  if (event.type === "turn.started") {
    return {
      id: event.id,
      kind: "turn",
      title: event.data.title,
      status: "running",
      startedAt: event.occurred_at,
      parentId: event.parent_id,
    };
  }
  if (event.type === "assistant.progress") {
    return {
      id: event.id,
      kind: "progress",
      title: "进度",
      status: "running",
      summary: event.data.text,
      startedAt: event.occurred_at,
      parentId: event.parent_id,
    };
  }
  if (event.type !== "activity.started" && event.type !== "activity.completed") {
    return undefined;
  }
  const completed = event.type === "activity.completed";
  return {
    id: event.data.activity_id,
    kind: event.data.activity_kind,
    title: event.data.title || event.data.tool_name || "执行步骤",
    status: completed ? event.data.status : "running",
    startedAt: event.occurred_at,
    ...(completed ? { completedAt: event.occurred_at } : {}),
    parentId: event.parent_id,
    callId: event.data.call_id,
    durationMs: event.data.duration_ms,
    summary: event.data.summary,
    inputSummary: event.data.input_summary,
    outputSummary: event.data.output_summary,
    errorSummary: event.data.error_summary,
    steps: event.data.steps,
  };
}

function mergeActivity(
  activities: AssistantActivity[],
  incoming: AssistantActivity,
): AssistantActivity[] {
  const key = incoming.callId || incoming.id;
  const index = activities.findIndex((activity) => (activity.callId || activity.id) === key);
  if (index < 0) return [...activities, incoming];
  const current = activities[index];
  const next = [...activities];
  next[index] = {
    ...current,
    ...incoming,
    startedAt: current.startedAt,
    inputSummary: current.inputSummary || incoming.inputSummary,
  };
  return next;
}

function applyEvent(turn: ConversationTurnModel, event: KnowledgeInvocationEvent): ConversationTurnModel {
  if (turn.eventIds.includes(event.id)) return turn;
  const next: ConversationTurnModel = {
    ...turn,
    eventIds: [...turn.eventIds, event.id],
    lastCursor: event.cursor,
  };
  const activity = activityFromEvent(event);
  if (activity) next.activities = mergeActivity(turn.activities, activity);
  if (event.type === "assistant.delta") {
    next.assistantContent += event.data.text;
  } else if (event.type === "assistant.final") {
    next.assistantContent = event.data.content;
  } else if (event.type === "request.summary") {
    next.requestSummary = event.data as RequestSummary;
  } else if (event.type === "state.updated") {
    next.stateUpdate = {
      stateReady: event.data.state_ready,
      remoteSaved: event.data.remote_saved,
    };
  } else if (event.type === "run.started") {
    next.status = "running";
    next.startedAt = event.occurred_at;
  } else if (event.type === "run.completed") {
    next.status = "succeeded";
    next.finishedAt = event.data.finished_at;
    next.connectionState = "idle";
    next.activities = next.activities.map((item) =>
      item.status === "running"
        ? { ...item, status: "succeeded", completedAt: event.data.finished_at }
        : item);
  } else if (event.type === "run.failed") {
    next.status = "failed";
    next.error = event.data.error;
    next.finishedAt = event.data.finished_at || event.occurred_at;
    next.connectionState = "idle";
    next.activities = next.activities.map((item) =>
      item.status === "running"
        ? { ...item, status: "failed", completedAt: next.finishedAt }
        : item);
  } else if (event.type === "run.cancelled") {
    next.status = "cancelled";
    next.finishedAt = event.data.finished_at || event.occurred_at;
    next.connectionState = "idle";
    next.activities = next.activities.map((item) =>
      item.status === "running"
        ? { ...item, status: "cancelled", completedAt: next.finishedAt }
        : item);
  }
  return next;
}

function restoreEntry(entry: ConversationHistoryEntry): ConversationTurnModel {
  return entry.events.reduce(applyEvent, emptyTurn(entry.invocation));
}

function updateTurn(
  state: AssistantState,
  invocationId: string,
  update: (turn: ConversationTurnModel) => ConversationTurnModel,
): AssistantState {
  return {
    turns: state.turns.map((turn) =>
      turn.invocationId === invocationId ? update(turn) : turn),
  };
}

export function assistantReducer(
  state: AssistantState,
  action: AssistantAction,
): AssistantState {
  if (action.type === "history.restored") {
    return { turns: action.entries.map(restoreEntry) };
  }
  if (action.type === "invocation.started") {
    const existing = state.turns.findIndex(
      (turn) => turn.invocationId === action.invocation.invocation_id,
    );
    if (existing >= 0) return state;
    return {
      turns: [
        ...state.turns,
        { ...emptyTurn(action.invocation), retryOf: action.retryOf },
      ],
    };
  }
  if (action.type === "invocation.confirmed") {
    const optimistic = state.turns.find(
      (turn) => turn.invocationId === action.optimisticId,
    );
    const confirmed = {
      ...(optimistic || emptyTurn(action.invocation)),
      invocation: action.invocation,
      invocationId: action.invocation.invocation_id,
      status: action.invocation.status,
      createdAt: action.invocation.created_at,
      startedAt: action.invocation.started_at,
      retryOf: action.retryOf,
    };
    return {
      turns: [
        ...state.turns.filter(
          (turn) =>
            turn.invocationId !== action.optimisticId
            && turn.invocationId !== action.invocation.invocation_id,
        ),
        confirmed,
      ],
    };
  }
  if (action.type === "invocation.rejected") {
    return updateTurn(state, action.invocationId, (turn) => ({
      ...turn,
      status: "failed",
      finishedAt: new Date().toISOString(),
      error: action.error,
    }));
  }
  if (action.type === "invocation.cancelled") {
    return updateTurn(state, action.invocationId, (turn) => ({
      ...turn,
      status: "cancelled",
      finishedAt: action.finishedAt,
      connectionState: "idle",
      activities: turn.activities.map((item) =>
        item.status === "running"
          ? { ...item, status: "cancelled", completedAt: action.finishedAt }
          : item),
    }));
  }
  if (action.type === "event.received") {
    return updateTurn(state, action.event.invocation_id, (turn) => applyEvent(turn, action.event));
  }
  if (action.type === "connection.changed") {
    return updateTurn(state, action.invocationId, (turn) => ({
      ...turn,
      connectionState: action.state,
    }));
  }
  return updateTurn(state, action.invocationId, (turn) => {
    if (turn.unknownEvents.some((event) => event.id === action.event.id)) return turn;
    return { ...turn, unknownEvents: [...turn.unknownEvents, action.event] };
  });
}
