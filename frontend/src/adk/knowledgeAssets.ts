export type KnowledgeAssetType =
  | "knowledge_resource"
  | "semantic_model"
  | "dashboard";

export type KnowledgeCapabilityKind =
  | "retrieval_binding"
  | "semantic_skill"
  | "dashboard_skill";

export type KnowledgePublishState =
  | "draft"
  | "validating"
  | "blocked"
  | "published"
  | "archived";

export interface KnowledgeAssetSpace {
  id: string;
  name: string;
  description?: string | null;
  default_knowledge_base_id?: string | null;
  region?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface KnowledgeAssetSource {
  id: string;
  space_id: string;
  source_type: string;
  provider?: string | null;
  name: string;
  description?: string | null;
  uri?: string | null;
  locator?: Record<string, unknown>;
  status: string;
  status_reason?: string | null;
  default_index_policy?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface KnowledgeAssetGate {
  score?: number;
  passed?: number;
  total?: number;
  blockers?: string[];
  [key: string]: unknown;
}

export interface KnowledgeAssetMetadata {
  schema_version: "knowledge_asset.metadata.v1";
  package_id?: string;
  space_id?: string | null;
  asset_type: KnowledgeAssetType;
  asset_id: string;
  capability_kind: KnowledgeCapabilityKind;
  name: string;
  description?: string | null;
  status: string;
  publish_state: KnowledgePublishState;
  gate?: KnowledgeAssetGate | null;
  version?: string | null;
  consumers?: string[];
  capabilities?: Record<string, unknown>;
  capability_package?: Record<string, unknown>;
  query_url?: string | null;
  freshness?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  usage_policy?: Record<string, unknown>;
  sample_evidence?: Array<Record<string, unknown>>;
}

export interface KnowledgeAssetListResponse {
  schema_version?: "knowledge_asset.list.v1";
  items: KnowledgeAssetMetadata[];
  total: number;
  next_cursor?: string | null;
  mock?: boolean;
}

export interface KnowledgeAssetBuildJob {
  id: string;
  space_id?: string | null;
  source_id?: string | null;
  asset_type?: KnowledgeAssetType | null;
  asset_id?: string | null;
  job_type: string;
  status: string;
  logs_ref?: string | null;
  result_skill_id?: string | null;
  error?: Record<string, unknown> | null;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface KnowledgeAssetSnapshot {
  id: string;
  source_id?: string | null;
  kind?: string | null;
  artifact_uri?: string | null;
  schema?: Record<string, unknown>;
  profile?: Record<string, unknown>;
  content_hash?: string | null;
  metadata?: KnowledgeAssetMetadata;
  created_at?: string;
}

export interface KnowledgeAssetSidecar {
  id: string;
  label: string;
  role: string;
  configured: boolean;
  status: "available" | "not_configured" | string;
  debug_url?: string;
  mock?: boolean;
}

export interface KnowledgeAssetOverview {
  space_id?: string;
  spaces?: KnowledgeAssetSpace[];
  source_counts?: Record<string, number>;
  capability_counts?: Record<string, number>;
  recent_jobs?: KnowledgeAssetBuildJob[];
  next_actions?: Array<Record<string, string>>;
  mock?: boolean;
}

export interface KnowledgeAssetImportResult {
  source: KnowledgeAssetSource;
  job: KnowledgeAssetBuildJob;
  document?: Record<string, unknown> | null;
}

export interface AskDataQueryResult {
  schema: "agentkit.askdata.result.v1";
  status: "completed" | "blocked" | string;
  asset: {
    type: "semantic_model";
    id: string;
    name: string;
    version?: string;
  };
  data: {
    rows: Array<Record<string, unknown>>;
    returnedCount?: number;
    metric?: Record<string, unknown>;
    dimensions?: Array<Record<string, unknown>>;
    sql: string;
    metricDefinition: string | Record<string, unknown>;
    policyDecision: Record<string, unknown>;
    freshness: Record<string, unknown>;
    evidence?: Array<Record<string, unknown>>;
    lineage?: Array<Record<string, unknown>>;
    execution?: Record<string, unknown>;
  };
  mock?: boolean;
}

export interface AskDataStreamInput {
  semantic_asset_id: string;
  message: string;
  conversation_id?: string;
  session_id?: string;
  dashboard_intent?: string;
  metric?: string;
  dimension?: string;
  dimensions?: string[];
  filters?: Record<string, unknown>;
  time_range?: Record<string, unknown>;
  mode?: string;
  limit?: number;
}

export interface DashboardSkillBuildResult {
  schema: "agentkit.dashboard_skill_build.v1";
  job_id: string;
  status: string;
  dashboard_asset_id: string;
  dashboard: KnowledgeAssetMetadata;
  askdata?: AskDataQueryResult;
  preview?: Record<string, unknown>;
  mock?: boolean;
}

export interface DashboardShare {
  share_id: string;
  asset_type: "dashboard" | string;
  asset_id: string;
  asset_version?: string | null;
  title: string;
  created_at?: string | null;
  expires_at?: string | null;
  revoked_at?: string | null;
  visibility: "local_link" | "workspace" | string;
  sanitized_snapshot: Record<string, unknown>;
  share_url: string;
  mock?: boolean;
}

export type KnowledgeAssetEvalTargetKind =
  | "semantic_skill"
  | "asktable_query"
  | "asktable"
  | "dashboard_skill";

export type KnowledgeAssetEvalRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "blocked";

export type KnowledgeAssetEvalResultStatus = "passed" | "failed" | "blocked";

export type KnowledgeAssetEvalModelStatus =
  | "not_configured"
  | "skipped"
  | "succeeded"
  | "failed";

export interface KnowledgeAssetEvalSuite {
  id: string;
  spaceId: string;
  name: string;
  description?: string;
  targetKind: KnowledgeAssetEvalTargetKind;
  targetAssetId: string;
  caseCount: number;
  createdAt: string;
  updatedAt: string;
  mock?: boolean;
}

export interface KnowledgeAssetEvalCase {
  id: string;
  suiteId: string;
  targetKind: KnowledgeAssetEvalTargetKind;
  input: string;
  question: string;
  intent: string;
  expectedMetric: string;
  expectedDimensions: string[];
  expectedSqlContains: string[];
  expectedPolicyDecision: string;
  expectedDashboardTiles: string[];
  expectedEvidenceKeys: string[];
  tags: string[];
  createdAt: string;
  mock?: boolean;
}

export interface KnowledgeAssetEvalCaseInput {
  targetKind?: KnowledgeAssetEvalTargetKind;
  input?: string;
  question?: string;
  intent?: string;
  expectedMetric?: string;
  expectedDimensions?: string[];
  expectedSqlContains?: string[];
  expectedPolicyDecision?: string;
  expectedDashboardTiles?: string[];
  expectedEvidenceKeys?: string[];
  tags?: string[];
}

export interface KnowledgeAssetEvalCaseImportResult {
  items: KnowledgeAssetEvalCase[];
  imported: number;
  mock?: boolean;
}

export interface KnowledgeAssetEvalRun {
  id: string;
  suiteId: string;
  targetKind: KnowledgeAssetEvalTargetKind;
  targetAssetId: string;
  status: KnowledgeAssetEvalRunStatus;
  score: number;
  startedAt?: string | null;
  completedAt?: string | null;
  modelStatus: KnowledgeAssetEvalModelStatus;
  generationMode: string;
  resultSummary: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeAssetEvalResult {
  id: string;
  runId: string;
  caseId: string;
  status: KnowledgeAssetEvalResultStatus;
  score: number;
  reason: string;
  actualOutput?: unknown;
  actualSql: string;
  actualRowsPreview: Array<Record<string, unknown>>;
  actualPolicyDecision: Record<string, unknown>;
  actualFreshness: Record<string, unknown>;
  toolCalls: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  dashboardSpecDiff: Record<string, unknown>;
  createdAt: string;
}

export interface KnowledgeAssetEvalRunDetail {
  run: KnowledgeAssetEvalRun;
  suite: KnowledgeAssetEvalSuite;
  cases: KnowledgeAssetEvalCase[];
  results: KnowledgeAssetEvalResult[];
  mock?: boolean;
}

export interface KnowledgeAssetOptimizationSuggestion {
  suggestion: string;
  reason: string;
}

export interface KnowledgeAssetOptimizationGroup {
  priority: "high" | "medium" | "low";
  module:
    | "semantic_model"
    | "metric_definition"
    | "relationship"
    | "policy"
    | "freshness"
    | "query_tool"
    | "dashboard_layout"
    | "evidence"
    | "other";
  customModule?: string | null;
  items: KnowledgeAssetOptimizationSuggestion[];
}

export interface KnowledgeAssetOptimizationSnapshot {
  targetKind: KnowledgeAssetEvalTargetKind;
  targetAssetId: string;
  generatedAt: string;
  sourceRunIds: string[];
  groups: KnowledgeAssetOptimizationGroup[];
}

export interface SemanticBuildEvent {
  event_type: string;
  sequence?: number;
  created_at?: string;
  payload: Record<string, unknown>;
}

export interface SemanticQuestionSqlPair {
  id: string;
  space_id: string;
  semantic_pack_id?: string | null;
  question: string;
  sql: string;
  dialect: string;
  tables: string[];
  notes?: string;
  created_at?: string;
  updated_at?: string;
}

export interface SemanticInstruction {
  id: string;
  space_id: string;
  semantic_pack_id?: string | null;
  instruction: string;
  questions: string[];
  is_default: boolean;
  scope: string;
  created_at?: string;
  updated_at?: string;
}

export interface SemanticPackDetail {
  schema: "agentkit.semantic_pack.detail.v1";
  semantic_pack_id: string;
  asset: KnowledgeAssetMetadata;
  structured_mdl: Record<string, unknown>;
  doc_graph: Record<string, unknown>;
  alignments: Array<Record<string, unknown>>;
  few_shot: SemanticQuestionSqlPair[];
  instructions: SemanticInstruction[];
  graph_objects: Array<Record<string, unknown>>;
  graph_relations: Array<Record<string, unknown>>;
  provenance: Record<string, unknown>;
  policy: Record<string, unknown>;
  eval_seed: Record<string, unknown>;
  skill_runtime: Record<string, unknown>;
  mock?: boolean;
}

export interface SemanticBuilderRevision {
  schema: "agentkit.semantic_builder.revision.v1";
  id: string;
  conversation_id: string;
  semantic_pack_id?: string | null;
  revision_number: number;
  author_role: string;
  message: string;
  patch: Record<string, unknown>;
  diff: Array<Record<string, unknown>>;
  status: string;
  created_at?: string;
}

export interface SemanticBuilderConversation {
  schema: "agentkit.semantic_builder.conversation.v1";
  id: string;
  space_id: string;
  semantic_pack_id?: string | null;
  draft_pack_id?: string | null;
  title: string;
  source_ids: string[];
  document_source_ids: string[];
  snapshot_ids: string[];
  metadata: Record<string, unknown>;
  revisions: SemanticBuilderRevision[];
  created_at?: string;
  updated_at?: string;
  mock?: boolean;
}

export interface SemanticBuilderRefineResult extends SemanticBuilderConversation {
  latest_revision: SemanticBuilderRevision;
  draft: SemanticPackDetail;
  diff: Array<Record<string, unknown>>;
}

export interface SemanticBuilderViewDraftResult {
  schema: "agentkit.semantic_builder.view_draft.v1";
  semantic_pack_id: string;
  view: Record<string, unknown>;
  diff: Array<Record<string, unknown>>;
  conversation_id?: string;
  revision?: SemanticBuilderRevision;
  draft: SemanticPackDetail;
  mock?: boolean;
}

export interface SemanticBuilderPublishResult {
  schema: "agentkit.semantic_builder.publish.v1";
  semantic_pack_id: string;
  asset: KnowledgeAssetMetadata;
  publish_state: KnowledgePublishState;
  conversation_id?: string;
  revision?: SemanticBuilderRevision;
  mock?: boolean;
}

export class KnowledgeAssetError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, message: string, code = "") {
    super(message);
    this.name = "KnowledgeAssetError";
    this.status = status;
    this.code = code;
  }
}

async function errorMessage(res: Response, fallback: string): Promise<{
  code: string;
  message: string;
}> {
  try {
    const payload = await res.json();
    const detail = payload?.detail;
    if (detail && typeof detail === "object") {
      const record = detail as Record<string, unknown>;
      return {
        code: typeof record.code === "string" ? record.code : "",
        message:
          typeof record.message === "string" ? record.message : fallback,
      };
    }
    if (typeof detail === "string") return { code: "", message: detail };
    if (typeof payload?.message === "string") {
      return { code: "", message: payload.message };
    }
  } catch {
    // Fall through to text.
  }
  try {
    const text = await res.text();
    if (text.trim()) return { code: "", message: text.trim() };
  } catch {
    // Ignore.
  }
  return { code: "", message: fallback };
}

async function requestJson<T>(
  url: string,
  init?: RequestInit,
  fallback = "知识资产请求失败",
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        accept: "application/json",
        ...(init?.body ? { "content-type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    throw new KnowledgeAssetError(
      0,
      `无法连接后端服务，请确认工作台后端已启动。诊断端点：${url}`,
      "NETWORK_UNREACHABLE",
    );
  }
  if (!res.ok) {
    const detail = await errorMessage(res, `${fallback}（HTTP ${res.status}）`);
    throw new KnowledgeAssetError(res.status, detail.message, detail.code);
  }
  return (await res.json()) as T;
}

async function requestNoContent(
  url: string,
  init?: RequestInit,
  fallback = "知识资产请求失败",
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        accept: "application/json",
        ...(init?.body ? { "content-type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new KnowledgeAssetError(
      0,
      `无法连接后端服务，请确认工作台后端已启动。诊断端点：${url}`,
      "NETWORK_UNREACHABLE",
    );
  }
  if (!res.ok) {
    const detail = await errorMessage(res, `${fallback}（HTTP ${res.status}）`);
    throw new KnowledgeAssetError(res.status, detail.message, detail.code);
  }
}

export async function getKnowledgeAssetHealth(): Promise<{
  configured: boolean;
  mock: boolean;
  store?: string;
  capabilities?: string[];
}> {
  return requestJson("/api/knowledge-assets/health", undefined, "读取知识资产状态失败");
}

export async function listKnowledgeAssetSpaces(): Promise<KnowledgeAssetSpace[]> {
  const payload = await requestJson<{ items?: KnowledgeAssetSpace[] }>(
    "/api/knowledge-assets/spaces",
    undefined,
    "读取资产空间失败",
  );
  return payload.items ?? [];
}

export async function createKnowledgeAssetSpace(input: {
  name: string;
  description?: string;
  default_knowledge_base_id?: string;
  region?: string;
}): Promise<KnowledgeAssetSpace> {
  return requestJson(
    "/api/knowledge-assets/spaces",
    { method: "POST", body: JSON.stringify(input) },
    "创建资产空间失败",
  );
}

export async function listKnowledgeAssetSources(
  spaceId?: string,
): Promise<KnowledgeAssetSource[]> {
  const params = new URLSearchParams();
  if (spaceId) params.set("space_id", spaceId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ items?: KnowledgeAssetSource[] }>(
    `/api/knowledge-assets/sources${suffix}`,
    undefined,
    "读取数据源失败",
  );
  return payload.items ?? [];
}

export async function getKnowledgeAssetOverview(
  spaceId?: string,
): Promise<KnowledgeAssetOverview> {
  const params = new URLSearchParams();
  if (spaceId) params.set("space_id", spaceId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson(
    `/api/knowledge-assets/workbench/overview${suffix}`,
    undefined,
    "读取工作台概览失败",
  );
}

export async function createKnowledgeAssetSource(input: {
  space_id: string;
  source_type: string;
  provider?: string;
  name: string;
  description?: string;
  uri?: string;
  locator?: Record<string, unknown>;
  status?: string;
  default_index_policy?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}): Promise<KnowledgeAssetSource> {
  return requestJson(
    "/api/knowledge-assets/sources",
    { method: "POST", body: JSON.stringify(input) },
    "创建数据源失败",
  );
}

export async function importKnowledgeAssetSource(input: {
  space_id: string;
  source_type: string;
  name: string;
  description?: string;
  uri?: string;
  target_knowledge_base_id?: string;
  region?: string;
  provider?: string;
  content?: string;
  content_format?: string;
  file?: Record<string, unknown>;
  schema?: Record<string, unknown>;
  locator?: Record<string, unknown>;
  credential_ref?: string;
  metadata?: Record<string, unknown>;
}): Promise<KnowledgeAssetImportResult> {
  return requestJson(
    "/api/knowledge-assets/sources/import",
    { method: "POST", body: JSON.stringify(input) },
    "导入数据源失败",
  );
}

export async function updateKnowledgeAssetSourceStatus(
  sourceId: string,
  input: {
    status: string;
    status_reason?: string;
    metadata?: Record<string, unknown>;
  },
): Promise<KnowledgeAssetSource> {
  return requestJson(
    `/api/knowledge-assets/sources/${encodeURIComponent(sourceId)}/status`,
    { method: "PATCH", body: JSON.stringify(input) },
    "更新数据源状态失败",
  );
}

export async function listKnowledgeAssets({
  query = "",
  cursor,
  limit = 20,
  assetTypes,
  capabilityKinds,
}: {
  query?: string;
  cursor?: string | null;
  limit?: number;
  assetTypes?: KnowledgeAssetType[];
  capabilityKinds?: KnowledgeCapabilityKind[];
} = {}): Promise<KnowledgeAssetListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query.trim()) params.set("q", query.trim());
  if (cursor) params.set("cursor", cursor);
  for (const type of assetTypes ?? []) params.append("asset_type", type);
  for (const kind of capabilityKinds ?? []) params.append("capability_kind", kind);
  return requestJson(
    `/api/knowledge-assets/assets?${params.toString()}`,
    undefined,
    "读取知识能力失败",
  );
}

export async function createKnowledgeAssetCapability(input: {
  space_id?: string;
  asset_type: KnowledgeAssetType;
  asset_id?: string;
  capability_kind: KnowledgeCapabilityKind;
  name: string;
  description?: string;
  status?: string;
  publish_state?: KnowledgePublishState;
  source_ids?: string[];
  type?: string;
  query_url?: string;
  capability_package?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  freshness?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  usage_policy?: Record<string, unknown>;
  sample_evidence?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
}): Promise<KnowledgeAssetMetadata> {
  return requestJson(
    "/api/knowledge-assets/skill-packages",
    { method: "POST", body: JSON.stringify(input) },
    "创建知识能力失败",
  );
}

export async function listKnowledgeAssetSnapshots(input: {
  sourceId?: string;
  assetId?: string;
} = {}): Promise<KnowledgeAssetSnapshot[]> {
  const params = new URLSearchParams();
  if (input.sourceId) params.set("source_id", input.sourceId);
  if (input.assetId) params.set("asset_id", input.assetId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ items?: KnowledgeAssetSnapshot[] }>(
    `/api/knowledge-assets/snapshots${suffix}`,
    undefined,
    "读取 schema snapshot 失败",
  );
  return payload.items ?? [];
}

export async function buildSemanticSkill(input: {
  space_id?: string;
  source_ids?: string[];
  document_source_ids?: string[];
  snapshot_ids?: string[];
  name: string;
  description?: string;
  intent?: string;
  target_domain?: string;
  publish?: boolean;
}): Promise<KnowledgeAssetBuildJob> {
  return requestJson(
    "/api/knowledge-assets/build/semantic-skill",
    { method: "POST", body: JSON.stringify(input) },
    "生成 Semantic Skill 失败",
  );
}

export async function streamSemanticBuild(
  input: {
    space_id?: string;
    source_ids?: string[];
    document_source_ids?: string[];
    snapshot_ids?: string[];
    name: string;
    description?: string;
    intent?: string;
    target_domain?: string;
    publish?: boolean;
  },
  onEvent: (event: SemanticBuildEvent) => void,
): Promise<SemanticBuildEvent[]> {
  let res: Response;
  try {
    res = await fetch("/api/knowledge-assets/semantic-build/stream", {
      method: "POST",
      headers: {
        accept: "text/event-stream",
        "content-type": "application/json",
      },
      body: JSON.stringify(input),
    });
  } catch {
    throw new KnowledgeAssetError(
      0,
      "无法连接语义构建流，请确认工作台后端已启动。",
      "NETWORK_UNREACHABLE",
    );
  }
  if (!res.ok) {
    const detail = await errorMessage(res, `语义构建流启动失败（HTTP ${res.status}）`);
    throw new KnowledgeAssetError(res.status, detail.message, detail.code);
  }
  const events: SemanticBuildEvent[] = [];
  const handleBlock = (block: string) => {
    const event = parseSseBlock(block);
    if (!event) return;
    events.push(event);
    onEvent(event);
  };
  if (!res.body) {
    const text = await res.text();
    parseSseText(text).forEach((event) => {
      events.push(event);
      onEvent(event);
    });
    return events;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      handleBlock(block);
      boundary = buffer.indexOf("\n\n");
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) handleBlock(buffer);
  return events;
}

function parseSseText(text: string): SemanticBuildEvent[] {
  return text
    .split("\n\n")
    .map(parseSseBlock)
    .filter((event): event is SemanticBuildEvent => Boolean(event));
}

function parseSseBlock(block: string): SemanticBuildEvent | null {
  if (!block.trim()) return null;
  let eventType = "message";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  const dataText = dataLines.join("\n");
  if (!dataText) return null;
  const payload = JSON.parse(dataText) as Record<string, unknown>;
  return {
    event_type:
      typeof payload.event_type === "string" ? payload.event_type : eventType,
    sequence: typeof payload.sequence === "number" ? payload.sequence : undefined,
    created_at: typeof payload.created_at === "string" ? payload.created_at : undefined,
    payload:
      payload.payload && typeof payload.payload === "object"
        ? (payload.payload as Record<string, unknown>)
        : payload,
  };
}

export async function listSemanticBuildEvents(
  jobId: string,
  afterSequence?: number,
): Promise<SemanticBuildEvent[]> {
  const params = new URLSearchParams();
  if (afterSequence !== undefined) params.set("after_sequence", String(afterSequence));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ items?: SemanticBuildEvent[] }>(
    `/api/knowledge-assets/semantic-build/${encodeURIComponent(jobId)}/events${suffix}`,
    undefined,
    "读取语义构建事件失败",
  );
  return payload.items ?? [];
}

