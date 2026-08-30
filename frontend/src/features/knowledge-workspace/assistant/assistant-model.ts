import type {
  ArchivedInvocationEvent,
  Invocation,
  InvocationStatus,
  JsonObject,
  KnowledgeInvocationEvent,
  PlanStep,
} from "../domain/types";

export type ActivityStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface AssistantActivity {
  id: string;
  kind: "turn" | "planning" | "action" | "tool" | "observation" | "progress";
  title: string;
  status: ActivityStatus;
  parentId?: string;
  callId?: string;
  startedAt: string;
  completedAt?: string;
  durationMs?: number;
  summary?: string;
  inputSummary?: string;
  outputSummary?: string;
  errorSummary?: string;
  steps?: PlanStep[];
}

export interface AssistantArtifactPreview {
  artifactId?: string;
  revisionId?: string;
  title?: string;
  mediaType?: string;
  sha256?: string;
  uri?: string;
  csp?: string;
  sandbox?: string;
  status: "pending" | "preview" | "final" | "blocked" | "error";
  message?: string;
  source?: string;
  log: string[];
  updatedAt: string;
}

export interface RequestSummary {
  status?: string;
  model?: string;
  skills: {
    used: number;
    created: number;
    updated: number;
  };
  usage?: JsonObject;
  message?: string;
}

export interface ConversationTurnModel {
  invocation: Invocation;
  invocationId: string;
  userMessage: string;
  activities: AssistantActivity[];
  assistantContent: string;
  requestSummary?: RequestSummary;
  error?: { code: string; message: string; retryable: boolean; category?: string };
  artifactPreview?: AssistantArtifactPreview;
  stateUpdate?: {
    stateReady?: boolean;
    remoteSaved?: boolean;
    errorSummary?: string;
  };
  status: InvocationStatus;
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  lastCursor?: string;
  eventIds: string[];
  unknownEvents: ArchivedInvocationEvent[];
  connectionState: "idle" | "connected" | "disconnected";
  retryOf?: string;
}

export interface AssistantState {
  turns: ConversationTurnModel[];
}

export interface ConversationHistoryEntry {
  invocation: Invocation;
  events: KnowledgeInvocationEvent[];
}

export function emptyTurn(invocation: Invocation): ConversationTurnModel {
  return {
    invocation,
    invocationId: invocation.invocation_id,
    userMessage: invocation.message,
    activities: [],
    assistantContent: "",
    status: invocation.status,
    createdAt: invocation.created_at,
    startedAt: invocation.started_at,
    finishedAt: invocation.finished_at,
    eventIds: [],
    unknownEvents: [],
    connectionState: "idle",
  };
}
