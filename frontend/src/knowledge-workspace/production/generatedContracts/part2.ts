/* Generated from contracts.py; do not edit manually. */

import type { ArtifactExportResult, AssistantTurnResult, DraftCommandResult, ErrorEnvelope } from "./part1";
import type { NotReadyCommandResult, OwnerRef, PermissionRef, PublicationPublishResult, RefreshRunResult, ResourceShareResult, RunProvenance, SchemaRef } from "./part3";
import type { SkillDraftRunResult, SkillResult, SourceCleanResult, SourceProfileResult, StorageRef, TypedPatch, frontend__server__knowledge_assets__contract_views__EvaluationCase, frontend__server__knowledge_assets__contract_views__EvaluationRun, frontend__server__knowledge_assets__contract_views__EvaluationSuite, frontend__server__knowledge_assets__contract_views__PolicyGateResult, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationRun, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationSuite, frontend__server__knowledge_assets__evaluation_quality__models__PolicyGateResult } from "./part4";

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
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | null;
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

export interface KnowledgeKindSpec {
  kind?: "knowledge";
  retrievalMode?: "hybrid" | "vector" | "keyword";
  sourceRevisionRefs?: Array<string>;
  citationPolicyRef?: PermissionRef | null;
  refusalPolicyRef?: string | null;
}