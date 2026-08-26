/* Generated from contracts.py; do not edit manually. */

import type { AddCitationIntentPatch, ArtifactExportResult, ArtifactRef, AssetOwner, AssetPermission, AssistantTurnResult, Audit, DraftCommandResult, ErrorEnvelope, EvaluationFixActionPayload } from "./part1";
import type { PublicationPublishResult, RefreshRunResult, ResourceShareResult, RunProvenance, SchemaRef, SecretRef, SetDashboardChartPatch, SetDashboardFilterPatch, SetDashboardKpiPatch, SetDescriptionPatch, SetGraphEntityPatch, SetGraphRelationPatch, SetPermissionScopePatch, SetQueryPlanPatch, SetRefreshPolicyPatch, SetSemanticDimensionPatch, SetSemanticMappingPatch, SetSemanticMetricPatch, SetSemanticRelationshipPatch, SetSopConditionPatch, SetSopStepPatch, SetSopToolRefPatch, SetThresholdPolicyPatch, SetTitlePatch, SkillAuthoringAnswerResult, SkillAuthoringExecuteResult, SkillAuthoringPatchResult, SkillAuthoringStartResult, SkillDraftRunResult, SkillManifestAction } from "./part3";
import type { SkillResult, SourceCleanResult, SourceGoldenConnectionResult, SourceGoldenIngestResult, SourceProfileResult, StorageRef, TypedPatch, frontend__server__knowledge_assets__contract_views__EvaluationCase, frontend__server__knowledge_assets__contract_views__EvaluationRun, frontend__server__knowledge_assets__contract_views__EvaluationSuite, frontend__server__knowledge_assets__contract_views__PolicyGateResult, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationRun, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationSuite, frontend__server__knowledge_assets__evaluation_quality__models__PolicyGateResult } from "./part4";

export interface EvaluationFixProposeAllPayload {
  runId: string;
  affectedCaseIds: Array<string>;
  conflicts?: Array<string>;
  patch: TypedPatch;
}

export interface EvaluationFixProposeCommand {
  command: "evaluation-fix.propose";
  payload: EvaluationFixProposePayload;
}

export interface EvaluationFixProposePayload {
  runId: string;
  issueCaseIds: Array<string>;
  affectedCaseIds: Array<string>;
  conflicts?: Array<string>;
  patch: TypedPatch;
}

export interface EvaluationFixUndoCommand {
  command: "evaluation-fix.undo";
  payload: EvaluationFixActionPayload;
}

export interface EvaluationPayload {
  targetId: string;
  suiteId?: string;
  environment?: "production" | "demo" | "test";
  caseIds?: Array<string>;
  cases?: Array<frontend__server__knowledge_assets__contract_views__EvaluationCase>;
}

export interface EvaluationQualityCommandResult {
  resultType: "evaluation-suite.create" | "evaluation-suite.revise" | "evaluation-case.import" | "evaluation-case.adopt-history" | "evaluation-case.generate-candidates" | "evaluation-case.confirm-candidates" | "evaluation-run.start" | "evaluation-run.cancel" | "evaluation-run.resume" | "evaluation-run.retry" | "evaluation-fix.propose" | "evaluation-fix.propose-all-unresolved" | "evaluation-fix.apply" | "evaluation-fix.undo" | "policy-gate.evaluate";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed" | "blocked";
  suite?: frontend__server__knowledge_assets__evaluation_quality__models__EvaluationSuite | null;
  run?: frontend__server__knowledge_assets__evaluation_quality__models__EvaluationRun | null;
  fixPlan?: FixPlan | null;
  gate?: frontend__server__knowledge_assets__evaluation_quality__models__PolicyGateResult | null;
  cases?: Array<frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase>;
  message?: string | null;
}

export interface EvaluationRunActionPayload {
  runId: string;
}

export interface EvaluationRunCancelCommand {
  command: "evaluation-run.cancel";
  payload: EvaluationRunActionPayload;
}

export interface EvaluationRunResult {
  resultType: "evaluation.run" | "evaluation.apply";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  targetId: string;
  evaluationSuite?: frontend__server__knowledge_assets__contract_views__EvaluationSuite | null;
  evaluationRun?: frontend__server__knowledge_assets__contract_views__EvaluationRun | null;
  policyGateResult?: frontend__server__knowledge_assets__contract_views__PolicyGateResult | null;
}

