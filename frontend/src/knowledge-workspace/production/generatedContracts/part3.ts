/* Generated from contracts.py; do not edit manually. */

import type { Audit, DraftCommandResult, ErrorEnvelope } from "./part1";
import type { Event, InvocationStartResult, LegacySkillManifestInput } from "./part2";
import type { SkillDraftRunResult, SkillManifest, SkillOperation, SourceCleanResult, SourceProfileResult, StorageRef } from "./part4";

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
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | null;
  error?: ErrorEnvelope | null;
  nextActions?: Array<string>;
  audit?: Array<Audit>;
}

export interface OwnerRef {
  workspaceId: string;
  principalId: string;
}

export interface PermissionRef {
  uri: string;
  version: string;
}

export interface PolicyGateResult {
  id: string;
  skillRevisionId: string;
  evaluationRunId: string;
  decision: "publishable" | "blocked";
  reasons?: Array<string>;
  checkedAt: string;
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