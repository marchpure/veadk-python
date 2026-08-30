import type {
  ArchivedInvocationEvent,
  Invocation,
  KnowledgeInvocationEvent,
} from "../domain/types";
import {
  emptyTurn,
  type AssistantActivity,
  type AssistantArtifactPreview,
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
      error: { code: string; message: string; retryable: boolean; category?: string };
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

const TERMINAL_STATUSES = new Set<ConversationTurnModel["status"]>([
  "succeeded",
  "failed",
  "cancelled",
]);

function summarize(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (value === undefined || value === null) return fallback;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return fallback;
  }
}

function textFromData(data: Record<string, unknown>): string {
  return String(data.text ?? data.message ?? data.stage ?? "");
}

function normalizeStatus(
  value: unknown,
  fallback: AssistantActivity["status"] = "running",
): AssistantActivity["status"] {
  const status = String(value || "").toLowerCase();
  if (status === "success" || status === "ok" || status === "completed" || status === "complete" || status === "done") return "succeeded";
  if (status === "failed" || status === "failure" || status === "error") return "failed";
  if (status === "cancelled" || status === "canceled") return "cancelled";
  if (status === "pending" || status === "queued") return "pending";
  if (status === "running" || status === "started" || status === "start") return "running";
  return fallback;
}

function normalizeToolCallId(data: Record<string, unknown>, fallback: string): string {
  return String(data.call_id || data.tool_call_id || data.id || fallback);
}

function normalizeToolName(data: Record<string, unknown>, fallback: string): string {
  return String(data.tool_name || data.name || data.tool || fallback);
}

function artifactLog(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value === "string" && value.trim()) return [value];
  return [];
}

function sortActivities(activities: AssistantActivity[]): AssistantActivity[] {
  return [...activities].sort((left, right) => {
    const leftTime = Date.parse(left.startedAt);
    const rightTime = Date.parse(right.startedAt);
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return 0;
  });
}

