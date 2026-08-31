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
export type AuthoringSessionStatus = "idle" | "running" | "archived";
export type TemplateKey = "generic" | "semantic" | "dashboard" | "sop";

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

export type WorkspaceResourceStatus = "beta" | "verified" | "dev" | "error";

export interface WorkspaceResource {
  resource_id: string;
  kind: WorkspaceResourceKind;
  display_name: string;
  scope: ConnectionScope;
  status: WorkspaceResourceStatus;
  metadata?: JsonObject;
  created_at: string;
  updated_at: string;
}

export interface Draft {
  draft_id: string;
  display_name?: string;
  goal: string;
  trial_task?: string;
  template_key: TemplateKey;
  template_config?: JsonObject;
  connection_ids: string[];
  resource_ids: string[];
  knowledge_source_refs: KnowledgeSourceRef[];
  lifecycle: DraftLifecycle;
  current_revision_id?: string;
  active_invocation_id?: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSourceRef {
  provider: string;
  profile_ref?: string;
  resource_ref?: string;
  version?: string;
  etag?: string;
  metadata?: Record<string, string>;
}

export interface Invocation {
  invocation_id: string;
  authoring_session_id?: string;
  kind: "generate" | "update" | "run" | "validate" | "discover";
  status: InvocationStatus;
  message: string;
  model?: string;
  event_url: string;
  started_at?: string;
  finished_at?: string;
  created_at: string;
  knowledge_source_refs?: KnowledgeSourceRef[];
}

export interface AuthoringSession {
  authoring_session_id: string;
  draft_id: string;
  title: string;
  status: AuthoringSessionStatus;
  last_message_preview?: string;
  active_invocation_id?: string;
  last_event_cursor?: string;
  created_at: string;
  updated_at: string;
}

export interface Revision {
  revision_id: string;
  draft_id: string;
  number: number;
  skill_name: string;
  template_key?: TemplateKey;
  template_config?: JsonObject;
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
  presentation?: PresentationManifest;
  csp?: string;
  sandbox?: string;
  created_at: string;
}

export interface PresentationManifest {
  schemaVersion: "1.0";
  surface: "dashboard" | "semantic_graph" | "sop" | "generic";
  title: string;
  entry: string;
  mediaType: "text/html";
  source: string;
  sandboxProfile: "static-self-contained";
  viewport: {
    responsive: boolean;
    defaultWidth: number;
    mobileWidth: number;
    minWidth: number;
  };
  integrity: { sha256: string };
}

export interface ArtifactPreviewEventData {
  artifact_id?: string;
  snapshot_id?: string;
  revision_id?: string;
  media_type?: string;
  sha256?: string;
  title?: string;
  uri?: string;
  csp?: string;
  sandbox?: string;
  status?: "pending" | "preview" | "final" | "blocked" | "error";
  message?: string;
  source?: string;
  log?: string | string[];
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
      type: "message.delta";
      data: { text: string; sequence?: number; final?: boolean };
    }
  | {
      type: "progress";
      data: { text?: string; message?: string; stage?: string };
    }
  | {
      type: "planning";
      data: { steps?: PlanStep[]; summary?: string; title?: string; status?: string };
    }
  | {
      type: "action" | "tool_call";
      data: {
        call_id?: string;
        tool_call_id?: string;
        name?: string;
        tool_name?: string;
        input?: JsonValue;
        arguments?: JsonValue;
        input_summary?: string;
        status?: string;
      };
    }
  | {
      type: "observation" | "tool_output";
      data: {
        call_id?: string;
        tool_call_id?: string;
        name?: string;
        tool_name?: string;
        ok?: boolean;
        output?: JsonValue;
        output_summary?: string;
        error?: string;
        error_summary?: string;
        duration_ms?: number;
        status?: string;
      };
    }
  | {
      type: "artifact.preview" | "artifact.final";
      data: ArtifactPreviewEventData;
    }
  | {
      type: "state";
      data: {
        state_ready?: boolean;
        remote_saved?: boolean;
        error_summary?: string;
      };
    }
  | {
      type: "error";
      data: {
        code?: string;
        message?: string;
        retryable?: boolean;
        category?: "network" | "permission" | "model" | "artifact" | "unknown";
      };
    }
  | {
      type: "done";
      data: { status?: "succeeded"; finished_at?: string; artifact_ids?: string[]; revision_id?: string };
    }
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
