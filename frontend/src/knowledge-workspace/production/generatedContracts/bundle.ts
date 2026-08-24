/* Generated from contracts.py; do not edit manually. */

import type { ActionCommand, ActionUpdatePayload, AgentBinding, AlertEvent, AnalysisKindSpec, ArtifactExportCommand, ArtifactExportPayload, ArtifactExportResult, AssistantCommand, AssistantContextEnvelope, AssistantDiff, AssistantTurnPayload, AssistantTurnResult, Audit, CaseCategory, CaseSource, ChartSeries, ChartViewModel, CleanRun, CleaningRecipe, CommandResponse, CompatibilityTargets, ConnectorCommand, ConnectorPayload, CreateSkillDraftCommand, CreateSkillDraftPayload, DashboardKpi, DashboardViewModel, DataAccessKindSpec, DatabaseConnectorConfig, DraftCommandResult, ErrorEnvelope, EvaluationCaseAdoptHistoryCommand, EvaluationCaseAdoptHistoryPayload, EvaluationCaseConfirmCommand, EvaluationCaseConfirmPayload, EvaluationCaseGenerateCandidateCommand, EvaluationCaseGenerateCandidatePayload, EvaluationCaseImportCommand, EvaluationCaseImportPayload } from "./part1";
import type { EvaluationCommand, EvaluationFixActionPayload, EvaluationFixApplyCommand, EvaluationFixProposeAllCommand, EvaluationFixProposeAllPayload, EvaluationFixProposeCommand, EvaluationFixProposePayload, EvaluationFixUndoCommand, EvaluationPayload, EvaluationQualityCommandResult, EvaluationRunActionPayload, EvaluationRunCancelCommand, EvaluationRunResult, EvaluationRunResumeCommand, EvaluationRunRetryCommand, EvaluationRunRetryPayload, EvaluationRunStartCommand, EvaluationRunStartPayload, EvaluationSuiteCreateCommand, EvaluationSuiteCreatePayload, EvaluationSuiteReviseCommand, EvaluationSuiteRevisePayload, Event, FileConnectorConfig, FixPlan, GoldenAssetRevision, GraphEdge, GraphNode, GraphOntologyKindSpec, GraphOntologyViewModel, ImportCommand, ImportPayload, Invocation, InvocationStartCommand, InvocationStartPayload, InvocationStartResult, JobEvent, JobState, KnowledgeCitation, KnowledgeKindSpec } from "./part2";
import type { KnowledgeViewModel, LegacySkillManifestInput, ManifestInputSchema, ManifestProperty, McpConnectorConfig, MonitoringKindSpec, MonitoringViewModel, NotReadyCommandResult, Operation, OwnerRef, PatchOperation, PermissionRef, PolicyCheck, PolicyGateEvaluateCommand, PolicyGateEvaluatePayload, ProfileRun, ProviderDocumentConfig, PublicationPublishCommand, PublicationPublishPayload, PublicationPublishResult, PublishedSkillConnectorConfig, PublishedSkillVersion, RefreshRun, RefreshRunCommand, RefreshRunPayload, RefreshRunResult, ResourceCommand, ResourcePayload, ResourceShareResult, RunProvenance, SaveManifestCommand, SaveManifestPayload, SchemaRef, SecretRef, SemanticKindSpec, SemanticViewModel, SkillContract, SkillDependencies, SkillDraft, SkillDraftRetryCommand } from "./part3";
import type { SkillDraftRetryPayload, SkillDraftRevision, SkillDraftRunCommand, SkillDraftRunPayload, SkillDraftRunResult, SkillManifest, SkillManifestAction, SkillMetadata, SkillOperation, SkillPatch, SkillResult, SkillSpec, SkillViewManifest, SkillViewRevision, SkillViewShareGrant, SourceCleanCommand, SourceCleanPayload, SourceCleanResult, SourceProfileCommand, SourceProfilePayload, SourceProfileResult, SourceRevision, StorageRef, StreamCancelCommand, StreamCancelPayload, TypedPatch, ViewCell, ViewField, ViewIntent, WebConnectorConfig, frontend__server__knowledge_assets__contract_views__EvaluationCase, frontend__server__knowledge_assets__contract_views__EvaluationCaseResult, frontend__server__knowledge_assets__contract_views__EvaluationRun, frontend__server__knowledge_assets__contract_views__EvaluationSuite, frontend__server__knowledge_assets__contract_views__PolicyGateResult, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCase, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationCaseResult, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationRun, frontend__server__knowledge_assets__evaluation_quality__models__EvaluationSuite, frontend__server__knowledge_assets__evaluation_quality__models__PolicyGateResult } from "./part4";

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
  evaluationSuite?: frontend__server__knowledge_assets__contract_views__EvaluationSuite | null;
  evaluationRun?: frontend__server__knowledge_assets__contract_views__EvaluationRun | null;
  policyGateResult?: frontend__server__knowledge_assets__contract_views__PolicyGateResult | null;
  publishedSkillVersion?: PublishedSkillVersion | null;
  agentBinding?: AgentBinding | null;
  invocation?: Invocation | null;
  refreshRun?: RefreshRun | null;
  alertEvent?: AlertEvent | null;
  legacySkillManifestInput?: LegacySkillManifestInput | null;
  commandRequest?: CreateSkillDraftCommand | SaveManifestCommand | ResourceCommand | ConnectorCommand | ImportCommand | StreamCancelCommand | AssistantCommand | EvaluationCommand | EvaluationSuiteCreateCommand | EvaluationSuiteReviseCommand | EvaluationCaseImportCommand | EvaluationCaseAdoptHistoryCommand | EvaluationCaseGenerateCandidateCommand | EvaluationCaseConfirmCommand | EvaluationRunStartCommand | EvaluationRunCancelCommand | EvaluationRunResumeCommand | EvaluationRunRetryCommand | EvaluationFixProposeCommand | EvaluationFixProposeAllCommand | EvaluationFixApplyCommand | EvaluationFixUndoCommand | PolicyGateEvaluateCommand | ActionCommand | ArtifactExportCommand | SourceProfileCommand | SourceCleanCommand | SkillDraftRunCommand | SkillDraftRetryCommand | PublicationPublishCommand | RefreshRunCommand | InvocationStartCommand | null;
  commandResult?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | AssistantTurnResult | ArtifactExportResult | ResourceShareResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | EvaluationRunResult | EvaluationQualityCommandResult | null;
  commandResponse?: CommandResponse | null;
  operation?: Operation | null;
  event?: Event | null;
  audit?: Audit | null;
  jobState?: JobState | null;
  jobEvent?: JobEvent | null;
  connectorConfig?: FileConnectorConfig | ProviderDocumentConfig | DatabaseConnectorConfig | WebConnectorConfig | McpConnectorConfig | PublishedSkillConnectorConfig | null;
}
