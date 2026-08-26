/* Generated from contracts.py; do not edit manually. */

import type { EvaluationFixProposeAllPayload, EvaluationPayload, EvaluationQualityCommandResult, EvaluationRunResult, FreshnessPolicy, InputContract, InvocationStartResult, JsonValue, NotReadyCommandResult, OutputContract, PermissionRef } from "./part2";
import type { PlanNode, PublicationPublishResult, QueryPlan, RefreshRunResult, ResourceRef, ResourceShareResult, Scope, SecretRef, SkillAuthoringAnswerResult, SkillAuthoringExecuteResult, SkillAuthoringPatchResult, SkillAuthoringStartResult, SkillDraft, SkillDraftRunResult, SkillKind } from "./part3";
import type { SkillPatch, SourceCleanResult, SourceGoldenConnectionResult, SourceGoldenIngestResult, SourceProfileResult, StorageRef, TemplateSelection, ViewCell, ViewField, frontend__server__skill_authoring__models__AnalysisKindSpec, frontend__server__skill_authoring__models__GraphOntologyKindSpec, frontend__server__skill_authoring__models__KnowledgeKindSpec, frontend__server__skill_authoring__models__MonitoringKindSpec, frontend__server__skill_authoring__models__SemanticKindSpec, frontend__server__skill_authoring__models__SopKindSpec } from "./part4";

export interface ActionCommand {
  command: "action.update";
  payload: ActionUpdatePayload;
}

export interface ActionUpdatePayload {
  actionId: string;
}

export interface AddCitationIntentPatch {
  patch_type?: "add_citation_intent";
  intent: string;
}

export interface AgentAnswer {
  status: "succeeded" | "awaiting_input";
  text?: string | null;
  citations?: Array<ResourceRef>;
  clarification_questions?: Array<string>;
}

export interface AgentBinding {
  id: string;
  skillVersionId: string;
  agentId: string;
  workspaceId: string;
  versionSelector: string;
  status?: "active" | "revoked";
  createdAt: string;
}

export interface AgentEventEvidence {
  event_type: string;
  author?: string | null;
  has_content?: boolean;
  output_present?: boolean;
}

export interface AgentExecutionEvidence {
  session_id: string;
  trace_id: string;
  status: "running" | "succeeded" | "failed";
  events?: Array<AgentEventEvidence>;
  tool_calls?: Array<AgentToolCallEvidence>;
  error_code?: AuthoringErrorCode | null;
  error_message?: string | null;
}

export interface AgentToolCallEvidence {
  name: string;
  call_id?: string | null;
  status?: "requested" | "succeeded" | "failed";
}

export interface AlertEvent {
  id: string;
  skillId: string;
  severity: "info" | "warning" | "critical";
  status: "open" | "acknowledged" | "resolved";
  ruleRef: string;
  fingerprint: string;
  observedAt: string;
  payloadRef?: StorageRef | null;
}

export interface ArtifactExportCommand {
  command: "artifact.export";
  payload: ArtifactExportPayload;
}

export interface ArtifactExportPayload {
  resourceId: string;
  format: "json" | "csv" | "html";
}

export interface ArtifactExportResult {
  resultType?: "artifact.export";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  resourceId: string;
  artifactRef?: StorageRef | null;
}

export interface ArtifactRef {
  uri: string;
  sha256: string;
  mediaType: string;
  bytes: number;
}

export interface AssetOwner {
  workspaceId: string;
  principalId: string;
}

export interface AssetPermission {
  workspaceId: string;
  scope: "personal" | "team";
  canRead: boolean;
  canWrite: boolean;
  inheritedFromConnectionId: string;
  version: number;
}

export interface AssistantCommand {
  command: "assistant.turn";
  payload: AssistantTurnPayload;
}

export interface AssistantContextEnvelope {
  skillId: string;
  viewRevisionId: string;
  selectedIds?: Array<string>;
  schemaRef: string;
  permissionScope: string;
}

export interface AssistantDiff {
  patchId: string;
  skillId: string;
  baseRevision: number;
  nextRevision: number;
  operation: SkillPatch;
  before: string;
  after: string;
  undoToken: string;
}

