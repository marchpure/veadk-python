/* Generated from contracts.py; do not edit manually. */

import type { ArtifactRef, CaseCategory, CaseSource, ChartViewModel, CleanRun, CleanRunRecord, CleaningRecipeRecord, CompatibilityTargets, ConnectionViewModel, ConnectorOperation, ContextRevisionRef, DashboardPresentationSpec, DashboardViewModel, DataAccessKindSpec, ErrorEnvelope } from "./part1";
import type { GoldenAssetRevision, GoldenAssetRevisionRecord, GraphOntologyViewModel, GraphRelationSpec, JsonValue, KnowledgeViewModel, MonitoringViewModel, OwnerRef, PatchOperation } from "./part2";
import type { PermissionRef, PolicyCheck, ProfileRun, ProfileRunRecord, QueryPlan, RunProvenance, SchemaRef, SecretRef, SemanticViewModel, SkillContract, SkillDependencies } from "./part3";

export interface SkillMetadata {
  id: string;
  version: string;
  displayName: string;
  description?: string;
  owner: OwnerRef;
  digest?: string | null;
}

export interface SkillOperation {
  name: string;
  description?: string;
  inputSchemaRef: SchemaRef;
  outputSchemaRef: SchemaRef;
  risk?: "read_only" | "external_write" | "high_risk";
}

export interface SkillPatch {
  patchId: string;
  skillId: string;
  baseRevision: number;
  operation: "set_description" | "set_runtime_ref" | "set_evaluation_suite_ref";
  value: string;
  undoToken?: string | null;
}

export interface SkillResult {
  id: string;
  skillId: string;
  skillRevision: number;
  kind: "data_access" | "semantic" | "analysis" | "sop" | "knowledge" | "graph_ontology" | "monitoring";
  outputSchemaRef: SchemaRef;
  resultRef: StorageRef;
  sourceRevisionRefs?: Array<string>;
  goldenAssetRevisionRefs?: Array<string>;
  traceId: string;
  freshnessAt?: string | null;
}

export interface SkillSpec {
  kind: "data_access" | "semantic" | "analysis" | "sop" | "knowledge" | "graph_ontology" | "monitoring";
  contract: SkillContract;
  dependencies?: SkillDependencies;
  policyRef: PermissionRef;
  runtimeRef: string;
  evaluationSuiteRef?: string | null;
  skillViewRef?: string | null;
  compatibility?: CompatibilityTargets;
  templateRef?: TemplateRef | null;
  defaultRenderer?: "dashboard" | "semantic" | "sop" | "knowledge" | "graph_ontology" | "monitoring" | null;
  contextRevisionRefs?: Array<ContextRevisionRef>;
  kindSpec: DataAccessKindSpec | frontend__server__knowledge_assets__contract_base__SemanticKindSpec | frontend__server__knowledge_assets__contract_base__AnalysisKindSpec | frontend__server__knowledge_assets__contract_base__KnowledgeKindSpec | frontend__server__knowledge_assets__contract_base__GraphOntologyKindSpec | frontend__server__knowledge_assets__contract_base__MonitoringKindSpec | frontend__server__knowledge_assets__contract_base__SopKindSpec;
}

export interface SkillViewManifest {
  id: string;
  skillRevisionId: string;
  rendererRef: string;
  viewModelSchemaRef: SchemaRef;
  allowedComponents?: Array<string>;
  cspProfile?: "trusted-renderer-v1";
}

export interface SkillViewRevision {
  id: string;
  skillRevisionId: string;
  revision: number;
  manifest: SkillViewManifest;
  intent: ViewIntent;
  viewModel: DashboardViewModel | ChartViewModel | SemanticViewModel | KnowledgeViewModel | GraphOntologyViewModel | MonitoringViewModel | SopViewModel;
  invocationId?: string | null;
  resultRef?: StorageRef | null;
  htmlDigest?: string | null;
  etag?: string | null;
  csp?: string;
  dataRevisionRefs?: Array<string>;
  traceId?: string | null;
  createdAt: string;
}

export interface SkillViewShareGrant {
  id: string;
  resourceId: string;
  skillViewRevisionId: string;
  workspaceId: string;
  permission?: "read";
  expiresAt?: string | null;
  createdAt: string;
}