export async function createSemanticBuilderConversation(input: {
  space_id: string;
  semantic_pack_id?: string | null;
  draft_pack_id?: string | null;
  title?: string;
  source_ids?: string[];
  document_source_ids?: string[];
  snapshot_ids?: string[];
  metadata?: Record<string, unknown>;
}): Promise<SemanticBuilderConversation> {
  return requestJson(
    "/api/knowledge-assets/semantic-builder/conversations",
    { method: "POST", body: JSON.stringify(input) },
    "创建语义建模对话失败",
  );
}

export async function getSemanticBuilderConversation(
  conversationId: string,
): Promise<SemanticBuilderConversation> {
  return requestJson(
    `/api/knowledge-assets/semantic-builder/conversations/${encodeURIComponent(conversationId)}`,
    undefined,
    "读取语义建模对话失败",
  );
}

export async function refineSemanticBuilderConversation(
  conversationId: string,
  input: {
    message: string;
    semantic_pack_id?: string | null;
    base_revision_id?: string | null;
  },
): Promise<SemanticBuilderRefineResult> {
  return requestJson(
    `/api/knowledge-assets/semantic-builder/conversations/${encodeURIComponent(conversationId)}/messages`,
    { method: "POST", body: JSON.stringify(input) },
    "调整语义草案失败",
  );
}