export interface AssistantTurnPayload {
  text: string;
  contextIds?: Array<string>;
  context?: AssistantContextEnvelope | null;
  patch?: SkillPatch | null;
}

export interface AssistantTurnResult {
  resultType?: "assistant.turn";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  skillId: string;
  diff?: AssistantDiff | null;
  rerun?: SkillDraftRunResult | null;
}

export interface Audit {
  requestId: string;
  operationId: string;
  workspaceId: string;
  action: string;
  resourceId: string;
  outcome: string;
  details?: Record<string, unknown>;
  occurredAt: string;
}

export type AuthoringErrorCode = "invalid_context" | "permission_denied" | "resource_not_found" | "awaiting_input" | "credential_blocked" | "model_timeout" | "model_unavailable" | "validation_failed" | "optimistic_conflict" | "team_read_only" | "evaluation_required" | "not_found" | "cancelled" | "execution_blocked";

export interface AuthoringEvent {
  event_id?: string;
  operation_id: string;
  event_type: "operation_created" | "context_resolved" | "agent_execution" | "plan_proposed" | "clarification_required" | "credential_blocked" | "draft_created" | "patch_proposed" | "patch_accepted" | "patch_rejected" | "undo_applied" | "execution_requested" | "operation_retry" | "operation_cancelled" | "operation_failed" | "message.accepted" | "context.resolving" | "context.resolved" | "agent.started" | "answer.delta" | "answer.final" | "tool.started" | "tool.progress" | "tool.completed" | "tool.failed" | "plan.created" | "plan.step.started" | "plan.step.completed" | "plan.step.failed" | "artifact.revision.created" | "operation.completed" | "operation.failed" | "operation.cancelled";
  sequence: number;
  data?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  type?: "message.accepted" | "context.resolving" | "context.resolved" | "agent.started" | "answer.delta" | "answer.final" | "tool.started" | "tool.progress" | "tool.completed" | "tool.failed" | "plan.created" | "plan.step.started" | "plan.step.completed" | "plan.step.failed" | "artifact.revision.created" | "operation.completed" | "operation.failed" | "operation.cancelled" | null;
  session_id?: string | null;
  trace_id?: string | null;
  public_summary?: string;
  terminal?: boolean;
  occurred_at?: string;
}

export interface AuthoringOperation {
  operation_id: string;
  operation_type: "answer" | "create_draft" | "propose_patch" | "accept_patch" | "patch_reject" | "undo" | "comment_repair" | "comment_repair_batch" | "execute_draft" | "retry" | "cancel" | "copy_team_draft" | "submit_team_review" | "update_context";
  status: AuthoringStatus;
  caller_id: string;
  workspace_id: string;
  conversation_id?: string | null;
  draft_id?: string | null;
  current_revision?: number | null;
  error_code?: AuthoringErrorCode | null;
  error_message?: string | null;
  trace_id: string;
  patch_id?: string | null;
  retry_of_operation_id?: string | null;
  clarification_questions?: Array<string>;
  stage?: "received" | "planning" | "context_resolved" | "plan_ready" | "clarification" | "draft_ready" | "patch_ready" | "execution_queued" | "execution_succeeded" | "credential_blocked" | "cancelled" | "failed";
  progress?: number;
  context_digest?: string | null;
  plan?: BuildPlan | null;
  agent_execution?: AgentExecutionEvidence | null;
  artifact_result?: Record<string, unknown> | null;
  execution_result?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
}

export type AuthoringStatus = "queued" | "planning" | "awaiting_input" | "credential_blocked" | "running" | "ready_for_execution" | "succeeded" | "failed" | "cancelled";

export interface BigqueryConnectorConfig {
  kind: "bigquery";
  secretRef: SecretRef;
  projectId: string;
  datasetId: string;
  schemaAllowlist: Array<string>;
  tableAllowlist: Array<string>;
  query?: string | null;
  queryParameters?: Record<string, JsonValue>;
  pageSize?: number;
  rowLimit?: number;
  byteLimit?: number;
  timeoutSeconds?: number;
}