export interface SnowflakeConnectorConfig {
  kind: "snowflake";
  secretRef: SecretRef;
  account: string;
  warehouse: string;
  database: string;
  schemaAllowlist: Array<string>;
  tableAllowlist: Array<string>;
  query?: string | null;
  queryParameters?: Record<string, JsonValue>;
  pageSize?: number;
  rowLimit?: number;
  byteLimit?: number;
  timeoutSeconds?: number;
}

export interface SopActionProposal {
  proposalId: string;
  title: string;
  risk: "external_write" | "high_risk";
  confirmationRequired?: true;
  challenge: string;
  toolRef: string;
}

export interface SopCondition {
  field: string;
  operator: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains" | "exists";
  value?: string | number | boolean | null;
}

export interface SopEvidenceRequirement {
  kind: "tool_result" | "source_citation" | "input" | "decision";
  required?: boolean;
  locator?: string | null;
}

export interface SopInputField {
  name: string;
  label: string;
  valueType: "string" | "number" | "boolean" | "enum";
  required?: boolean;
  enumValues?: Array<string>;
  description?: string;
}

export interface SopOutputField {
  name: string;
  description?: string;
  valueType: "string" | "number" | "boolean" | "object" | "array";
}

export interface SopPlanInput {
  name: string;
  label: string;
  value_type: "string" | "number" | "boolean" | "enum";
  required?: boolean;
  enum_values?: Array<string>;
  description?: string;
}

export interface SopPlanOutput {
  name: string;
  description?: string;
  value_type: "string" | "number" | "boolean" | "object" | "array";
}

export interface SopPlanStep {
  id: string;
  title: string;
  instruction: string;
  condition?: Record<string, unknown> | null;
  tool_ref?: Record<string, unknown> | null;
  evidence_requirements?: Array<Record<string, unknown>>;
  on_true?: string | null;
  on_false?: string | null;
  failure_mode?: "stop" | "continue" | "request_input" | "propose_action";
}

export interface SopStep {
  id: string;
  title: string;
  instruction: string;
  condition?: SopCondition | null;
  toolRef?: SopToolRef | null;
  evidenceRequirements?: Array<SopEvidenceRequirement>;
  onTrue?: string | null;
  onFalse?: string | null;
  failureMode?: "stop" | "continue" | "request_input" | "propose_action";
}

export interface SopStepEvidence {
  kind: "tool_result" | "source_citation" | "input" | "decision";
  locator: string;
  summary: string;
}

export interface SopStepResult {
  stepId: string;
  title: string;
  status: "succeeded" | "skipped" | "failed" | "awaiting_confirmation";
  branch?: "true" | "false" | "unconditional";
  evidence?: Array<SopStepEvidence>;
  message?: string;
  toolRefs?: Array<string>;
  inputSummary?: string;
}

export interface SopToolRef {
  toolId: string;
  revision: string;
  operation: string;
  risk?: "read_only" | "external_write" | "high_risk";
}

export interface SopViewModel {
  template?: "sop";
  title: string;
  trigger: string;
  scope: string;
  stepResults?: Array<SopStepResult>;
  recommendation: string;
  outputs?: Record<string, string | number | boolean | null>;
  actionProposals?: Array<SopActionProposal>;
  runState?: "queued" | "running" | "succeeded" | "failed" | "awaiting_confirmation";
}

export interface SourceCleanCommand {
  command: "source.clean";
  payload: SourceCleanPayload;
}

export interface SourceCleanPayload {
  sourceRevisionId: string;
  recipeId: string;
}

export interface SourceCleanResult {
  resultType?: "source.clean";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  sourceRevisionId: string;
  recipeId: string;
  cleanRun?: CleanRun | null;
  goldenAssetRevision?: GoldenAssetRevision | null;
}

export interface SourceGoldenConnectionCreateCommand {
  command: "source-golden.connection.create";
  payload: SourceGoldenConnectionCreatePayload;
}

export interface SourceGoldenConnectionCreatePayload {
  connectorKey: string;
  displayName: string;
  scope?: "personal" | "team";
  configuration?: Record<string, unknown>;
  secretRef?: string | null;
  mcpProfileId?: string | null;
  toolAllowlist?: Array<string>;
}