export async function createSemanticBuilderViewDraft(
  assetId: string,
  input: {
    name: string;
    description?: string;
    base_metric?: string;
    dimensions?: string[];
    filters?: Array<Record<string, unknown>>;
    time_grain?: string;
    query_spec?: Record<string, unknown>;
    generated_sql?: string;
  },
): Promise<SemanticBuilderViewDraftResult> {
  return requestJson(
    `/api/knowledge-assets/semantic-builder/drafts/${encodeURIComponent(assetId)}/views`,
    { method: "POST", body: JSON.stringify(input) },
    "创建语义视图草案失败",
  );
}

export async function publishSemanticBuilderDraft(
  assetId: string,
): Promise<SemanticBuilderPublishResult> {
  return requestJson(
    `/api/knowledge-assets/semantic-builder/drafts/${encodeURIComponent(assetId)}/publish`,
    { method: "POST", body: JSON.stringify({ publish: true }) },
    "发布语义草案失败",
  );
}

export async function applySemanticBuilderRevisionAction(
  conversationId: string,
  revisionId: string,
  action: "accept" | "reject" | "revert",
  input: { message?: string } = {},
): Promise<SemanticBuilderRefineResult> {
  return requestJson(
    `/api/knowledge-assets/semantic-builder/conversations/${encodeURIComponent(conversationId)}/revisions/${encodeURIComponent(revisionId)}/${encodeURIComponent(action)}`,
    { method: "POST", body: JSON.stringify(input) },
    "更新语义草案 revision 失败",
  );
}

