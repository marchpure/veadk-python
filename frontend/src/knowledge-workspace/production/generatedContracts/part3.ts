/* Generated from contracts.py; do not edit manually. */

import type { AddCitationIntentPatch, AgentAnswer, AgentExecutionEvidence, ArtifactRef, AuthoringEvent, AuthoringOperation, ContextRevisionRef, DraftRevision, ErrorEnvelope } from "./part1";
import type { FreshnessPolicy, GoldenAssetRevision, JsonValue, LegacySkillManifestInput, PatchProposal } from "./part2";
import type { SkillMetadata, SkillOperation, SkillResult, SkillSpec, SkillViewRevision, SkillViewShareGrant, StorageRef, TemplateRef, ViewIntent } from "./part4";

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

export interface PostgresqlConnectorConfig {
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
  kind: "postgresql";
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
  kind: "golden_asset" | "document" | "knowledge" | "semantic" | "graph" | "skill" | "artifact" | "data_access_skill" | "knowledge_asset";
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

export interface RestApiConnectorConfig {
  endpoint: string;
  secretRef?: SecretRef | null;
  operationAllowlist: Array<string>;
  maxRows?: number;
  maxResponseBytes?: number;
  rateLimitPerMinute?: number;
  timeoutSeconds?: number;
  refreshSeconds?: number;
  kind: "rest_api";
  paginationMode?: "none" | "cursor" | "offset" | "link_header";
  pageSize?: number;
  maxPages?: number;
  termsRef?: string | null;
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

export interface S3ConnectorConfig {
  secretRef: SecretRef;
  bucket: string;
  objectPrefix?: string;
  region?: string | null;
  maxObjects?: number;
  maxObjectBytes?: number;
  timeoutSeconds?: number;
  kind: "s3";
  endpoint?: string | null;
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

export interface SemanticViewField {
  name: string;
  role: "entity" | "dimension" | "measure" | "time";
  aggregation?: "sum" | "count" | "avg" | "min" | "max" | "none";
  unit?: string;
  sourceField: string;
  primaryKey?: boolean;
}

export interface SemanticViewModel {
  template?: "semantic";
  schemaRef: SchemaRef;
  metricRefs?: Array<string>;
  dimensionRefs?: Array<string>;
  relationshipRefs?: Array<string>;
  dataRef?: StorageRef | null;
  entities?: Array<string>;
  fields?: Array<SemanticViewField>;
  relationships?: Array<SemanticViewRelationship>;
  mdl?: string;
  ambiguities?: Array<string>;
  dependencyErrors?: Array<string>;
}

export interface SemanticViewRelationship {
  source: string;
  target: string;
  relation: string;
  joinType: "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many";
  evidenceLocator: string;
  confidence?: number | null;
}

export interface SetDashboardChartPatch {
  patch_type?: "set_dashboard_chart";
  x_field: string;
  y_field: string;
  chart_type?: "line" | "bar" | "area" | "table";
}

export interface SetDashboardFilterPatch {
  patch_type?: "set_dashboard_filter";
  field: string;
  value: string;
}

export interface SetDashboardKpiPatch {
  patch_type?: "set_dashboard_kpi";
  key: string;
  label?: string | null;
  value: number | string;
  unit?: string;
}

export interface SetDescriptionPatch {
  patch_type?: "set_description";
  description: string;
}

export interface SetGraphEntityPatch {
  patch_type?: "set_graph_entity";
  entity_type: string;
  label: string;
}

export interface SetGraphRelationPatch {
  patch_type?: "set_graph_relation";
  relation: string;
  source_type: string;
  target_type: string;
}

export interface SetPermissionScopePatch {
  patch_type?: "set_permission_scope";
  permissions: Array<string>;
}

export interface SetQueryPlanPatch {
  patch_type?: "set_query_plan";
  query_plan: QueryPlan;
}

export interface SetRefreshPolicyPatch {
  patch_type?: "set_refresh_policy";
  freshness: FreshnessPolicy;
}

export interface SetSemanticDimensionPatch {
  patch_type?: "set_semantic_dimension";
  dimension: string;
  field: string;
}

export interface SetSemanticMappingPatch {
  patch_type?: "set_semantic_mapping";
  field: string;
  entity: string;
}

export interface SetSemanticMetricPatch {
  patch_type?: "set_semantic_metric";
  metric: string;
  definition: string;
}

export interface SetSemanticRelationshipPatch {
  patch_type?: "set_semantic_relationship";
  relationship: string;
  source_entity: string;
  target_entity: string;
}

export interface SetSopConditionPatch {
  patch_type?: "set_sop_condition";
  step_id: string;
  condition: string;
}

export interface SetSopStepPatch {
  patch_type?: "set_sop_step";
  step_id: string;
  label: string;
  condition?: string | null;
  tool_ref?: string | null;
}

export interface SetSopToolRefPatch {
  patch_type?: "set_sop_tool_ref";
  step_id: string;
  tool_ref: string;
}

export interface SetThresholdPolicyPatch {
  patch_type?: "set_threshold_policy";
  threshold: number;
  comparator: "gt" | "gte" | "lt" | "lte" | "change_rate";
}

export interface SetTitlePatch {
  patch_type?: "set_title";
  title: string;
}

export interface SkillAuthoringAnswerCommand {
  command: "skill-authoring.answer";
  payload: SkillAuthoringAnswerPayload;
}

export interface SkillAuthoringAnswerPayload {
  prompt: string;
  resourceRefs?: Array<ResourceRef>;
  permissions?: Array<string>;
  fixedRevisions?: Array<string>;
  currentSkillId?: string | null;
  currentViewId?: string | null;
  currentComponentId?: string | null;
  commentIds?: Array<string>;
}

export interface SkillAuthoringAnswerResult {
  resultType?: "skill-authoring.answer";
  error?: ErrorEnvelope | null;
  status?: "succeeded" | "awaiting_input" | "credential_blocked" | "failed";
  answer?: AgentAnswer | null;
  agentExecution?: AgentExecutionEvidence | null;
  contextDigest?: string | null;
  draft?: null;
  artifactResult?: null;
}

export interface SkillAuthoringExecuteCommand {
  command: "skill-authoring.execute";
  payload: SkillAuthoringExecutePayload;
}

export interface SkillAuthoringExecutePayload {
  draftId: string;
  revision?: number | null;
}

export interface SkillAuthoringExecuteResult {
  resultType?: "skill-authoring.execute";
  error?: ErrorEnvelope | null;
  status?: "queued" | "running" | "succeeded" | "ready_for_execution" | "credential_blocked" | "failed" | "cancelled";
  operation?: AuthoringOperation | null;
  draft?: DraftRevision | null;
  events?: Array<AuthoringEvent>;
}

export interface SkillAuthoringPatchCommand {
  command: "skill-authoring.patch";
  payload: SkillAuthoringPatchPayload;
}

export interface SkillAuthoringPatchPayload {
  draftId: string;
  baseRevision: number;
  patch: SetTitlePatch | SetDescriptionPatch | SetQueryPlanPatch | SetRefreshPolicyPatch | SetThresholdPolicyPatch | SetPermissionScopePatch | AddCitationIntentPatch | SetSemanticMappingPatch | SetSemanticMetricPatch | SetSemanticDimensionPatch | SetSemanticRelationshipPatch | SetDashboardKpiPatch | SetDashboardChartPatch | SetDashboardFilterPatch | SetSopStepPatch | SetSopConditionPatch | SetSopToolRefPatch | SetGraphEntityPatch | SetGraphRelationPatch;
}

export interface SkillAuthoringPatchResult {
  resultType?: "skill-authoring.patch";
  error?: ErrorEnvelope | null;
  status?: "succeeded" | "ready_for_execution" | "failed";
  operation?: AuthoringOperation | null;
  draft?: DraftRevision | null;
  patch?: PatchProposal | null;
  events?: Array<AuthoringEvent>;
}

export interface SkillAuthoringStartCommand {
  command: "skill-authoring.start";
  payload: SkillAuthoringStartPayload;
}

export interface SkillAuthoringStartPayload {
  prompt: string;
  conversationId?: string | null;
  resourceRefs?: Array<ResourceRef>;
  permissions?: Array<string>;
  fixedRevisions?: Array<string>;
  requestedKind?: "knowledge" | "semantic" | "analysis" | "sop" | "graph_ontology" | "monitoring" | null;
  scope?: "personal" | "team";
  displayName?: string | null;
  currentSkillId?: string | null;
  currentViewId?: string | null;
  currentComponentId?: string | null;
  commentIds?: Array<string>;
  templateRef?: TemplateRef | null;
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
  templateRef?: TemplateRef | null;
  contextRevisionRefs?: Array<ContextRevisionRef>;
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

export type SkillKind = "knowledge" | "semantic" | "analysis" | "sop" | "graph_ontology" | "monitoring";

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