export interface Budget {
  max_steps?: number;
  max_tokens?: number;
  timeout_ms?: number;
}

export interface BuildPlan {
  plan_id: string;
  intent: SkillKind;
  purpose: string;
  nodes: Array<PlanNode>;
  inputs?: Array<InputContract>;
  outputs: Array<OutputContract>;
  dependencies?: Array<ResourceRef>;
  kind_spec: frontend__server__skill_authoring__models__KnowledgeKindSpec | frontend__server__skill_authoring__models__SemanticKindSpec | frontend__server__skill_authoring__models__AnalysisKindSpec | frontend__server__skill_authoring__models__SopKindSpec | frontend__server__skill_authoring__models__GraphOntologyKindSpec | frontend__server__skill_authoring__models__MonitoringKindSpec;
  query_plan?: QueryPlan | null;
  clarification_questions?: Array<string>;
  data_refs?: Array<ResourceRef>;
  metrics?: Array<string>;
  dimensions?: Array<string>;
  layout_intent?: "kpi" | "trend" | "table" | "funnel" | "breakdown" | "graph" | "document" | "alert";
  refresh_policy?: FreshnessPolicy;
  lineage?: Array<ResourceRef>;
  plan_digest: string;
}

export interface CapabilityReason {
  code: string;
  message: string;
  retryable?: boolean;
}

export type CaseCategory = "normal" | "refusal" | "unauthorized" | "empty_data" | "ambiguity" | "metric_definition" | "citation" | "chart_consistency" | "interaction" | "performance_budget";

export type CaseSource = "manual" | "historical_conversation" | "historical_run" | "csv_import" | "json_import" | "agent_candidate";

export interface ChartSeries {
  name: string;
  points?: Array<[string, number]>;
}

export interface ChartViewModel {
  template?: "chart";
  title: string;
  xField: string;
  yField: string;
  chartType?: "line" | "bar" | "stacked_bar" | "area" | "donut" | "scatter" | "table";
  series?: Array<ChartSeries>;
  dataRef: StorageRef;
}

export interface CleanRun {
  id: string;
  sourceRevisionId: string;
  recipeId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  outputRef?: StorageRef | null;
  qualityReportRef?: StorageRef | null;
  errorCode?: string | null;
  startedAt: string;
  finishedAt?: string | null;
}

export interface CleanRunRecord {
  id: string;
  sourceRevisionId: string;
  recipeId: string;
  status: "succeeded" | "failed" | "cancelled";
  outputRef: ArtifactRef;
  qualityReportRef: ArtifactRef;
  startedAt: string;
  finishedAt: string;
  traceId: string;
}

export interface CleaningRecipe {
  id: string;
  version: number;
  operations?: Array<"trim" | "deduplicate" | "normalize" | "split" | "map" | "redact">;
  configRef?: StorageRef | null;
  sourceRevisionId: string;
  recipeDigest: string;
}

export interface CleaningRecipeRecord {
  id: string;
  assetId: string;
  version: number;
  sourceRevisionId: string;
  operations: Array<"trim" | "deduplicate" | "normalize" | "redact">;
  recipeDigest: string;
  createdAt: string;
}

export interface ClickhouseConnectorConfig {
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
  kind: "clickhouse";
}

export interface CommandResponse {
  accepted: boolean;
  requestId: string;
  operationId?: string | null;
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | SkillAuthoringStartResult | SkillAuthoringAnswerResult | SkillAuthoringPatchResult | SkillAuthoringExecuteResult | SourceGoldenConnectionResult | SourceGoldenIngestResult | null;
}

export interface CompatibilityTargets {
  targets?: Array<"agentkit" | "mcp" | "openapi" | "codex">;
}

export interface ConnectionViewModel {
  id: string;
  workspaceId: string;
  connectorKey: string;
  displayName: string;
  scope: "personal" | "team";
  ownerId: string;
  status: "ready" | "config_required" | "credential_blocked" | "unsupported" | "revoked";
  syncMode: "full" | "incremental" | "realtime" | "local";
  createdAt: string;
  updatedAt: string;
  lastSuccessAt?: string | null;
  lastError?: CapabilityReason | null;
  discoveredResources?: Array<DiscoveredResource>;
  goldenRevisionIds?: Array<string>;
}

