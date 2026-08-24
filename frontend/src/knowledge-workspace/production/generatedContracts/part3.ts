/* Generated from contracts.py; do not edit manually. */

import type { ArtifactExportResult, AssistantTurnResult, Audit, DraftCommandResult, ErrorEnvelope } from "./part1";
import type { EvaluationQualityCommandResult, EvaluationRunResult, Event, InvocationStartResult, KnowledgeCitation } from "./part2";
import type { SkillDraftRetryPayload, SkillDraftRunResult, SkillManifest, SkillManifestAction, SkillOperation, SkillViewShareGrant, SourceCleanResult, SourceProfileResult, StorageRef } from "./part4";

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

export interface NotReadyCommandResult {
  resultType?: "command.not-ready";
  error: ErrorEnvelope;
  command: string;
}

export interface Operation {
  operationId: string;
  status: "accepted" | "running" | "succeeded" | "failed" | "cancelled";
  version: number;
  events: Array<Event>;
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | null;
  error?: ErrorEnvelope | null;
  nextActions?: Array<string>;
  audit?: Array<Audit>;
}

export interface OwnerRef {
  workspaceId: string;
  principalId: string;
}

export interface PatchOperation {
  op: "replace_query" | "replace_metric" | "replace_retrieval_policy" | "replace_view_binding" | "replace_interaction" | "replace_budget";
  path: string;
  before: unknown;
  after: unknown;
}

export interface PermissionRef {
  uri: string;
  version: string;
}

export interface PolicyCheck {
  dimension: "schema" | "data_quality" | "freshness" | "permission" | "security" | "evaluation" | "visual_interaction" | "compatibility" | "budget";
  passed: boolean;
  machineReason: string;
  evidenceRefs?: Array<string>;
}

export interface PolicyGateEvaluateCommand {
  command: "policy-gate.evaluate";
  payload: PolicyGateEvaluatePayload;
}

export interface PolicyGateEvaluatePayload {
  runId: string;
  checks?: Array<PolicyCheck>;
}

export interface ProfileRun {
  id: string;
  sourceRevisionId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  sampleRef?: StorageRef | null;
  reportRef?: StorageRef | null;
  structureRef?: StorageRef | null;
  qualityScore?: number | null;
  sensitiveClassification?: Array<string>;
  estimatedCostRef?: StorageRef | null;
  errorCode?: string | null;
  startedAt: string;
  finishedAt?: string | null;
}

export interface ProviderDocumentConfig {
  kind: "lark_doc" | "lark_minutes" | "lark_group_chat";
  documentRef: string;
  secretRef: SecretRef;
  scopeRef: string;
  pageSize?: number;
}

export interface PublicationPublishCommand {
  command: "publication.publish";
  payload: PublicationPublishPayload;
}

export interface PublicationPublishPayload {
  draftId: string;
  revision: number;
  semver: string;
}

export interface PublicationPublishResult {
  resultType?: "publication.publish";
  error?: ErrorEnvelope | null;
  status?: "not_ready";
  draftId: string;
}

export interface PublishedSkillConnectorConfig {
  kind: "published_skill";
  skillRef: string;
  secretRef: SecretRef;
  scopeRef: string;
  dependencyAllowlist: Array<string>;
  outputBytes?: number;
  timeoutSeconds?: number;
}

export interface PublishedSkillVersion {
  id: string;
  skillId: string;
  semver: string;
  manifest: SkillManifest;
  skillRevisionId: string;
  digest: string;
  status?: "published" | "deprecated" | "revoked";
  evaluationRunId: string;
  policyGateResultId: string;
  skillViewRef?: string | null;
  publishedAt: string;
}

export interface RefreshRun {
  id: string;
  skillId: string;
  trigger: "manual" | "schedule" | "event" | "freshness_on_read";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  stagingRef?: StorageRef | null;
  currentRevision?: number | null;
  lastGoodRevision?: number | null;
  errorCode?: string | null;
  startedAt: string;
  finishedAt?: string | null;
}

export interface RefreshRunCommand {
  command: "refresh.run";
  payload: RefreshRunPayload;
}

export interface RefreshRunPayload {
  skillId: string;
  trigger: "manual" | "schedule" | "event" | "freshness_on_read";
}

export interface RefreshRunResult {
  resultType?: "refresh.run";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  skillId: string;
  refreshRun?: RefreshRun | null;
}

export interface ResourceCommand {
  command: "resource.create" | "resource.update" | "resource.publish" | "resource.share" | "resource.revoke";
  payload: ResourcePayload;
}

export interface ResourcePayload {
  resourceId: string;
  reason?: string;
}

export interface ResourceShareResult {
  resultType?: "resource.share";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  resourceId: string;
  shareGrant?: SkillViewShareGrant | null;
}

export interface RunProvenance {
  suiteId: string;
  suiteVersion: number;
  environment: "test" | "staging" | "production";
  skillDraftRevision: string;
  dependencyRevisionRefs?: Array<string>;
  goldenRevisionRefs?: Array<string>;
  executorVersion: string;
  rendererVersion: string;
  dataAsOf: string;
}

export interface SaveManifestCommand {
  command: "skill-draft.save-manifest";
  payload: SaveManifestPayload;
}

export interface SaveManifestPayload {
  draftId: string;
  baseRevision: number;
  manifest: SkillManifest | LegacySkillManifestInput;
}

export interface SchemaRef {
  uri: string;
  version: string;
  sha256: string;
}

export interface SecretRef {
  uri: string;
  version: string;
}

export interface SemanticKindSpec {
  kind?: "semantic";
  metricRefs?: Array<string>;
  dimensionRefs?: Array<string>;
  relationshipRefs?: Array<string>;
  queryPolicyRef?: PermissionRef | null;
}

export interface SemanticViewModel {
  template?: "semantic";
  schemaRef: SchemaRef;
  metricRefs?: Array<string>;
  dimensionRefs?: Array<string>;
  relationshipRefs?: Array<string>;
  dataRef?: StorageRef | null;
}

export interface SkillContract {
  inputSchemaRef: SchemaRef;
  outputSchemaRef: SchemaRef;
  examplesRef?: StorageRef | null;
  errorCodes?: Array<string>;
  operations?: Array<SkillOperation>;
}

export interface SkillDependencies {
  skills?: Array<string>;
  goldenAssets?: Array<string>;
  sources?: Array<string>;
}

export interface SkillDraft {
  id: string;
  workspaceId: string;
  name: string;
  description: string;
  revision: number;
  lifecycle?: "draft";
  viewState?: "debug";
  createdAt: string;
  updatedAt: string;
  manifest: SkillManifest;
}

export interface SkillDraftRetryCommand {
  command: "skill-draft.retry";
  payload: SkillDraftRetryPayload;
}