export interface EvaluationRunResumeCommand {
  command: "evaluation-run.resume";
  payload: EvaluationRunActionPayload;
}

export interface EvaluationRunRetryCommand {
  command: "evaluation-run.retry";
  payload: EvaluationRunRetryPayload;
}

export interface EvaluationRunRetryPayload {
  runId: string;
}

export interface EvaluationRunStartCommand {
  command: "evaluation-run.start";
  payload: EvaluationRunStartPayload;
}

export interface EvaluationRunStartPayload {
  suiteId: string;
  suiteVersion: number;
  provenance: RunProvenance;
  selectedCaseIds?: Array<string>;
}

export interface EvaluationSuiteCreateCommand {
  command: "evaluation-suite.create";
  payload: EvaluationSuiteCreatePayload;
}

export interface EvaluationSuiteCreatePayload {
  suiteId: string;
  skillId: string;
  cases: Array<frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase>;
  passThreshold?: number;
}

export interface EvaluationSuiteReviseCommand {
  command: "evaluation-suite.revise";
  payload: EvaluationSuiteRevisePayload;
}

export interface EvaluationSuiteRevisePayload {
  suiteId: string;
  version: number;
  additions: Array<frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase>;
}

export interface Event {
  schemaVersion?: "knowledge-assets.event.v1";
  operationId: string;
  eventId: string;
  sequence: number;
  occurredAt: string;
  type: "accepted" | "progress" | "succeeded" | "failed" | "cancelled";
  terminal: boolean;
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | SkillAuthoringStartResult | SkillAuthoringAnswerResult | SkillAuthoringPatchResult | SkillAuthoringExecuteResult | SourceGoldenConnectionResult | SourceGoldenIngestResult | null;
  error?: ErrorEnvelope | null;
}

export interface ExcelConnectorConfig {
  sourceRef: string;
  kind: "excel";
  sheetAllowlist?: Array<string>;
}

export interface FixPlan {
  id: string;
  runId: string;
  issueCaseIds: Array<string>;
  affectedCaseIds: Array<string>;
  conflicts?: Array<string>;
  patch: TypedPatch;
  status?: "proposed" | "applied" | "undone";
  newDraftRevision?: string | null;
  rerunId?: string | null;
  undoToken?: string | null;
}

