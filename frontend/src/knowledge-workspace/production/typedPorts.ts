import {
  parseBootstrap,
  type KnowledgeBootstrap,
  type WorkspaceActionLoopState,
  type WorkspaceBootstrapData,
  type WorkspaceConnectorDefinition,
  type WorkspaceDatasetField,
  type WorkspaceKpi,
  type WorkspaceKnowledgeGraphEntity,
  type WorkspaceKnowledgeGraphMapping,
  type WorkspaceTrendPoint,
} from "./bootstrapSchema";
import {
  createKnowledgeAssetClient,
  GeneratedClientHttpError,
  type KnowledgeAssetClient,
} from "./generatedClient";
import type {
  GeneratedCommand,
  GeneratedLegacyManifest,
  GeneratedManifest,
} from "./generated";
import type {
  AssistantContextEnvelope,
  SkillPatch,
} from "./generatedContracts";

export type KnowledgeCommandName =
  | "resource.create"
  | "resource.update"
  | "resource.publish"
  | "resource.share"
  | "resource.revoke"
  | "connector.create"
  | "connector.test"
  | "import.start"
  | "import.cancel"
  | "stream.cancel"
  | "assistant.turn"
  | "evaluation.run"
  | "evaluation.apply"
  | "action.update"
  | "artifact.export"
  | "skill-draft.create"
  | "skill-draft.save-manifest"
  | "source.profile"
  | "source.clean"
  | "source-golden.connection.create"
  | "source-golden.ingest"
  | "skill-draft.retry"
  | "skill-draft.run"
  | "publication.publish"
  | "refresh.run"
  | "invocation.start";

export interface ActionUpdatePayload {
  actionId: string;
}
export interface SkillDraftCreatePayload {
  workspaceId: string;
  name: string;
  description: string;
  sourceRefs: string[];
}
export interface SkillDraftSaveManifestPayload {
  draftId: string;
  baseRevision: number;
  manifest: GeneratedManifest | GeneratedLegacyManifest;
}
export interface ResourceCommandPayload {
  resourceId: string;
}
export interface ConnectorCommandPayload {
  connectorKey: string;
}
export interface ImportCommandPayload {
  sourceId: string;
}
export interface AssistantTurnPayload {
  text: string;
  contextIds: string[];
  context?: AssistantContextEnvelope | null;
  patch?: SkillPatch | null;
}
export interface EvaluationPayload {
  targetId: string;
  suiteId: string;
  environment: "production" | "demo" | "test";
  caseIds: string[];
}
export interface ArtifactExportPayload {
  resourceId: string;
  format: "json" | "csv" | "html";
}
export interface StreamCancelPayload {
  streamId: string;
  sourceCommand: "import.start" | "assistant.turn";
}
export interface SourceProfilePayload {
  sourceRevisionId: string;
  sampleLimit: number;
}
export interface SourceCleanPayload {
  sourceRevisionId: string;
  recipeId: string;
}
export interface SkillDraftRunPayload {
  draftId: string;
  revision: number;
  traceId: string;
  maxSteps: number;
  budget: number;
}
export interface SkillDraftRetryPayload extends SkillDraftRunPayload {
  retryOfOperationId: string;
}
export interface PublicationPublishPayload {
  draftId: string;
  revision: number;
  semver: string;
}
export interface RefreshRunPayload {
  skillId: string;
  trigger: "manual" | "schedule" | "event" | "freshness_on_read";
}
export interface InvocationStartPayload {
  skillVersionId: string;
  skillViewRevisionId: string;
  inputRef: import("./generatedContracts").StorageRef;
  callerId: string;
}
export type KnowledgeCommand =
  | { command: "action.update"; payload: ActionUpdatePayload }
  | { command: "skill-draft.create"; payload: SkillDraftCreatePayload }
  | {
    command: "skill-draft.save-manifest";
    payload: SkillDraftSaveManifestPayload;
  }
  | { command: "resource.create" | "resource.update" | "resource.publish" | "resource.share" | "resource.revoke"; payload: ResourceCommandPayload }
  | { command: "connector.create" | "connector.test"; payload: ConnectorCommandPayload }
  | { command: "import.start" | "import.cancel"; payload: ImportCommandPayload }
  | { command: "stream.cancel"; payload: StreamCancelPayload }
  | { command: "assistant.turn"; payload: AssistantTurnPayload }
  | { command: "evaluation.run" | "evaluation.apply"; payload: EvaluationPayload }
  | { command: "artifact.export"; payload: ArtifactExportPayload }
  | { command: "source.profile"; payload: SourceProfilePayload }
  | { command: "source.clean"; payload: SourceCleanPayload }
  | {
    command: "source-golden.connection.create";
    payload: import("./generatedContracts").SourceGoldenConnectionCreatePayload;
  }
  | {
    command: "source-golden.ingest";
    payload: import("./generatedContracts").SourceGoldenIngestPayload;
  }
  | { command: "skill-draft.retry"; payload: SkillDraftRetryPayload }
  | { command: "skill-draft.run"; payload: SkillDraftRunPayload }
  | { command: "publication.publish"; payload: PublicationPublishPayload }
  | { command: "refresh.run"; payload: RefreshRunPayload }
  | { command: "invocation.start"; payload: InvocationStartPayload };