export async function listSemanticQuestionSqlPairs(input: {
  spaceId: string;
  semanticPackId?: string;
}): Promise<SemanticQuestionSqlPair[]> {
  const params = new URLSearchParams({ space_id: input.spaceId });
  if (input.semanticPackId) params.set("semantic_pack_id", input.semanticPackId);
  const payload = await requestJson<{ items?: SemanticQuestionSqlPair[] }>(
    `/api/knowledge-assets/semantic/question-sql-pairs?${params.toString()}`,
    undefined,
    "读取 question-SQL pairs 失败",
  );
  return payload.items ?? [];
}

export async function createSemanticQuestionSqlPair(input: {
  space_id: string;
  semantic_pack_id?: string | null;
  question: string;
  sql: string;
  dialect?: string;
  tables?: string[];
  notes?: string;
}): Promise<SemanticQuestionSqlPair> {
  return requestJson(
    "/api/knowledge-assets/semantic/question-sql-pairs",
    { method: "POST", body: JSON.stringify(input) },
    "创建 question-SQL pair 失败",
  );
}

export async function updateSemanticQuestionSqlPair(
  id: string,
  input: Partial<Pick<SemanticQuestionSqlPair, "question" | "sql" | "dialect" | "tables" | "notes">>,
): Promise<SemanticQuestionSqlPair> {
  return requestJson(
    `/api/knowledge-assets/semantic/question-sql-pairs/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(input) },
    "更新 question-SQL pair 失败",
  );
}

export async function deleteSemanticQuestionSqlPair(id: string): Promise<void> {
  await requestNoContent(
    `/api/knowledge-assets/semantic/question-sql-pairs/${encodeURIComponent(id)}`,
    { method: "DELETE" },
    "删除 question-SQL pair 失败",
  );
}

export async function listSemanticInstructions(input: {
  spaceId: string;
  semanticPackId?: string;
}): Promise<SemanticInstruction[]> {
  const params = new URLSearchParams({ space_id: input.spaceId });
  if (input.semanticPackId) params.set("semantic_pack_id", input.semanticPackId);
  const payload = await requestJson<{ items?: SemanticInstruction[] }>(
    `/api/knowledge-assets/semantic/instructions?${params.toString()}`,
    undefined,
    "读取 semantic instructions 失败",
  );
  return payload.items ?? [];
}

export async function createSemanticInstruction(input: {
  space_id: string;
  semantic_pack_id?: string | null;
  instruction: string;
  questions?: string[];
  is_default?: boolean;
  scope?: string;
}): Promise<SemanticInstruction> {
  return requestJson(
    "/api/knowledge-assets/semantic/instructions",
    { method: "POST", body: JSON.stringify(input) },
    "创建 semantic instruction 失败",
  );
}

export async function updateSemanticInstruction(
  id: string,
  input: Partial<Pick<SemanticInstruction, "instruction" | "questions" | "is_default" | "scope">>,
): Promise<SemanticInstruction> {
  return requestJson(
    `/api/knowledge-assets/semantic/instructions/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(input) },
    "更新 semantic instruction 失败",
  );
}