export interface FreshnessPolicy {
  as_of?: string | null;
  max_age_seconds?: number;
  require_fixed_revision?: boolean;
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

export interface GoldenAssetRevisionRecord {
  id: string;
  assetId: string;
  revision: number;
  assetKind: "dataset" | "knowledge";
  schemaDigest: string;
  storageRef: ArtifactRef;
  owner: AssetOwner;
  permissions: AssetPermission;
  lineage: GoldenLineage;
  qualityScore: number;
  freshnessAt: string;
  dataAsOf: string;
  lastGood?: boolean;
  traceId: string;
}

export interface GoldenLineage {
  connectionId: string;
  resourceId: string;
  sourceRevisionId: string;
  profileRunId: string;
  recipeId: string;
  recipeVersion: number;
  cleanRunId: string;
  contentDigest: string;
  correlationId: string;
  adapterRunId?: string | null;
  checkpoint?: Record<string, string>;
  lineageDigest: string;
  toolArguments?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  confidence?: number | null;
  evidenceLocator?: string | null;
}

export interface GraphNode {
  id: string;
  label: string;
  entityType: string;
}

export interface GraphOntologyViewModel {
  template?: "graph_ontology";
  nodes?: Array<GraphNode>;
  edges?: Array<GraphEdge>;
  evidenceRef?: StorageRef | null;
  evidenceLocators?: Array<string>;
  conflicts?: Array<string>;
  selectedNodeId?: string | null;
}

export interface GraphRelationSpec {
  source: string;
  target: string;
  relation: string;
  evidenceLocator: string;
}

export interface GraphqlConnectorConfig {
  endpoint: string;
  secretRef?: SecretRef | null;
  operationAllowlist: Array<string>;
  maxRows?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "graphql";
  query: string;
}

export interface HiveConnectorConfig {
  secretRef: SecretRef;
  host: string;
  port: number;
  database: string;
  schemaAllowlist: Array<string>;
  tableAllowlist: Array<string>;
  query?: string | null;
  queryParameters?: Record<string, JsonValue>;
  pageSize?: number;
  rowLimit?: number;
  byteLimit?: number;
  timeoutSeconds?: number;
  kind: "hive";
}

export interface ImportCommand {
  command: "import.start" | "import.cancel";
  payload: ImportPayload;
}

export interface ImportPayload {
  sourceId: string;
}

export interface InputContract {
  name: string;
  type: "string" | "number" | "boolean" | "date" | "dimension" | "metric" | "document_ref";
  required?: boolean;
}

export interface Invocation {
  id: string;
  skillVersionId: string;
  skillViewRevisionId: string;
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
  skillViewRevisionId?: string;
  inputRef: StorageRef;
  callerId: string;
}

export interface InvocationStartResult {
  resultType?: "invocation.start";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  skillVersionId: string;
  invocation?: Invocation | null;
  skillResult?: SkillResult | null;
  dataRevisionRefs?: Array<string>;
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

export interface JsonConnectorConfig {
  sourceRef: string;
  kind: "json";
  maxDepth?: number;
  maxRows?: number;
}

export type JsonValue = unknown;

export interface KafkaConnectorConfig {
  kind: "kafka";
  secretRef: SecretRef;
  bootstrapServers: Array<string>;
  topics: Array<string>;
  consumerGroup: string;
  maxMessages?: number;
  maxMessageBytes?: number;
  timeoutSeconds?: number;
}

export interface KnowledgeCitation {
  citationId: string;
  sourceRevisionId: string;
  title: string;
  locator: string;
  excerptRef?: StorageRef | null;
}

export interface KnowledgeViewModel {
  template?: "knowledge";
  answer: string;
  citations?: Array<KnowledgeCitation>;
  refusal?: boolean;
}

export interface LarkBaseConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_base";
  appRef: string;
  tableRef: string;
  viewRef?: string | null;
}

export interface LarkChatConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_chat";
  chatRef: string;
  timeRange: string;
}

export interface LarkDocConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_doc";
  documentRef: string;
}

export interface LarkDriveConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_drive";
  folderRef: string;
}

export interface LarkGroupConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_group";
  chatRef: string;
  timeRange: string;
  includeAttachments?: boolean;
}

export interface LarkMailConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_mail";
  folder: string;
  query?: string | null;
}

export interface LarkMeetingConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_meeting";
  calendarRef: string;
  dateFrom: string;
  dateTo: string;
  attendees?: Array<string>;
}

export interface LarkMinutesConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_minutes";
  minutesRef: string;
}

export interface LarkSheetConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_sheet";
  sheetRef: string;
  sheetName?: string | null;
  cellRange?: string;
}

export interface LarkWikiConnectorConfig {
  secretRef: SecretRef;
  scopeRef: string;
  apiBaseUrl?: string;
  pageSize?: number;
  maxPages?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "lark_wiki";
  wikiRef: string;
}

export interface LegacySkillManifestInput {
  name: string;
  version: string;
  description?: string;
  actions?: Array<SkillManifestAction>;
  schema?: ManifestInputSchema;
}