export type KnowledgeErrorCode =
  | "UNAVAILABLE"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "CREDENTIAL_EXPIRED"
  | "RATE_LIMITED"
  | "TIMEOUT"
  | "CONFLICT"
  | "CANCELLED"
  | "PARTIAL_FAILURE"
  | "INVALID_RESPONSE"
  | "NETWORK"
  | "VALIDATION_ERROR"
  | "DRAFT_NOT_FOUND"
  | "OPERATION_NOT_FOUND";
export interface KnowledgeRequestContext {
  requestId: string;
  idempotencyKey: string;
  expectedVersion?: string;
  lastEventId?: string;
  signal?: AbortSignal;
}
export interface KnowledgeError {
  code: KnowledgeErrorCode;
  message: string;
  retryable: boolean;
  requestId: string;
  retryAfterMs?: number;
  details?: Record<string, string>;
}

export type {
  KnowledgeBootstrap,
  WorkspaceActionLoopState,
  WorkspaceBootstrapData,
  WorkspaceConnectorDefinition,
  WorkspaceDatasetField,
  WorkspaceKpi,
  WorkspaceKnowledgeGraphEntity,
  WorkspaceKnowledgeGraphMapping,
  WorkspaceTrendPoint,
};
export interface KnowledgeCommandResult {
  accepted: boolean;
  requestId: string;
  operationId?: string;
  version?: string;
  result?: Record<string, unknown>;
}
export interface KnowledgeStreamEvent {
  schema_version: string;
  stream_id: string;
  event_id: string;
  sequence: number;
  occurred_at: string;
  type: string;
  payload: Record<string, unknown>;
  terminal: boolean;
}
export interface KnowledgeStream {
  events: AsyncIterable<KnowledgeStreamEvent>;
  cancel: () => Promise<void>;
}
export interface WorkspaceAdapter {
  readonly kind: "production-http" | "contract";
  readonly allowOptimisticUpdates: boolean;
  bootstrap(signal?: AbortSignal): Promise<KnowledgeBootstrap>;
  command(
    command: KnowledgeCommand,
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeCommandResult>;
  stream(
    command: Extract<
      KnowledgeCommand,
      { command: "import.start" | "assistant.turn" }
    >,
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeStream>;
}
type LegacyCommandName = KnowledgeCommandName;
export class KnowledgeAdapterError extends Error {
  readonly issue: KnowledgeError;
  constructor(issue: KnowledgeError) {
    super(issue.message);
    this.name = "KnowledgeAdapterError";
    this.issue = issue;
  }
}
let requestSequence = 0;
