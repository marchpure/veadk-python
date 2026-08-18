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