export interface LocalFileConnectorConfig {
  sourceRef: string;
  kind: "local_file";
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

export interface McpCustomConnectorConfig {
  kind: "mcp_custom";
  transport: "stdio" | "streamable_http" | "sse";
  command?: string | null;
  args?: Array<string>;
  env?: Record<string, string>;
  cwd?: string | null;
  endpoint?: string | null;
  secretRef?: SecretRef | null;
  oauthScopeRef?: string | null;
  toolAllowlist: Array<string>;
  startupTimeoutSeconds?: number;
  callTimeoutSeconds?: number;
  maxPages?: number;
  outputBytes?: number;
}

export interface MonitoringInvocationView {
  startedAt: string;
  traceId: string;
  durationMs?: number | null;
  status: string;
  summary?: string;
  operationId?: string | null;
}

export interface MonitoringObservationView {
  metric: string;
  latest: number;
  previous?: number | null;
  changeRate?: number | null;
  durationSeconds: number;
  freshnessAt: string;
  lastGoodRevisionId?: string | null;
}

export interface MonitoringViewModel {
  template?: "monitoring";
  metricRefs?: Array<string>;
  values?: Array<[string, number]>;
  alerts?: Array<string>;
  dataRef?: StorageRef | null;
  observations?: Array<MonitoringObservationView>;
  failureTrace?: Array<string>;
  invocationRows?: Array<MonitoringInvocationView>;
  callVolume?: number | null;
  successRate?: number | null;
  latencyMs?: number | null;
  stale?: boolean;
  status?: "healthy" | "stale" | "alert" | "failed" | "empty";
}

export interface MysqlConnectorConfig {
  secretRef: SecretRef;
  host: string;
  port: number;
  database: string;
  schemaAllowlist: Array<string>;
  tableAllowlist: Array<string>;
  query?: string | null;
  queryParameters?: Record<string, JsonValue>;
  pageSize?: number;
  rowLimit?: number;
  byteLimit?: number;
  timeoutSeconds?: number;
  kind: "mysql";
}

export interface NotReadyCommandResult {
  resultType?: "command.not-ready";
  error: ErrorEnvelope;
  command: string;
}

export interface OpenapiSpecConnectorConfig {
  kind: "openapi_spec";
  specRef: string;
  secretRef?: SecretRef | null;
  operationAllowlist: Array<string>;
  serverUrl?: string | null;
  maxRows?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
}

export interface Operation {
  operationId: string;
  status: "accepted" | "running" | "succeeded" | "failed" | "cancelled";
  version: number;
  events: Array<Event>;
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | SkillAuthoringStartResult | SkillAuthoringAnswerResult | SkillAuthoringPatchResult | SkillAuthoringExecuteResult | SourceGoldenConnectionResult | SourceGoldenIngestResult | null;
  error?: ErrorEnvelope | null;
  nextActions?: Array<string>;
  audit?: Array<Audit>;
}

export interface OracleConnectorConfig {
  kind: "oracle";
  secretRef: SecretRef;
  host: string;
  port: number;
  serviceName: string;
  schemaAllowlist: Array<string>;
  tableAllowlist: Array<string>;
  query?: string | null;
  queryParameters?: Record<string, JsonValue>;
  pageSize?: number;
  rowLimit?: number;
  byteLimit?: number;
  timeoutSeconds?: number;
}

export interface OssConnectorConfig {
  secretRef: SecretRef;
  bucket: string;
  objectPrefix?: string;
  region?: string | null;
  maxObjects?: number;
  maxObjectBytes?: number;
  timeoutSeconds?: number;
  kind: "oss";
  endpoint: string;
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

export interface ParquetConnectorConfig {
  sourceRef: string;
  kind: "parquet";
  maxRows?: number;
  maxColumns?: number;
  maxUncompressedBytes?: number;
  maxNestingDepth?: number;
}

export interface PatchImpact {
  summary: string;
  affected_paths: Array<string>;
  requires_rerun: boolean;
  reason: "presentation_only" | "query_changed" | "metric_changed" | "permission_changed" | "freshness_changed" | "alert_changed" | "mapping_changed";
}

export interface PatchOperation {
  op: "replace_query" | "replace_metric" | "replace_retrieval_policy" | "replace_view_binding" | "replace_interaction" | "replace_budget";
  path: string;
  before: unknown;
  after: unknown;
}

export interface PatchProposal {
  patch_id?: string;
  operation_id?: string | null;
  draft_id: string;
  base_revision: number;
  patch: SetTitlePatch | SetDescriptionPatch | SetQueryPlanPatch | SetRefreshPolicyPatch | SetThresholdPolicyPatch | SetPermissionScopePatch | AddCitationIntentPatch | SetSemanticMappingPatch | SetSemanticMetricPatch | SetSemanticDimensionPatch | SetSemanticRelationshipPatch | SetDashboardKpiPatch | SetDashboardChartPatch | SetDashboardFilterPatch | SetSopStepPatch | SetSopConditionPatch | SetSopToolRefPatch | SetGraphEntityPatch | SetGraphRelationPatch;
  impact: PatchImpact;
  status?: "proposed" | "accepted" | "rejected" | "undone" | "conflicted";
  proposed_by: string;
  source_comment_ids?: Array<string>;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  base_digest?: string | null;
  new_digest?: string | null;
  new_revision?: number | null;
  view_revision_id?: string | null;
  created_at?: string;
}

export interface PermissionRef {
  uri: string;
  version: string;
}