export async function deleteSemanticInstruction(id: string): Promise<void> {
  await requestNoContent(
    `/api/knowledge-assets/semantic/instructions/${encodeURIComponent(id)}`,
    { method: "DELETE" },
    "删除 semantic instruction 失败",
  );
}

export async function getSemanticPackDetail(assetId: string): Promise<SemanticPackDetail> {
  return requestJson(
    `/api/knowledge-assets/semantic-packs/${encodeURIComponent(assetId)}/detail`,
    undefined,
    "读取 Semantic Pack 详情失败",
  );
}

export async function queryAskData(input: {
  semantic_asset_id: string;
  metric?: string;
  dimension?: string;
  dimensions?: string[];
  filters?: Record<string, unknown>;
  time_range?: Record<string, unknown>;
  question?: string;
  limit?: number;
}): Promise<AskDataQueryResult> {
  return requestJson(
    "/api/knowledge-assets/askdata/query",
    { method: "POST", body: JSON.stringify(input) },
    "AskData 查询失败",
  );
}

export async function streamAskData(
  input: AskDataStreamInput,
  options: { signal?: AbortSignal } = {},
): Promise<Response> {
  let res: Response;
  try {
    res = await fetch("/api/knowledge-assets/askdata/stream", {
      method: "POST",
      headers: {
        accept: "text/event-stream",
        "content-type": "application/json",
      },
      body: JSON.stringify(input),
      signal: options.signal,
    });
  } catch {
    throw new KnowledgeAssetError(
      0,
      "无法连接 AskTable streaming endpoint，请确认工作台后端已启动。",
      "NETWORK_UNREACHABLE",
    );
  }
  if (!res.ok) {
    const detail = await errorMessage(res, `AskTable streaming 失败（HTTP ${res.status}）`);
    throw new KnowledgeAssetError(res.status, detail.message, detail.code);
  }
  return res;
}