export interface SourceGoldenConnectionResult {
  resultType?: "source_golden.connection";
  connection: ConnectionViewModel;
  validation: ConnectorOperation;
  discovery: ConnectorOperation;
  replayed?: boolean;
}

export interface SourceGoldenIngestCommand {
  command: "source-golden.ingest";
  payload: SourceGoldenIngestPayload;
}

export interface SourceGoldenIngestPayload {
  connectionId: string;
  resourceId?: string | null;
  recipeOperations?: Array<"trim" | "deduplicate" | "normalize" | "redact">;
  toolArguments?: Record<string, unknown>;
}

export interface SourceGoldenIngestResult {
  resultType?: "source_golden.ingest";
  sourceRevision: SourceRevisionRecord;
  profileRun: ProfileRunRecord;
  cleaningRecipe: CleaningRecipeRecord;
  cleanRun: CleanRunRecord;
  goldenAssetRevision: GoldenAssetRevisionRecord;
  replayed?: boolean;
}

export interface SourceProfileCommand {
  command: "source.profile";
  payload: SourceProfilePayload;
}

export interface SourceProfilePayload {
  sourceRevisionId: string;
  sampleLimit?: number;
}

export interface SourceProfileResult {
  resultType?: "source.profile";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  sourceRevisionId: string;
  profileRun?: ProfileRun | null;
}

export interface SourceRevision {
  id: string;
  sourceType: "local_file" | "markdown" | "csv" | "pdf" | "document" | "database" | "excel" | "office" | "lark_doc" | "lark_minutes" | "lark_group_chat" | "web_api" | "web_url" | "rest_api" | "graphql" | "openapi" | "mcp" | "published_skill";
  contentRef: StorageRef;
  schemaRef?: SchemaRef | null;
  permissionRef: PermissionRef;
  sourceDigest: string;
  createdAt: string;
}

export interface SourceRevisionRecord {
  id: string;
  workspaceId: string;
  connectionId: string;
  resourceId: string;
  sourceType: "markdown" | "text" | "html" | "csv" | "excel" | "json" | "parquet" | "pdf" | "sqlite" | "mcp" | "http" | "database" | "office";
  contentRef: ArtifactRef;
  sourceDigest: string;
  schemaDigest: string;
  sourceLocator: string;
  permissionVersion: number;
  checkpoint?: Record<string, string>;
  createdAt: string;
  traceId: string;
}

export interface SqliteConnectorConfig {
  sourceRef: string;
  kind: "sqlite";
  tableAllowlist?: Array<string>;
  query?: string | null;
  rowLimit?: number;
}

export interface SqlserverConnectorConfig {
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
  kind: "sqlserver";
}

export interface StarrocksConnectorConfig {
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
  kind: "starrocks";
}

export interface StorageRef {
  uri: string;
  kind: "object" | "table" | "vector" | "bundle" | "inline";
  sha256: string;
  mediaType: string;
  bytes?: number | null;
}

export interface StreamCancelCommand {
  command: "stream.cancel";
  payload: StreamCancelPayload;
}

export interface StreamCancelPayload {
  streamId: string;
  sourceCommand: "import.start" | "assistant.turn";
}

export interface TemplateEvidenceRule {
  evidenceKind: "data_revision" | "source_citation" | "tool_result" | "schema" | "trace";
  description: string;
  minimumCount?: number;
}

export interface TemplateQualityGate {
  gateId: string;
  description: string;
  required?: boolean;
}

export interface TemplateRef {
  templateId: string;
  version: string;
  digest: string;
}

export interface TemplateSelection {
  template_id: string;
  version: string;
  digest: string;
}

export interface TemplateSpec {
  templateId: string;
  version: string;
  displayName: string;
  scenario: string;
  requiredContextKinds: Array<"tabular" | "document" | "semantic_skill" | "knowledge" | "graph" | "tool" | "observation">;
  inputSchema: Record<string, unknown>;
  capabilityIntent: "data_access" | "semantic" | "analysis" | "sop" | "knowledge" | "graph_ontology" | "monitoring";
  executionInstructions: Array<string>;
  evidenceRules: Array<TemplateEvidenceRule>;
  qualityGates: Array<TemplateQualityGate>;
  defaultRenderer: "dashboard" | "semantic" | "sop" | "knowledge" | "graph_ontology" | "monitoring";
  allowedTools?: Array<string>;
  allowedActions?: Array<string>;
  compatibility?: CompatibilityTargets;
  builtin?: boolean;
  ownerWorkspaceId?: string | null;
  copiedFrom?: TemplateRef | null;
}