export interface ConnectorCommand {
  command: "connector.create" | "connector.test";
  payload: ConnectorPayload;
}

export interface ConnectorOperation {
  operation: "validate" | "authenticate" | "authorize" | "discover" | "introspect" | "sample" | "read" | "ingest" | "profile" | "clean" | "golden" | "refresh" | "checkpoint" | "close" | "revoke" | "delete";
  status: "succeeded" | "config_required" | "credential_blocked" | "unsupported" | "failed";
  traceId: string;
  reason: CapabilityReason;
  resources?: Array<DiscoveredResource>;
}

export interface ConnectorPayload {
  connectorKey: string;
}

export interface ContextRevisionRef {
  kind: "source" | "golden_asset" | "document" | "semantic_skill" | "published_skill" | "tool";
  resourceId: string;
  revisionId: string;
  digest: string;
  permissionRef?: PermissionRef | null;
}

export interface CreateSkillDraftCommand {
  command: "skill-draft.create";
  payload: CreateSkillDraftPayload;
}

export interface CreateSkillDraftPayload {
  workspaceId: string;
  name: string;
  description?: string;
  sourceRefs?: Array<string>;
}

export interface CsvConnectorConfig {
  sourceRef: string;
  kind: "csv";
}

export interface CustomHttpConnectorConfig {
  endpoint: string;
  secretRef?: SecretRef | null;
  operationAllowlist: Array<string>;
  maxRows?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "custom_http";
  name: string;
  method?: "GET" | "HEAD";
  paginationMode?: "none" | "cursor" | "offset";
  pageSize?: number;
  maxPages?: number;
}

export interface DashboardChart {
  chartId: string;
  title: string;
  xField: string;
  yField: string;
  chartType?: "line" | "bar" | "stacked_bar" | "area" | "donut" | "scatter" | "table";
  series?: Array<ChartSeries>;
}

export interface DashboardDrill {
  sourceField: string;
  targetFields?: Array<string>;
}

export interface DashboardFilter {
  field: string;
  operator: "eq" | "in" | "gte" | "lte" | "between";
  values?: Array<string | number | boolean>;
}

export interface DashboardKpi {
  key: string;
  label: string;
  value: string | number;
  unit?: string;
  trend?: "up" | "down" | "flat" | "unknown";
}

export interface DashboardPresentationSpec {
  title?: string | null;
  kpiLabels?: Record<string, string>;
  chartTitle?: string | null;
  filterFields?: Array<string>;
  drillFields?: Array<string>;
}

export interface DashboardViewModel {
  template?: "dashboard";
  title?: string;
  fields?: Array<ViewField>;
  kpis?: Array<DashboardKpi>;
  charts?: Array<DashboardChart>;
  rows?: Array<Array<ViewCell>>;
  filters?: Array<DashboardFilter>;
  drills?: Array<DashboardDrill>;
  insights?: Array<string>;
  freshnessAt?: string | null;
  status?: "populated" | "partial" | "stale" | "empty" | "error";
  dataRef: StorageRef;
}

export interface DataAccessKindSpec {
  kind?: "data_access";
  connectorType: "oracle" | "mysql" | "postgresql" | "csv" | "excel" | "markdown" | "pdf" | "office" | "lark_doc" | "lark_minutes" | "lark_group_chat" | "web_api" | "web_url" | "rest_api" | "graphql" | "openapi" | "mcp" | "published_skill" | "local_file";
  endpointRef: string;
  secretRef?: SecretRef | null;
  allowedSchemas?: Array<string>;
  allowedTables?: Array<string>;
  allowedOperations?: Array<"introspect" | "query" | "read" | "subscribe" | "search">;
  rowPolicyRef?: PermissionRef | null;
  columnPolicyRef?: PermissionRef | null;
}

export interface DiscoveredField {
  name: string;
  dataType: string;
  nullable?: boolean;
}

