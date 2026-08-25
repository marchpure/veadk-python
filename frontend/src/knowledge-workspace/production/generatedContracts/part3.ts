/* Generated from contracts.py; do not edit manually. */

import type { ArtifactExportResult, ArtifactRef, AssistantTurnResult, Audit, AuthoringEvent, AuthoringOperation, DraftCommandResult, DraftRevision, ErrorEnvelope } from "./part1";
import type { EvaluationQualityCommandResult, EvaluationRunResult, Event, GoldenAssetRevision, InvocationStartResult, LegacySkillManifestInput } from "./part2";
import type { SkillManifest, SkillOperation, SkillResult, SkillViewRevision, SkillViewShareGrant, SourceCleanResult, SourceGoldenConnectionResult, SourceGoldenIngestResult, SourceProfileResult, StorageRef, ViewIntent } from "./part4";

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
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | SkillAuthoringStartResult | SourceGoldenConnectionResult | SourceGoldenIngestResult | null;
  error?: ErrorEnvelope | null;
  nextActions?: Array<string>;
  audit?: Array<Audit>;
}

export interface OutputContract {
  name: string;
  type: "answer" | "table" | "metric" | "chart" | "schema" | "graph" | "observation";
  required?: boolean;
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

export interface PlanNode {
  node_id: string;
  role: "intent_resolution" | "context_resolution" | "query_plan" | "retrieval" | "schema_mapping" | "threshold_policy" | "worker3_execution";
  depends_on?: Array<string>;
  input_names?: Array<string>;
  output_names?: Array<string>;
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

export interface ProfileField {
  name: string;
  dataType: string;
  nullable: boolean;
  nullCount: number;
  distinctCount: number;
  sensitive?: boolean;
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

export interface ProfileRunRecord {
  id: string;
  sourceRevisionId: string;
  status: "succeeded" | "failed" | "cancelled";
  rowCount: number;
  fields: Array<ProfileField>;
  qualityScore: number;
  sensitiveFields: Array<string>;
  reportRef: ArtifactRef;
  sampleRef: ArtifactRef;
  startedAt: string;
  finishedAt: string;
  traceId: string;
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
  status?: "not_ready" | "succeeded" | "failed";
  draftId: string;
  publishedVersion?: PublishedSkillVersion | null;
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

export interface QueryPlan {
  source_revision: string;
  selected_fields: Array<string>;
  filters?: Record<string, string>;
  limit?: number;
  read_only?: true;
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

export interface ResourceRef {
  kind: "golden_asset" | "data_access_skill" | "knowledge_asset" | "skill";
  object_id: string;
  revision: string;
  scope: Scope;
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

export type Scope = "personal" | "team";

export interface SecretRef {
  uri: string;
  version: string;
}

export interface SemanticViewModel {
  template?: "semantic";
  schemaRef: SchemaRef;
  metricRefs?: Array<string>;
  dimensionRefs?: Array<string>;
  relationshipRefs?: Array<string>;
  dataRef?: StorageRef | null;
}

export interface SkillAuthoringStartCommand {
  command: "skill-authoring.start";
  payload: SkillAuthoringStartPayload;
}

export interface SkillAuthoringStartPayload {
  prompt: string;
  resourceRefs?: Array<ResourceRef>;
  permissions?: Array<string>;
  fixedRevisions?: Array<string>;
  requestedKind?: "knowledge" | "semantic" | "analysis" | "graph_ontology" | "monitoring" | null;
  scope?: "personal" | "team";
  displayName?: string | null;
  currentSkillId?: string | null;
  currentViewId?: string | null;
  currentComponentId?: string | null;
  commentIds?: Array<string>;
}

export interface SkillAuthoringStartResult {
  resultType?: "skill-authoring.start";
  error?: ErrorEnvelope | null;
  status?: "queued" | "planning" | "awaiting_input" | "ready_for_execution" | "credential_blocked" | "failed" | "cancelled";
  operation?: AuthoringOperation | null;
  draft?: DraftRevision | null;
  events?: Array<AuthoringEvent>;
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

export interface SkillDraftRetryPayload {
  draftId: string;
  revision: number;
  traceId: string;
  maxSteps?: number;
  budget?: number;
  retryOfOperationId: string;
}

export interface SkillDraftRevision {
  id: string;
  skillId: string;
  revision: number;
  manifest: SkillManifest;
  sourceRevisionRefs?: Array<string>;
  goldenAssetRevisionRefs?: Array<string>;
  status?: "draft" | "planning" | "awaiting_input" | "running" | "partially_succeeded" | "failed" | "ready_for_evaluation" | "evaluating" | "publishable" | "publishing" | "published";
  createdAt: string;
}

export interface SkillDraftRunCommand {
  command: "skill-draft.run";
  payload: SkillDraftRunPayload;
}

export interface SkillDraftRunPayload {
  draftId: string;
  revision: number;
  traceId: string;
  maxSteps?: number;
  budget?: number;
}

export interface SkillDraftRunResult {
  resultType?: "skill-draft.run";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "planning" | "awaiting_input" | "running" | "partially_succeeded" | "failed" | "cancelled" | "ready_for_evaluation";
  draftId: string;
  goldenAssetRevision?: GoldenAssetRevision | null;
  skillResult?: SkillResult | null;
  viewIntent?: ViewIntent | null;
  skillViewRevision?: SkillViewRevision | null;
  executionState?: "ok" | "no_data" | "unable_to_answer" | "permission_denied" | "schema_drift" | "validation_failed" | "timeout" | "over_budget" | "cancelled" | "credential_blocked" | "awaiting_input" | null;
  traceRef?: StorageRef | null;
  evidenceRef?: StorageRef | null;
}

export type SkillKind = "knowledge" | "semantic" | "analysis" | "graph_ontology" | "monitoring";