export type ConnectorStatus = "catalog" | "beta" | "verified";
export type ConnectionScope = "personal" | "team";
export type ConnectionStatus =
  | "draft"
  | "validating"
  | "ready"
  | "degraded"
  | "error"
  | "revoked";
export type DraftLifecycle =
  | "editing"
  | "generating"
  | "generated"
  | "validating"
  | "ready_to_publish"
  | "published"
  | "failed"
  | "cancelled";
export type InvocationStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Meta {
  request_id: string;
  next_cursor?: string;
  has_more?: boolean;
}

export interface ConnectorDefinition {
  connector_key: string;
  version: string;
  display_name: string;
  category?: string;
  status: ConnectorStatus;
  capabilities: string[];
  config_schema: JsonObject;
  auth_schema: JsonObject;
  endpoints?: string[];
}

export interface ConnectionProfile {
  connection_id: string;
  connector_key: string;
  display_name: string;
  scope: ConnectionScope;
  status: ConnectionStatus;
  definition_version: string;
  profile?: JsonObject;
  last_validated_at?: string;
  created_at: string;
  updated_at: string;
}

export type WorkspaceResourceKind =
  | "oracle_database"
  | "rest_openapi"
  | "mcp"
  | "files";

export interface WorkspaceResource {
  resource_id: string;
  kind: WorkspaceResourceKind;
  display_name: string;
  scope: ConnectionScope;
  status: "beta" | "verified" | "dev" | "error";
  metadata?: JsonObject;
  created_at: string;
  updated_at: string;
}

export interface Draft {
  draft_id: string;
  goal: string;
  trial_task?: string;
  connection_ids: string[];
  resource_ids: string[];
  lifecycle: DraftLifecycle;
  current_revision_id?: string;
  active_invocation_id?: string;
  created_at: string;
  updated_at: string;
}

export interface Invocation {
  invocation_id: string;
  kind: "generate" | "update" | "run" | "validate" | "discover";
  status: InvocationStatus;
  message: string;
  model?: string;
  event_url: string;
  started_at?: string;
  finished_at?: string;
  created_at: string;
}

export interface Revision {
  revision_id: string;
  draft_id: string;
  number: number;
  skill_name: string;
  sha256: string;
  manifest?: JsonObject;
  created_from_invocation?: string;
  created_at: string;
}

export interface Artifact {
  artifact_id: string;
  revision_id: string;
  invocation_id: string;
  media_type: string;
  uri?: string;
  sha256: string;
  title?: string;
  lineage?: JsonObject;
  created_at: string;
}

export interface Publication {
  publication_id: string;
  revision_id: string;
  target_space: "personal" | "team";
  status: "published" | "revoked";
  agent_grants?: string[];
  created_at: string;
}

export interface JsonObject {
  [key: string]: JsonValue;
}

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | JsonObject;

export interface PlanStep {
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
}

interface InvocationEventBase {
  id: string;
  cursor: string;
  invocation_id: string;
  occurred_at: string;
  parent_id?: string;
}

export type KnowledgeInvocationEvent = InvocationEventBase & (
  | {
      type: "run.started";
      data: {
        kind: "generate" | "update" | "run" | "validate" | "discover";
        status: "running";
        draft_id?: string;
        revision_id?: string;
      };
    }
  | {
      type: "assistant.delta";
      data: { text: string; sequence: number; final?: boolean };
    }
  | {
      type: "assistant.progress";
      data: { text: string };
    }
  | {
      type: "assistant.final";
      data: { content: string };
    }
  | {
      type: "plan.updated";
      data: { steps: PlanStep[]; summary?: string };
    }
  | {
      type: "tool.started" | "tool.completed";
      data: {
        tool_call_id: string;
        tool_name: string;
        connection_id?: string;
        connection_alias?: string;
        input_summary?: string;
        status?: "succeeded" | "failed" | "cancelled";
        duration_ms?: number;
        output_summary?: string;
        error_code?: string;
      };
    }
  | {
      type: "turn.started";
      data: {
        turn_number: number;
        title: string;
        status: "running";
      };
    }
  | {
      type: "activity.started" | "activity.completed";
      data: {
        activity_id: string;
        activity_kind: "planning" | "tool";
        title?: string;
        status: "running" | "succeeded" | "failed" | "cancelled";
        call_id?: string;
        tool_name?: string;
        summary?: string;
        input_summary?: string;
        output_summary?: string;
        error_summary?: string;
        duration_ms?: number;
        steps?: PlanStep[];
      };
    }
  | {
      type: "request.summary";
      data: {
        status?: string;
        model?: string;
        skills: { used: number; created: number; updated: number };
        usage?: JsonObject;
        message?: string;
      };
    }
  | {
      type: "state.updated";
      data: {
        state_ready?: boolean;
        remote_saved?: boolean;
        error_summary?: string;
      };
    }
  | {
      type: "artifact.created";
      data: {
        artifact_id: string;
        revision_id: string;
        media_type: string;
        sha256: string;
        title?: string;
        lineage?: JsonObject;
      };
    }
  | {
      type: "revision.created";
      data: {
        revision_id: string;
        draft_id: string;
        number: number;
        sha256: string;
        skill_name?: string;
      };
    }
  | {
      type: "run.completed";
      data: {
        status: "succeeded";
        finished_at: string;
        request_summary?: JsonObject;
        artifact_ids?: string[];
        revision_id?: string;
      };
    }
  | {
      type: "run.failed";
      data: {
        status: "failed";
        error: InvocationError;
        finished_at?: string;
      };
    }
  | {
      type: "run.cancelled";
      data: { status: "cancelled"; finished_at?: string };
    }
);

export interface ConversationHistoryEntry {
  invocation: Invocation;
  events: KnowledgeInvocationEvent[];
}

export interface InvocationError {
  code: string;
  message: string;
  retryable: boolean;
  details?: JsonObject;
}

export interface ArchivedInvocationEvent {
  id: string;
  type: string;
  invocation_id: string;
  occurred_at: string;
  data: JsonObject;
}