export interface DiscoveredResource {
  id: string;
  name: string;
  resourceType: "file" | "table" | "document" | "operation" | "tool";
  schemaName?: string | null;
  rowCount?: number | null;
  fields?: Array<DiscoveredField>;
  inputSchema?: Record<string, unknown> | null;
  outputSchema?: Record<string, unknown> | null;
  permission?: "read" | "denied";
}

export interface DocumentConnectorConfig {
  sourceRef: string;
  kind: "doc_txt";
  maxTextChars?: number;
}

export interface DorisConnectorConfig {
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
  kind: "doris";
}

export interface DraftCommandResult {
  resultType: "skill-draft.create" | "skill-draft.save-manifest";
  error?: ErrorEnvelope | null;
  draft: SkillDraft;
  replayed?: boolean;
}

export interface DraftManifest {
  name: string;
  description: string;
  kind: SkillKind;
  kind_spec: frontend__server__skill_authoring__models__KnowledgeKindSpec | frontend__server__skill_authoring__models__SemanticKindSpec | frontend__server__skill_authoring__models__AnalysisKindSpec | frontend__server__skill_authoring__models__SopKindSpec | frontend__server__skill_authoring__models__GraphOntologyKindSpec | frontend__server__skill_authoring__models__MonitoringKindSpec;
  inputs: Array<InputContract>;
  outputs: Array<OutputContract>;
  dependencies: Array<ResourceRef>;
  permissions: Array<string>;
  freshness: FreshnessPolicy;
}

export interface DraftRevision {
  draft_id: string;
  revision: number;
  parent_revision?: number | null;
  manifest: DraftManifest;
  plan: BuildPlan;
  state?: "draft" | "awaiting_execution" | "execution_requested" | "conflicted";
  scope: Scope;
  owner_id: string;
  workspace_id: string;
  budget?: Budget;
  authorized_permissions?: Array<string>;
  lineage?: Array<ResourceRef>;
  lineage_source_draft_id?: string | null;
  promotion_state?: "personal" | "team_read_only" | "pre_publish_evaluation";
  digest: string;
  selected_template?: TemplateSelection | null;
  created_at?: string;
  updated_at?: string;
  undo_of_revision?: number | null;
  dashboard_config?: Record<string, unknown>;
  sop_steps?: Array<Record<string, unknown>>;
  graph_config?: Record<string, unknown>;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  retryable: boolean;
  requestId: string;
  details?: Record<string, string> | null;
}

export interface EvaluationCaseAdoptHistoryCommand {
  command: "evaluation-case.adopt-history";
  payload: EvaluationCaseAdoptHistoryPayload;
}

export interface EvaluationCaseAdoptHistoryPayload {
  caseId: string;
  category: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  provenanceRef: string;
  source: "historical_conversation" | "historical_run";
}

export interface EvaluationCaseConfirmCommand {
  command: "evaluation-case.confirm-candidates";
  payload: EvaluationCaseConfirmPayload;
}

export interface EvaluationCaseConfirmPayload {
  suiteId: string;
  version: number;
  caseIds: Array<string>;
}

export interface EvaluationCaseGenerateCandidateCommand {
  command: "evaluation-case.generate-candidates";
  payload: EvaluationCaseGenerateCandidatePayload;
}

export interface EvaluationCaseGenerateCandidatePayload {
  caseId: string;
  category: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  provenanceRef: string;
}

export interface EvaluationCaseImportCommand {
  command: "evaluation-case.import";
  payload: EvaluationCaseImportPayload;
}

export interface EvaluationCaseImportPayload {
  content: string;
  mediaType: "application/json" | "text/csv";
}

export interface EvaluationCommand {
  command: "evaluation.run" | "evaluation.apply";
  payload: EvaluationPayload;
}

export interface EvaluationFixActionPayload {
  planId: string;
}

export interface EvaluationFixApplyCommand {
  command: "evaluation-fix.apply";
  payload: EvaluationFixActionPayload;
}

export interface EvaluationFixProposeAllCommand {
  command: "evaluation-fix.propose-all-unresolved";
  payload: EvaluationFixProposeAllPayload;
}