export async function buildDashboardSkill(input: {
  space_id?: string;
  semantic_asset_id: string;
  name: string;
  description?: string;
  intent: string;
  metric?: string;
  dimensions?: string[];
  filters?: Record<string, unknown>;
  time_range?: Record<string, unknown>;
  publish?: boolean;
}): Promise<DashboardSkillBuildResult> {
  return requestJson(
    "/api/knowledge-assets/build/dashboard-skill",
    { method: "POST", body: JSON.stringify(input) },
    "生成 Dashboard Skill 失败",
  );
}

export async function shareDashboardAsset(
  assetId: string,
  input: {
    title?: string;
    visibility?: "local_link" | "workspace";
    expires_at?: string | null;
    dashboard_html?: string;
    dashboard_spec?: Record<string, unknown>;
    query?: Record<string, unknown>;
    evidence?: Record<string, unknown>;
  },
): Promise<DashboardShare> {
  return requestJson(
    `/api/knowledge-assets/assets/dashboard/${encodeURIComponent(assetId)}/share`,
    { method: "POST", body: JSON.stringify(input) },
    "创建 Dashboard 分享失败",
  );
}

export async function getDashboardShare(shareId: string): Promise<DashboardShare> {
  return requestJson(
    `/api/knowledge-assets/shares/${encodeURIComponent(shareId)}`,
    undefined,
    "读取 Dashboard 分享失败",
  );
}

