/* Generated from contracts.py; do not edit manually. */

import type { EvaluationPayload, InvocationStartResult, NotReadyCommandResult } from "./part2";
import type { PermissionRef, PublicationPublishResult, RefreshRunResult, SecretRef, SkillDraft } from "./part3";
import type { SkillDraftRunResult, SourceCleanResult, SourceProfileResult, StorageRef, ViewCell, ViewField } from "./part4";

export interface ActionCommand {
  command: "action.update";
  payload: ActionUpdatePayload;
}

export interface ActionUpdatePayload {
  actionId: string;
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

export interface AnalysisKindSpec {
  kind?: "analysis";
  question: string;
  queryPlanRef: string;
  refreshPolicyRef?: string | null;
  alertPolicyRef?: string | null;
}

export interface ArtifactExportCommand {
  command: "artifact.export";
  payload: ArtifactExportPayload;
}

export interface ArtifactExportPayload {
  resourceId: string;
  format: "json" | "csv" | "html";
}

export interface AssistantCommand {
  command: "assistant.turn";
  payload: AssistantTurnPayload;
}

export interface AssistantTurnPayload {
  text: string;
  contextIds?: Array<string>;
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

export interface ChartSeries {
  name: string;
  points?: Array<[string, number]>;
}

export interface ChartViewModel {
  template?: "chart";
  title: string;
  xField: string;
  yField: string;
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

export interface CleaningRecipe {
  id: string;
  version: number;
  operations?: Array<"trim" | "deduplicate" | "normalize" | "split" | "map" | "redact">;
  configRef?: StorageRef | null;
  sourceRevisionId: string;
  recipeDigest: string;
}

export interface CommandResponse {
  accepted: boolean;
  requestId: string;
  operationId?: string | null;
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | null;
}

export interface CompatibilityTargets {
  targets?: Array<"agentkit" | "mcp" | "openapi" | "codex">;
}

export interface ConnectorCommand {
  command: "connector.create" | "connector.test";
  payload: ConnectorPayload;
}

export interface ConnectorPayload {
  connectorKey: string;
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

export interface DashboardKpi {
  key: string;
  label: string;
  value: string | number;
  unit?: string;
  trend?: "up" | "down" | "flat" | "unknown";
}

export interface DashboardViewModel {
  template?: "dashboard";
  fields?: Array<ViewField>;
  kpis?: Array<DashboardKpi>;
  rows?: Array<Array<ViewCell>>;
  dataRef: StorageRef;
}

export interface DataAccessKindSpec {
  kind?: "data_access";
  connectorType: "oracle" | "mysql" | "postgresql" | "csv" | "excel" | "web_api" | "mcp" | "local_file";
  endpointRef: string;
  secretRef?: SecretRef | null;
  allowedSchemas?: Array<string>;
  allowedTables?: Array<string>;
  allowedOperations?: Array<"introspect" | "query" | "read" | "subscribe" | "search">;
  rowPolicyRef?: PermissionRef | null;
  columnPolicyRef?: PermissionRef | null;
}

export interface DraftCommandResult {
  resultType: "skill-draft.create" | "skill-draft.save-manifest";
  error?: ErrorEnvelope | null;
  draft: SkillDraft;
  replayed?: boolean;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  retryable: boolean;
  requestId: string;
  details?: Record<string, string> | null;
}

export interface EvaluationCommand {
  command: "evaluation.run" | "evaluation.apply";
  payload: EvaluationPayload;
}