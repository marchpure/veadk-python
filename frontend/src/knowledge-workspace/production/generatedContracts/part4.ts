/* Generated from contracts.py; do not edit manually. */

import type { AnalysisKindSpec, CaseCategory, CaseSource, ChartViewModel, CleanRun, CompatibilityTargets, DashboardViewModel, DataAccessKindSpec, ErrorEnvelope } from "./part1";
import type { GoldenAssetRevision, GraphOntologyKindSpec, GraphOntologyViewModel, KnowledgeKindSpec } from "./part2";
import type { KnowledgeViewModel, MonitoringKindSpec, MonitoringViewModel, OwnerRef, PatchOperation, PermissionRef, PolicyCheck, ProfileRun, RunProvenance, SchemaRef, SecretRef, SemanticKindSpec, SemanticViewModel, SkillContract, SkillDependencies } from "./part3";

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

export interface SkillManifest {
  apiVersion?: "knowledge.veadk.io/v1alpha1";
  kind?: "Skill";
  metadata: SkillMetadata;
  spec: SkillSpec;
}

export interface SkillManifestAction {
  name: string;
  description?: string;
}

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
  kind: "data_access" | "semantic" | "analysis" | "knowledge" | "graph_ontology" | "monitoring";
  outputSchemaRef: SchemaRef;
  resultRef: StorageRef;
  sourceRevisionRefs?: Array<string>;
  goldenAssetRevisionRefs?: Array<string>;
  traceId: string;
  freshnessAt?: string | null;
}

export interface SkillSpec {
  kind: "data_access" | "semantic" | "analysis" | "knowledge" | "graph_ontology" | "monitoring";
  contract: SkillContract;
  dependencies?: SkillDependencies;
  policyRef: PermissionRef;
  runtimeRef: string;
  evaluationSuiteRef?: string | null;
  skillViewRef?: string | null;
  compatibility?: CompatibilityTargets;
  kindSpec: DataAccessKindSpec | SemanticKindSpec | AnalysisKindSpec | KnowledgeKindSpec | GraphOntologyKindSpec | MonitoringKindSpec;
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
  viewModel: DashboardViewModel | ChartViewModel | SemanticViewModel | KnowledgeViewModel | GraphOntologyViewModel | MonitoringViewModel;
  invocationId?: string | null;
  resultRef?: StorageRef | null;
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
  template: "dashboard" | "chart" | "semantic" | "knowledge" | "graph_ontology" | "monitoring";
  purpose: "overview" | "compare" | "schema" | "answer" | "explore" | "monitor";
  resultRef: string;
}

export interface WebConnectorConfig {
  kind: "web_api" | "web_url" | "rest_api" | "graphql" | "openapi";
  endpoint: string;
  secretRef?: SecretRef | null;
  termsRef?: string | null;
  operationAllowlist?: Array<string>;
  pageSize?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
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