export async function revokeDashboardShare(shareId: string): Promise<DashboardShare> {
  return requestJson(
    `/api/knowledge-assets/shares/${encodeURIComponent(shareId)}/revoke`,
    { method: "POST", body: JSON.stringify({}) },
    "撤销 Dashboard 分享失败",
  );
}

export async function listKnowledgeAssetBuildJobs(
  spaceId?: string,
  filters: { sourceId?: string; assetId?: string } = {},
): Promise<KnowledgeAssetBuildJob[]> {
  const params = new URLSearchParams();
  if (spaceId) params.set("space_id", spaceId);
  if (filters.sourceId) params.set("source_id", filters.sourceId);
  if (filters.assetId) params.set("asset_id", filters.assetId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ items?: KnowledgeAssetBuildJob[] }>(
    `/api/knowledge-assets/build-jobs${suffix}`,
    undefined,
    "读取构建任务失败",
  );
  return payload.items ?? [];
}

export async function getKnowledgeAssetBuildJob(
  jobId: string,
): Promise<KnowledgeAssetBuildJob> {
  return requestJson(
    `/api/knowledge-assets/build-jobs/${encodeURIComponent(jobId)}`,
    undefined,
    "读取构建任务失败",
  );
}

export async function recordKnowledgeAssetBuildJob(input: {
  space_id?: string;
  source_id?: string;
  asset_type?: KnowledgeAssetType;
  asset_id?: string;
  job_type: string;
  status: string;
  result_skill_id?: string;
  error?: Record<string, unknown>;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
}): Promise<KnowledgeAssetBuildJob> {
  return requestJson(
    "/api/knowledge-assets/build-jobs",
    { method: "POST", body: JSON.stringify(input) },
    "记录构建任务失败",
  );
}

export async function updateKnowledgeAssetBuildJob(
  jobId: string,
  input: {
    status: string;
    logs_ref?: string;
    result_skill_id?: string;
    error?: Record<string, unknown> | null;
    output?: Record<string, unknown>;
  },
): Promise<KnowledgeAssetBuildJob> {
  return requestJson(
    `/api/knowledge-assets/build-jobs/${encodeURIComponent(jobId)}`,
    { method: "PATCH", body: JSON.stringify(input) },
    "更新构建任务失败",
  );
}