export interface TypedPatch {
  id: string;
  baseDraftRevision: string;
  operations: Array<PatchOperation>;
}

export interface ViewCell {
  field: string;
  value: string | number | boolean | null;
}

export interface ViewField {
  name: string;
  label: string;
  dataType: "string" | "number" | "boolean" | "date" | "json";
}

export interface ViewIntent {
  id: string;
  skillId: string;
  skillRevision: number;
  template: "dashboard" | "chart" | "semantic" | "sop" | "knowledge" | "graph_ontology" | "monitoring";
  purpose: "overview" | "compare" | "schema" | "answer" | "explore" | "monitor";
  resultRef: string;
}

export interface WebDiscoveryConnectorConfig {
  endpoint: string;
  secretRef?: SecretRef | null;
  operationAllowlist: Array<string>;
  maxRows?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "web_discovery";
  paginationMode?: "none" | "cursor" | "offset" | "link_header";
  pageSize?: number;
  maxPages?: number;
  termsRef?: string | null;
}

export interface WebhookConnectorConfig {
  kind: "webhook";
  secretRef: SecretRef;
  listenPath: string;
  schemaRef: string;
  maxEventBytes?: number;
  maxEvents?: number;
  rateLimitPerMinute?: number;
}

export interface frontend__server__knowledge_assets__contract_base__AnalysisKindSpec {
  kind?: "analysis";
  question: string;
  queryPlanRef: string;
  refreshPolicyRef?: string | null;
  alertPolicyRef?: string | null;
  dashboard?: DashboardPresentationSpec | null;
}

export interface frontend__server__knowledge_assets__contract_base__GraphOntologyKindSpec {
  kind?: "graph_ontology";
  entitySchemaRef: SchemaRef;
  relationshipSchemaRef: SchemaRef;
  constraintRefs?: Array<string>;
  entities?: Array<string>;
  relationships?: Array<GraphRelationSpec>;
  evidencePolicyRef?: PermissionRef | null;
}

export interface frontend__server__knowledge_assets__contract_base__KnowledgeKindSpec {
  kind?: "knowledge";
  retrievalMode?: "hybrid" | "vector" | "keyword";
  sourceRevisionRefs?: Array<string>;
  citationPolicyRef?: PermissionRef | null;
  refusalPolicyRef?: string | null;
}

export interface frontend__server__knowledge_assets__contract_base__MonitoringKindSpec {
  kind?: "monitoring";
  metricRefs?: Array<string>;
  refreshScheduleRef: string;
  alertPolicyRef: string;
  actionPolicyRef?: PermissionRef | null;
}

export interface frontend__server__knowledge_assets__contract_base__SemanticKindSpec {
  kind?: "semantic";
  metricRefs?: Array<string>;
  dimensionRefs?: Array<string>;
  relationshipRefs?: Array<string>;
  queryPolicyRef?: PermissionRef | null;
}

export interface frontend__server__knowledge_assets__contract_base__SopKindSpec {
  kind?: "sop";
  trigger: string;
  scope: string;
  inputFields: Array<SopInputField>;
  steps: Array<SopStep>;
  outputs?: Array<SopOutputField>;
  failureHandling: string;
  actionProposal: string;
}

export interface frontend__server__knowledge_assets__contract_views__EvaluationCase {
  id: string;
  inputRef: StorageRef;
  expectedOutputRef?: StorageRef | null;
  source?: "manual" | "historical" | "batch" | "agent_candidate";
}

export interface frontend__server__knowledge_assets__contract_views__EvaluationCaseResult {
  caseId: string;
  status: "passed" | "failed" | "skipped";
  score: number;
  evidenceRef?: StorageRef | null;
  regressionDiffRef?: StorageRef | null;
}

