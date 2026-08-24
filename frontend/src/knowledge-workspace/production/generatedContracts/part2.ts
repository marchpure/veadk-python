/* Generated from contracts.py; do not edit manually. */

import type { DraftCommandResult, ErrorEnvelope } from "./part1";
import type { NotReadyCommandResult, OwnerRef, PermissionRef, PublicationPublishResult, RefreshRunResult, SchemaRef, SecretRef } from "./part3";
import type { SkillDraftRunResult, SkillManifestAction, SourceCleanResult, SourceProfileResult, StorageRef } from "./part4";

export interface EvaluationPayload {
  targetId: string;
}

export interface EvaluationRun {
  id: string;
  suiteId: string;
  suiteVersion: number;
  skillRevisionId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  score?: number | null;
  evidenceRef?: StorageRef | null;
  regressionRef?: StorageRef | null;
  startedAt: string;
  finishedAt?: string | null;
}

export interface EvaluationSuite {
  id: string;
  version: number;
  skillId: string;
  caseCount: number;
  casesRef: StorageRef;
  passThreshold: number;
}

export interface Event {
  schemaVersion?: "knowledge-assets.event.v1";
  operationId: string;
  eventId: string;
  sequence: number;
  occurredAt: string;
  type: "accepted" | "progress" | "succeeded" | "failed" | "cancelled";
  terminal: boolean;
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | null;
  error?: ErrorEnvelope | null;
}

export interface FileConnectorConfig {
  kind: "markdown" | "csv" | "pdf" | "office" | "excel";
  sourceRef: string;
  maxBytes?: number;
  maxFiles?: number;
  followSymlinks?: false;
  sheetAllowlist?: Array<string>;
}

export interface GoldenAssetRevision {
  id: string;
  assetKind: "dataset" | "knowledge" | "semantic" | "graph";
  revision: number;
  schemaRef: SchemaRef;
  storageRef: StorageRef;
  sourceRevisionRefs?: Array<string>;
  recipeRef?: string | null;
  qualityRunRef?: string | null;
  owner: OwnerRef;
  permissionsRef: PermissionRef;
  lineageDigest: string;
  freshnessAt: string;
  lastGood?: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface GraphNode {
  id: string;
  label: string;
  entityType: string;
}

export interface GraphOntologyKindSpec {
  kind?: "graph_ontology";
  entitySchemaRef: SchemaRef;
  relationshipSchemaRef: SchemaRef;
  constraintRefs?: Array<string>;
  evidencePolicyRef?: PermissionRef | null;
}

export interface GraphOntologyViewModel {
  template?: "graph_ontology";
  nodes?: Array<GraphNode>;
  edges?: Array<GraphEdge>;
  evidenceRef?: StorageRef | null;
}

export interface ImportCommand {
  command: "import.start" | "import.cancel";
  payload: ImportPayload;
}

export interface ImportPayload {
  sourceId: string;
}

export interface Invocation {
  id: string;
  skillVersionId: string;
  callerId: string;
  workspaceId: string;
  status: "accepted" | "resolving" | "running" | "awaiting_confirmation" | "succeeded" | "failed" | "cancelled";
  inputRef?: StorageRef | null;
  resultRef?: StorageRef | null;
  traceId: string;
  actualDataRevisionRefs?: Array<string>;
  startedAt: string;
  finishedAt?: string | null;
}

export interface InvocationStartCommand {
  command: "invocation.start";
  payload: InvocationStartPayload;
}

export interface InvocationStartPayload {
  skillVersionId: string;
  inputRef: StorageRef;
  callerId: string;
}

export interface InvocationStartResult {
  resultType?: "invocation.start";
  error?: ErrorEnvelope | null;
  status?: "not_ready";
  skillVersionId: string;
}

export interface JobEvent {
  jobId: string;
  sequence: number;
  eventType: "enqueued" | "leased" | "heartbeat" | "retry_scheduled" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "dead_letter";
  occurredAt: string;
  payloadRef?: StorageRef | null;
}

export interface JobState {
  jobId: string;
  jobType: string;
  profile: "production" | "demo" | "test";
  idempotencyKey: string;
  status: "queued" | "leased" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled" | "dead_letter";
  attempt: number;
  maxAttempts: number;
  leaseOwner?: string | null;
  leaseExpiresAt?: string | null;
  heartbeatAt?: string | null;
  nextAttemptAt?: string | null;
  cancelRequested?: boolean;
  outboxSequence?: number;
}

export interface KnowledgeCitation {
  citationId: string;
  sourceRevisionId: string;
  title: string;
  locator: string;
  excerptRef?: StorageRef | null;
}

export interface KnowledgeKindSpec {
  kind?: "knowledge";
  retrievalMode?: "hybrid" | "vector" | "keyword";
  sourceRevisionRefs?: Array<string>;
  citationPolicyRef?: PermissionRef | null;
  refusalPolicyRef?: string | null;
}

export interface KnowledgeViewModel {
  template?: "knowledge";
  answer: string;
  citations?: Array<KnowledgeCitation>;
  refusal?: boolean;
}

export interface LegacySkillManifestInput {
  name: string;
  version: string;
  description?: string;
  actions?: Array<SkillManifestAction>;
  schema?: ManifestInputSchema;
}

export interface ManifestInputSchema {
  type?: "object";
  properties?: Record<string, ManifestProperty>;
  required?: Array<string>;
  additionalProperties?: boolean;
}

export interface ManifestProperty {
  type: "string" | "number" | "boolean" | "object" | "array";
  description?: string;
}

export interface McpConnectorConfig {
  kind: "mcp";
  serverUrl: string;
  secretRef: SecretRef;
  oauthScopeRef: string;
  toolAllowlist: Array<string>;
  outputBytes?: number;
  timeoutSeconds?: number;
}

export interface MonitoringKindSpec {
  kind?: "monitoring";
  metricRefs?: Array<string>;
  refreshScheduleRef: string;
  alertPolicyRef: string;
  actionPolicyRef?: PermissionRef | null;
}

export interface MonitoringViewModel {
  template?: "monitoring";
  metricRefs?: Array<string>;
  values?: Array<[string, number]>;
  alerts?: Array<string>;
  dataRef?: StorageRef | null;
}