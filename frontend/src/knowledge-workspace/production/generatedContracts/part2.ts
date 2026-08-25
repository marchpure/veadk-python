/* Generated from contracts.py; do not edit manually. */

import type { ArtifactExportResult, ArtifactRef, AssetOwner, AssetPermission, AssistantTurnResult, Audit, DraftCommandResult, ErrorEnvelope } from "./part1";
import type { PermissionRef, PublicationPublishResult, RefreshRunResult, ResourceShareResult, RunProvenance, SchemaRef, SecretRef, SkillAuthoringAnswerResult, SkillAuthoringExecuteResult, SkillAuthoringPatchResult, SkillAuthoringStartResult } from "./part3";
import type { SkillDraftRunResult, SkillManifestAction, SkillResult, SourceCleanResult, SourceGoldenConnectionResult, SourceGoldenIngestResult, SourceProfileResult, StorageRef, TypedPatch, frontend__server__knowledge_assets__contract_views__EvaluationCase, frontend__server__knowledge_assets__contract_views__EvaluationRun, frontend__server__knowledge_assets__contract_views__EvaluationSuite, frontend__server__knowledge_assets__contract_views__PolicyGateResult, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationRun, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationSuite, frontend__server__knowledge_assets__evaluation_quality__models__PolicyGateResult } from "./part4";

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

export interface FileConnectorConfig {
  kind: "markdown" | "csv" | "pdf" | "office" | "excel";
  sourceRef: string;
  maxBytes?: number;
  maxFiles?: number;
  followSymlinks?: false;
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
  lineageDigest: string;
  toolArguments?: Record<string, unknown>;
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
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | SkillAuthoringStartResult | SkillAuthoringAnswerResult | SkillAuthoringPatchResult | SkillAuthoringExecuteResult | SourceGoldenConnectionResult | SourceGoldenIngestResult | null;
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