export async function listKnowledgeAssetSidecars(): Promise<KnowledgeAssetSidecar[]> {
  const payload = await requestJson<{ items?: KnowledgeAssetSidecar[] }>(
    "/api/knowledge-assets/sidecars",
    undefined,
    "读取 sidecar 状态失败",
  );
  return payload.items ?? [];
}

export async function listKnowledgeAssetEvalSuites(input: {
  spaceId?: string;
  targetKind?: KnowledgeAssetEvalTargetKind;
} = {}): Promise<KnowledgeAssetEvalSuite[]> {
  const params = new URLSearchParams();
  if (input.spaceId) params.set("space_id", input.spaceId);
  if (input.targetKind) params.set("target_kind", input.targetKind);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ items?: KnowledgeAssetEvalSuite[] }>(
    `/api/knowledge-assets/evaluation/suites${suffix}`,
    undefined,
    "读取测评集失败",
  );
  return payload.items ?? [];
}

export async function createKnowledgeAssetEvalSuite(input: {
  spaceId: string;
  name: string;
  description?: string;
  targetKind: KnowledgeAssetEvalTargetKind;
  targetAssetId: string;
}): Promise<KnowledgeAssetEvalSuite> {
  return requestJson(
    "/api/knowledge-assets/evaluation/suites",
    { method: "POST", body: JSON.stringify(input) },
    "创建测评集失败",
  );
}

export async function listKnowledgeAssetEvalCases(
  suiteId: string,
): Promise<KnowledgeAssetEvalCase[]> {
  const payload = await requestJson<{ items?: KnowledgeAssetEvalCase[] }>(
    `/api/knowledge-assets/evaluation/suites/${encodeURIComponent(suiteId)}/cases`,
    undefined,
    "读取测评用例失败",
  );
  return payload.items ?? [];
}

export async function createKnowledgeAssetEvalCase(
  suiteId: string,
  input: KnowledgeAssetEvalCaseInput,
): Promise<KnowledgeAssetEvalCase> {
  return requestJson(
    `/api/knowledge-assets/evaluation/suites/${encodeURIComponent(suiteId)}/cases`,
    { method: "POST", body: JSON.stringify(input) },
    "创建测评用例失败",
  );
}

export async function importKnowledgeAssetEvalCases(
  suiteId: string,
  cases: KnowledgeAssetEvalCaseInput[],
): Promise<KnowledgeAssetEvalCaseImportResult> {
  return requestJson(
    `/api/knowledge-assets/evaluation/suites/${encodeURIComponent(suiteId)}/cases/import`,
    { method: "POST", body: JSON.stringify({ cases }) },
    "导入测评用例失败",
  );
}

export async function runKnowledgeAssetEvaluation(input: {
  suiteId: string;
  targetAssetId?: string;
  generationMode?: string;
}): Promise<KnowledgeAssetEvalRunDetail> {
  return requestJson(
    "/api/knowledge-assets/evaluation/runs",
    { method: "POST", body: JSON.stringify(input) },
    "运行测评失败",
  );
}

export async function listKnowledgeAssetEvalRuns(input: {
  suiteId?: string;
  targetKind?: KnowledgeAssetEvalTargetKind;
  targetAssetId?: string;
  limit?: number;
} = {}): Promise<KnowledgeAssetEvalRun[]> {
  const params = new URLSearchParams();
  if (input.suiteId) params.set("suite_id", input.suiteId);
  if (input.targetKind) params.set("target_kind", input.targetKind);
  if (input.targetAssetId) params.set("target_asset_id", input.targetAssetId);
  if (input.limit) params.set("limit", String(input.limit));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ items?: KnowledgeAssetEvalRun[] }>(
    `/api/knowledge-assets/evaluation/runs${suffix}`,
    undefined,
    "读取测评运行失败",
  );
  return payload.items ?? [];
}

export async function getKnowledgeAssetEvalRun(
  runId: string,
): Promise<KnowledgeAssetEvalRunDetail> {
  return requestJson(
    `/api/knowledge-assets/evaluation/runs/${encodeURIComponent(runId)}`,
    undefined,
    "读取测评结果失败",
  );
}

export async function listKnowledgeAssetOptimizations(input: {
  targetKind?: KnowledgeAssetEvalTargetKind;
  targetAssetId?: string;
} = {}): Promise<KnowledgeAssetOptimizationSnapshot[]> {
  const params = new URLSearchParams();
  if (input.targetKind) params.set("target_kind", input.targetKind);
  if (input.targetAssetId) params.set("target_asset_id", input.targetAssetId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ items?: KnowledgeAssetOptimizationSnapshot[] }>(
    `/api/knowledge-assets/evaluation/optimizations${suffix}`,
    undefined,
    "读取优化建议失败",
  );
  return payload.items ?? [];
}
