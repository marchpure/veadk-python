/* Generated from contracts.py; do not edit manually. */

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

export interface EvaluationPayload {
  targetId: string;
}

export interface EvaluationRun {
  id: string;
  suiteId: string;
  suiteVersion: number;
  skillRevisionId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  score?: number | null;
  evidenceRef?: StorageRef | null;
  regressionRef?: StorageRef | null;
  startedAt: string;
  finishedAt?: string | null;
}

export interface EvaluationSuite {
  id: string;
  version: number;
  skillId: string;
  caseCount: number;
  casesRef: StorageRef;
  passThreshold: number;
}

export interface Event {
  schemaVersion?: "knowledge-assets.event.v1";
  operationId: string;
  eventId: string;
  sequence: number;
  occurredAt: string;
  type: "accepted" | "progress" | "succeeded" | "failed" | "cancelled";
  terminal: boolean;
  result?: DraftCommandResult | NotReadyCommandResult | SourceProfileResult | SourceCleanResult | SkillDraftRunResult | PublicationPublishResult | RefreshRunResult | InvocationStartResult | null;
  error?: ErrorEnvelope | null;
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
  inputRef: StorageRef;
  callerId: string;
}

export interface InvocationStartResult {
  resultType?: "invocation.start";
  error?: ErrorEnvelope | null;
  status?: "not_ready";
  skillVersionId: string;
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

export interface MonitoringKindSpec {
  kind?: "monitoring";
  metricRefs?: Array<string>;
  refreshScheduleRef: string;
  alertPolicyRef: string;
  actionPolicyRef?: PermissionRef | null;
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
  qualityScore?: number | null;
  errorCode?: string | null;
  startedAt: string;
  finishedAt?: string | null;
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
  status?: "not_ready";
  skillId: string;
}

export interface ResourceCommand {
  command: "resource.create" | "resource.update" | "resource.publish" | "resource.share" | "resource.revoke";
  payload: ResourcePayload;
}

export interface ResourcePayload {
  resourceId: string;
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
}