export interface frontend__server__knowledge_assets__contract_views__EvaluationRun {
  id: string;
  suiteId: string;
  suiteVersion: number;
  skillRevisionId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  score?: number | null;
  evidenceRef?: StorageRef | null;
  regressionRef?: StorageRef | null;
  environment?: "production" | "demo" | "test";
  dependencyRevisionRefs?: Array<string>;
  dataRevisionRefs?: Array<string>;
  caseResults?: Array<frontend__server__knowledge_assets__contract_views__EvaluationCaseResult>;
  startedAt: string;
  finishedAt?: string | null;
}

export interface frontend__server__knowledge_assets__contract_views__EvaluationSuite {
  id: string;
  version: number;
  skillId: string;
  caseCount: number;
  casesRef: StorageRef;
  passThreshold: number;
  environment?: "production" | "demo" | "test";
  caseIds?: Array<string>;
}

export interface frontend__server__knowledge_assets__contract_views__PolicyGateResult {
  id: string;
  skillRevisionId: string;
  evaluationRunId: string;
  decision: "publishable" | "blocked";
  reasons?: Array<string>;
  machineReasons?: Array<string>;
  checkedAt: string;
}

export interface frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase {
  id: string;
  source: CaseSource;
  category: CaseCategory;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  grading?: Record<string, unknown>;
  provenanceRef?: string | null;
  candidateConfirmed?: boolean;
  createdAt?: string;
}

export interface frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCaseResult {
  caseId: string;
  status: "passed" | "failed" | "cancelled";
  score: number;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  actual?: Record<string, unknown> | null;
  grading?: Record<string, unknown>;
  evidence?: Array<string>;
  traceRef?: string | null;
  regressionDiff?: Record<string, unknown>;
  durationMs?: number | null;
}

export interface frontend__server__knowledge_assets__evaluation_quality__models__EvaluationRun {
  id: string;
  provenance: RunProvenance;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  selectedCaseIds: Array<string>;
  caseResults?: Array<frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCaseResult>;
  attempt?: number;
  retryOf?: string | null;
  createdAt?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export interface frontend__server__knowledge_assets__evaluation_quality__models__EvaluationSuite {
  id: string;
  version: number;
  skillId: string;
  cases: Array<frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase>;
  passThreshold?: number;
  createdAt?: string;
  digest: string;
}

export interface frontend__server__knowledge_assets__evaluation_quality__models__PolicyGateResult {
  id: string;
  skillDraftRevision: string;
  evaluationRunId: string;
  decision: "publishable" | "blocked";
  checks: Array<PolicyCheck>;
  machineReasons: Array<string>;
  checkedAt?: string;
}

export interface frontend__server__skill_authoring__models__AnalysisKindSpec {
  kind?: "analysis";
  query_plan: QueryPlan;
  analysis_shape?: "kpi" | "trend" | "table" | "funnel" | "breakdown";
  unit?: string | null;
}

export interface frontend__server__skill_authoring__models__GraphOntologyKindSpec {
  kind?: "graph_ontology";
  entity_types: Array<string>;
  relation_types?: Array<string>;
  mapping_intent?: Array<string>;
}

export interface frontend__server__skill_authoring__models__KnowledgeKindSpec {
  kind?: "knowledge";
  citation_intent: Array<string>;
  retrieval_mode?: "hybrid" | "semantic" | "exact";
}

export interface frontend__server__skill_authoring__models__MonitoringKindSpec {
  kind?: "monitoring";
  metric: string;
  threshold: number;
  comparator: "gt" | "gte" | "lt" | "lte" | "change_rate";
  duration_minutes?: number;
  refresh_seconds?: number;
}

export interface frontend__server__skill_authoring__models__SemanticKindSpec {
  kind?: "semantic";
  entities: Array<string>;
  relationships?: Array<string>;
  dimensions?: Array<string>;
  measures?: Array<string>;
}

export interface frontend__server__skill_authoring__models__SopKindSpec {
  kind?: "sop";
  trigger: string;
  scope: string;
  input_fields: Array<SopPlanInput>;
  steps: Array<SopPlanStep>;
  outputs?: Array<SopPlanOutput>;
  failure_handling: string;
  action_proposal: string;
}