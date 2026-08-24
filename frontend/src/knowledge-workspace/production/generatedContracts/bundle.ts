/* Generated from contracts.py; do not edit manually. */

import type { ActionCommand, ActionUpdatePayload, AgentBinding, AlertEvent, AnalysisKindSpec, ArtifactExportCommand, ArtifactExportPayload, AssistantCommand, AssistantTurnPayload, Audit, ChartSeries, ChartViewModel, CleanRun, CleaningRecipe, CommandResponse, CompatibilityTargets, ConnectorCommand, ConnectorPayload, CreateSkillDraftCommand, CreateSkillDraftPayload, DashboardKpi, DashboardViewModel, DataAccessKindSpec, DatabaseConnectorConfig, DraftCommandResult, ErrorEnvelope, EvaluationCommand } from "./part1";
import type { EvaluationPayload, EvaluationRun, EvaluationSuite, Event, FileConnectorConfig, GoldenAssetRevision, GraphEdge, GraphNode, GraphOntologyKindSpec, GraphOntologyViewModel, ImportCommand, ImportPayload, Invocation, InvocationStartCommand, InvocationStartPayload, InvocationStartResult, JobEvent, JobState, KnowledgeCitation, KnowledgeKindSpec, KnowledgeViewModel, LegacySkillManifestInput, ManifestInputSchema, ManifestProperty, McpConnectorConfig, MonitoringKindSpec, MonitoringViewModel } from "./part2";
import type { NotReadyCommandResult, Operation, OwnerRef, PermissionRef, PolicyGateResult, ProfileRun, ProviderDocumentConfig, PublicationPublishCommand, PublicationPublishPayload, PublicationPublishResult, PublishedSkillConnectorConfig, PublishedSkillVersion, RefreshRun, RefreshRunCommand, RefreshRunPayload, RefreshRunResult, ResourceCommand, ResourcePayload, SaveManifestCommand, SaveManifestPayload, SchemaRef, SecretRef, SemanticKindSpec, SemanticViewModel, SkillContract, SkillDependencies, SkillDraft } from "./part3";
import type { SkillDraftRevision, SkillDraftRunCommand, SkillDraftRunPayload, SkillDraftRunResult, SkillManifest, SkillManifestAction, SkillMetadata, SkillOperation, SkillResult, SkillSpec, SkillViewManifest, SkillViewRevision, SourceCleanCommand, SourceCleanPayload, SourceCleanResult, SourceProfileCommand, SourceProfilePayload, SourceProfileResult, SourceRevision, StorageRef, StreamCancelCommand, StreamCancelPayload, ViewCell, ViewField, ViewIntent, WebConnectorConfig } from "./part4";

export interface CoreContractBundle {
  sourceRevision?: SourceRevision | null;
  profileRun?: ProfileRun | null;
  cleaningRecipe?: CleaningRecipe | null;
  cleanRun?: CleanRun | null;
  goldenAssetRevision?: GoldenAssetRevision | null;
  skillDraftRevision?: SkillDraftRevision | null;
  skillResult?: SkillResult | null;
  viewIntent?: ViewIntent | null;
  viewModel?: DashboardViewModel | ChartViewModel | SemanticViewModel | KnowledgeViewModel | GraphOntologyViewModel | MonitoringViewModel | null;
  skillViewManifest?: SkillViewManifest | null;
  skillViewRevision?: SkillViewRevision | null;
  evaluationSuite?: EvaluationSuite | null;
  evaluationRun?: EvaluationRun | null;
  policyGateResult?: PolicyGateResult | null;
  publishedSkillVersion?: PublishedSkillVersion | null;
  agentBinding?: AgentBinding | null;
  invocation?: Invocation | null;
  refreshRun?: RefreshRun | null;
  alertEvent?: AlertEvent | null;
  legacySkillManifestInput?: LegacySkillManifestInput | null;
  commandRequest?: CreateSkillDraftCommand | SaveManifestCommand | ResourceCommand | ConnectorCommand | ImportCommand | StreamCancelCommand | AssistantCommand | EvaluationCommand | ActionCommand | ArtifactExportCommand | SourceProfileCommand | SourceCleanCommand | SkillDraftRunCommand | PublicationPublishCommand | RefreshRunCommand | InvocationStartCommand | null;
  commandResult?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | null;
  commandResponse?: CommandResponse | null;
  operation?: Operation | null;
  event?: Event | null;
  audit?: Audit | null;
  jobState?: JobState | null;
  jobEvent?: JobEvent | null;
  connectorConfig?: FileConnectorConfig | ProviderDocumentConfig | DatabaseConnectorConfig | WebConnectorConfig | McpConnectorConfig | PublishedSkillConnectorConfig | null;
}