function activityFromEvent(event: KnowledgeInvocationEvent): AssistantActivity | undefined {
  if (event.type === "planning") {
    return {
      id: event.id,
      kind: "planning",
      title: "规划",
      status: normalizeStatus(event.data.status, "running"),
      summary: "summary" in event.data ? event.data.summary : undefined,
      steps: Array.isArray(event.data.steps) ? event.data.steps : [],
      startedAt: event.occurred_at,
      parentId: event.parent_id,
    };
  }
  if (event.type === "plan.updated") {
    return {
      id: event.id,
      kind: "planning",
      title: "规划",
      status: "running",
      summary: event.data.summary,
      steps: event.data.steps,
      startedAt: event.occurred_at,
      parentId: event.parent_id,
    };
  }
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
  if (event.type === "assistant.progress" || event.type === "progress") {
    return {
      id: event.id,
      kind: "progress",
      title: "进度",
      status: "running",
      summary: textFromData(event.data),
      startedAt: event.occurred_at,
      parentId: event.parent_id,
    };
  }
  if (event.type === "tool.started") {
    return {
      id: event.data.tool_call_id,
      kind: "tool",
      title: event.data.tool_name,
      status: normalizeStatus(event.data.status, "running"),
      startedAt: event.occurred_at,
      parentId: event.parent_id,
      callId: event.data.tool_call_id,
      inputSummary: event.data.input_summary,
    };
  }
  if (event.type === "tool_call" || event.type === "action") {
    const data = event.data as Record<string, unknown>;
    const callId = normalizeToolCallId(data, event.id);
    return {
      id: callId,
      kind: event.type === "action" ? "action" : "tool",
      title: normalizeToolName(data, "工具调用"),
      status: normalizeStatus(data.status, "running"),
      startedAt: event.occurred_at,
      parentId: event.parent_id,
      callId,
      inputSummary: summarize(data.input_summary || data.input || data.arguments),
    };
  }
  if (event.type === "tool.completed") {
    return {
      id: event.data.tool_call_id,
      kind: "tool",
      title: event.data.tool_name,
      status: normalizeStatus(event.data.status, event.data.status || "succeeded"),
      startedAt: event.occurred_at,
      completedAt: event.occurred_at,
      parentId: event.parent_id,
      callId: event.data.tool_call_id,
      durationMs: event.data.duration_ms,
      outputSummary: event.data.output_summary,
      errorSummary: event.data.error_code,
    };
  }
  if (event.type === "tool_output" || event.type === "observation") {
    const data = event.data as Record<string, unknown>;
    const callId = normalizeToolCallId(data, event.parent_id || event.id);
    const failed = data.ok === false || Boolean(data.error);
    return {
      id: callId,
      kind: event.type === "observation" ? "observation" : "tool",
      title: normalizeToolName(data, "工具结果"),
      status: failed ? "failed" : normalizeStatus(data.status, "succeeded"),
      startedAt: event.occurred_at,
      completedAt: event.occurred_at,
      parentId: event.parent_id,
      callId,
      durationMs: typeof data.duration_ms === "number" ? data.duration_ms : undefined,
      outputSummary: summarize(data.output_summary || data.output),
      errorSummary: summarize(data.error_summary || data.error),
    };
  }
  if (event.type !== "activity.started" && event.type !== "activity.completed") {
    return undefined;
  }
  const completed = event.type === "activity.completed";
  return {
    id: event.data.activity_id,
    kind: event.data.activity_kind,
    title: event.data.title || event.data.tool_name || "执行活动",
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

function artifactPreviewFromEvent(
  current: AssistantArtifactPreview | undefined,
  event: KnowledgeInvocationEvent,
): AssistantArtifactPreview | undefined {
  if (event.type === "artifact.created") {
    const log = [
      ...(current?.log || []),
      `final artifact ${event.data.artifact_id} recorded`,
    ];
    if (current?.status === "final") {
      return {
        ...current,
        artifactId: current.artifactId || event.data.artifact_id,
        revisionId: current.revisionId || event.data.revision_id,
        mediaType: current.mediaType || event.data.media_type,
        sha256: current.sha256 || event.data.sha256,
        title: current.title || event.data.title,
        log,
        updatedAt: event.occurred_at,
      };
    }
    return {
      artifactId: event.data.artifact_id,
      revisionId: event.data.revision_id,
      mediaType: event.data.media_type,
      sha256: event.data.sha256,
      title: event.data.title,
      csp: undefined,
      sandbox: undefined,
      status: event.data.media_type === "text/html" ? "final" : "blocked",
      message: event.data.media_type === "text/html"
        ? "Immutable HTML Artifact is ready."
        : "Artifact is not renderable HTML.",
      log,
      updatedAt: event.occurred_at,
    };
  }
  if (event.type !== "artifact.preview" && event.type !== "artifact.final") {
    return current;
  }
  const data = event.data;
  const nextLog = [...(current?.log || []), ...artifactLog(data.log)];
  if (current?.status === "final" && event.type === "artifact.preview") {
    return {
      ...current,
      log: nextLog,
      updatedAt: event.occurred_at,
    };
  }
  const status = event.type === "artifact.final"
    ? "final"
    : data.status || "preview";
  return {
    artifactId: data.artifact_id || data.snapshot_id || current?.artifactId,
    revisionId: data.revision_id || current?.revisionId,
    mediaType: data.media_type || current?.mediaType,
    sha256: data.sha256 || current?.sha256,
    title: data.title || current?.title,
    uri: data.uri || current?.uri,
    csp: data.csp || current?.csp,
    sandbox: data.sandbox || current?.sandbox,
    status,
    message: data.message || current?.message,
    source: data.source || current?.source,
    log: nextLog,
    updatedAt: event.occurred_at,
  };
}

function mergeActivity(
  activities: AssistantActivity[],
  incoming: AssistantActivity,
): AssistantActivity[] {
  const key = incoming.callId || incoming.id;
  const index = activities.findIndex((activity) => (activity.callId || activity.id) === key);
  if (index < 0) return sortActivities([...activities, incoming]);
  const current = activities[index];
  const currentIsTerminal = current.status !== "running" && current.status !== "pending";
  const incomingIsStart = incoming.status === "running" || incoming.status === "pending";
  const derivedDuration = incoming.durationMs ?? (
    incoming.completedAt
      ? Math.max(0, Date.parse(incoming.completedAt) - Date.parse(current.startedAt))
      : undefined
  );
  const next = [...activities];
  next[index] = {
    ...current,
    ...incoming,
    status: currentIsTerminal && incomingIsStart ? current.status : incoming.status,
    startedAt: Date.parse(incoming.startedAt) < Date.parse(current.startedAt)
      ? incoming.startedAt
      : current.startedAt,
    completedAt: current.completedAt || incoming.completedAt,
    title: incoming.title === "执行活动" ? current.title : incoming.title,
    inputSummary: current.inputSummary || incoming.inputSummary,
    outputSummary: current.outputSummary || incoming.outputSummary,
    errorSummary: current.errorSummary || incoming.errorSummary,
    durationMs: current.durationMs ?? derivedDuration,
  };
  return sortActivities(next);
}

function applyEvent(turn: ConversationTurnModel, event: KnowledgeInvocationEvent): ConversationTurnModel {
  if (turn.eventIds.includes(event.id)) return turn;
  if (
    TERMINAL_STATUSES.has(turn.status) &&
    event.type !== "artifact.created" &&
    event.type !== "artifact.final" &&
    event.type !== "artifact.preview" &&
    event.type !== "revision.created"
  ) {
    return {
      ...turn,
      eventIds: [...turn.eventIds, event.id],
      lastCursor: event.cursor,
    };
  }
  const next: ConversationTurnModel = {
    ...turn,
    eventIds: [...turn.eventIds, event.id],
    lastCursor: event.cursor,
  };
  const activity = activityFromEvent(event);
  if (activity) next.activities = mergeActivity(turn.activities, activity);
  const artifactPreview = artifactPreviewFromEvent(turn.artifactPreview, event);
  if (artifactPreview !== turn.artifactPreview) next.artifactPreview = artifactPreview;
  if (event.type === "assistant.delta" || event.type === "message.delta") {
    next.assistantContent += event.data.text;
  } else if (event.type === "assistant.final") {
    next.assistantContent = event.data.content;
  } else if (event.type === "request.summary") {
    next.requestSummary = event.data as RequestSummary;
  } else if (event.type === "state.updated" || event.type === "state") {
    next.stateUpdate = {
      stateReady: event.data.state_ready,
      remoteSaved: event.data.remote_saved,
      errorSummary: event.data.error_summary,
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
  } else if (event.type === "done") {
    next.status = "succeeded";
    next.finishedAt = event.data.finished_at || event.occurred_at;
    next.connectionState = "idle";
    next.activities = next.activities.map((item) =>
      item.status === "running"
        ? { ...item, status: "succeeded", completedAt: next.finishedAt }
        : item);
  } else if (event.type === "error") {
    next.status = "failed";
    next.error = {
      code: event.data.code || "UNKNOWN",
      message: event.data.message || "运行失败",
      retryable: event.data.retryable !== false,
      category: event.data.category,
    };
    next.finishedAt = event.occurred_at;
    next.connectionState = "idle";
    next.activities = next.activities.map((item) =>
      item.status === "running"
        ? { ...item, status: "failed", completedAt: next.finishedAt }
        : item);
  }
  return next;
}

function restoreEntry(entry: ConversationHistoryEntry): ConversationTurnModel {
  const replayInvocation = TERMINAL_STATUSES.has(entry.invocation.status)
    ? {
      ...entry.invocation,
      status: "running" as const,
      finished_at: undefined,
    }
    : entry.invocation;
  const restored = entry.events.reduce(applyEvent, emptyTurn(replayInvocation));
  return {
    ...restored,
    invocation: entry.invocation,
    status: restored.status === "running" ? entry.invocation.status : restored.status,
    finishedAt: restored.finishedAt || entry.invocation.finished_at,
  };
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
    const restored = action.entries.map(restoreEntry);
    const restoredById = new Map(restored.map((turn) => [turn.invocationId, turn]));
    const merged = state.turns.map((current) => {
      const restoredTurn = restoredById.get(current.invocationId);
      if (!restoredTurn) return current;
      const hasLiveState =
        current.eventIds.length > 0
        || current.connectionState !== "idle"
        || current.status !== current.invocation.status;
      return hasLiveState
        ? {
          ...current,
          invocation: restoredTurn.invocation,
          userMessage: restoredTurn.userMessage,
        }
        : restoredTurn;
    });
    const currentIds = new Set(state.turns.map((turn) => turn.invocationId));
    return {
      turns: [
        ...merged,
        ...restored.filter((turn) => !currentIds.has(turn.invocationId)),
      ],
    };
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
