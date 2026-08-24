/* Generated from contracts.py; do not edit manually. */

import type { AnalysisKindSpec, ChartViewModel, CleanRun, CompatibilityTargets, DashboardViewModel, DataAccessKindSpec, ErrorEnvelope } from "./part1";
import type { GoldenAssetRevision, GraphOntologyKindSpec, GraphOntologyViewModel, KnowledgeKindSpec, KnowledgeViewModel, MonitoringKindSpec, MonitoringViewModel } from "./part2";
import type { OwnerRef, PermissionRef, ProfileRun, SchemaRef, SemanticKindSpec, SemanticViewModel, SkillContract, SkillDependencies } from "./part3";

export interface SkillDraftRunPayload {
  draftId: string;
  revision: number;
  traceId: string;
}

export interface SkillDraftRunResult {
  resultType?: "skill-draft.run";
  error?: ErrorEnvelope | null;
  status?: "not_ready" | "succeeded" | "failed";
  draftId: string;
  goldenAssetRevision?: GoldenAssetRevision | null;
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
  sourceType: "local_file" | "markdown" | "csv" | "pdf" | "document" | "database" | "excel" | "web_api" | "mcp";
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