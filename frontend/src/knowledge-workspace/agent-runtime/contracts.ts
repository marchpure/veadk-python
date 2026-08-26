export type AgentEventType =
  | "message.accepted"
  | "context.resolving"
  | "context.resolved"
  | "agent.started"
  | "answer.delta"
  | "answer.final"
  | "tool.started"
  | "tool.progress"
  | "tool.completed"
  | "tool.failed"
  | "plan.created"
  | "plan.step.started"
  | "plan.step.completed"
  | "plan.step.failed"
  | "artifact.revision.created"
  | "operation.completed"
  | "operation.failed"
  | "operation.cancelled";

export type ToolStatus = "running" | "completed" | "failed";
export type ToolCategory =
  | "database"
  | "mcp"
  | "connector"
  | "retrieval"
  | "skill"
  | "artifact"
  | "generic";

export interface AuthoringEvent {
  cursor: string;
  operation_id: string;
  event_id: string;
  sequence: number;
  event_type: AgentEventType;
  type: AgentEventType;
  session_id?: string | null;
  trace_id?: string | null;
  public_summary: string;
  payload: Record<string, unknown>;
  terminal: boolean;
  occurred_at: string;
}

export interface ToolActivity {
  id: string;
  name: string;
  category: ToolCategory;
  status: ToolStatus;
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  inputSummary?: string;
  outputSummary?: string;
  error?: string;
  recoveryHint?: string;
  sessionId?: string;
  traceId?: string;
}

export interface PlanStep {
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed";
}

export interface TimelineState {
  operationId: string;
  userPrompt?: string;
  events: AuthoringEvent[];
  seenEventIds: ReadonlySet<string>;
  lastEventId?: string;
  answerText: string;
  finalAnswer?: string;
  tools: ToolActivity[];
  plan: PlanStep[];
  artifacts: ArtifactRevision[];
  status:
    | "idle"
    | "connecting"
    | "running"
    | "reconnecting"
    | "stopping"
    | "completed"
    | "awaiting_input"
    | "failed"
    | "cancelled"
    | "disconnected";
  warning?: string;
  error?: RuntimeErrorState;
}

export interface AuthoringStreamOptions {
  baseUrl?: string;
  signal?: AbortSignal;
  lastEventId?: string;
  requestId?: string;
}

export interface ResourceReference {
  kind: string;
  objectId: string;
  revision: string;
  scope?: "personal" | "team";
}

export interface StartAuthoringInput {
  prompt: string;
  conversationId?: string;
  resourceRefs?: ResourceReference[];
  permissions?: string[];
  fixedRevisions?: string[];
  requestedKind?:
    | "knowledge"
    | "semantic"
    | "analysis"
    | "sop"
    | "graph_ontology"
    | "monitoring";
  scope?: "personal" | "team";
  displayName?: string;
  currentSkillId?: string;
  currentViewId?: string;
  currentComponentId?: string;
  commentIds?: string[];
  templateRef?: {
    templateId: string;
    version: string;
    digest: string;
  };
}

export interface StartedAuthoringOperation {
  operationId: string;
  events: AsyncGenerator<AuthoringEvent>;
}

export interface ArtifactRevision {
  id: string;
  revision?: number;
  label: string;
  uri?: string;
  baseRevision?: number;
  baseDigest?: string;
  newDigest?: string;
  viewRevisionId?: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
}

export interface RuntimeErrorState {
  code: string;
  message: string;
  retryable: boolean;
  kind: "network" | "authentication" | "runner" | "protocol";
  requestId?: string;
}

export interface AgentTimelineProps {
  state: TimelineState;
  onStop?: () => void;
  onRetry?: () => void;
  onResume?: () => void;
  className?: string;
}

export interface AgentRuntimeContext
  extends Omit<StartAuthoringInput, "prompt"> {}
