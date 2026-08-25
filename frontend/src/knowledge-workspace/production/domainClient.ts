/**
 * Worker B domain seam.
 *
 * These endpoints are intentionally separate from the frozen Knowledge Asset
 * command contract.  The client sends bytes and typed intent to the BFF; it
 * never invents a resource, revision, answer, or graph projection locally.
 */

export const KNOWLEDGE_DOMAIN_BASE = "/api/knowledge-domains/v1";

export const KNOWLEDGE_DOMAIN_ENDPOINTS = {
  createKnowledgeBase: `${KNOWLEDGE_DOMAIN_BASE}/knowledge-bases`,
  getKnowledgeBase: (knowledgeBaseId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`,
  getDocument: (sourceId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/documents/${encodeURIComponent(sourceId)}`,
  uploadSource: (knowledgeBaseId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/sources`,
  inspectFeishu: `${KNOWLEDGE_DOMAIN_BASE}/connectors/feishu/inspect`,
  syncFeishu: (knowledgeBaseId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/sources/feishu:sync`,
  askKnowledgeBase: (knowledgeBaseId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/query`,
  knowledgeQueryResult: (knowledgeBaseId: string, queryResultId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/query-results/${encodeURIComponent(queryResultId)}`,
  publishKnowledgeBase: (knowledgeBaseId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}:publish`,
  semanticModel: (resourceId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/semantic-models/${encodeURIComponent(resourceId)}`,
  semanticValidate: (resourceId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/semantic-models/${encodeURIComponent(resourceId)}:validate`,
  semanticRevision: (resourceId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/semantic-models/${encodeURIComponent(resourceId)}/revisions`,
  semanticSourceRevisions: `${KNOWLEDGE_DOMAIN_BASE}/semantic-source-revisions`,
  graphProjection: (resourceId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/graphs/${encodeURIComponent(resourceId)}`,
  graphMutation: (resourceId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/graphs/${encodeURIComponent(resourceId)}/mutations`,
  graphQuery: (resourceId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/graphs/${encodeURIComponent(resourceId)}/queries`,
  graphQueryResult: (resourceId: string, queryResultId: string) =>
    `${KNOWLEDGE_DOMAIN_BASE}/graphs/${encodeURIComponent(resourceId)}/queries/${encodeURIComponent(queryResultId)}`,
} as const;

export type DomainRequestErrorCode =
  | "NETWORK"
  | "NOT_FOUND"
  | "FORBIDDEN"
  | "VALIDATION_ERROR"
  | "GRAPH_QUERY_INVALID"
  | "KNOWLEDGE_QUERY_RESULT_NOT_FOUND"
  | "GRAPH_QUERY_RESULT_NOT_FOUND"
  | "SERVER_ERROR"
  | "INVALID_RESPONSE";

export class DomainRequestError extends Error {
  readonly code: DomainRequestErrorCode;
  readonly requestId: string;
  readonly status: number;
  readonly details: Record<string, unknown> | undefined;

  constructor(options: {
    code: DomainRequestErrorCode;
    message: string;
    requestId: string;
    status?: number;
    details?: Record<string, unknown>;
  }) {
    super(options.message);
    this.name = "DomainRequestError";
    this.code = options.code;
    this.requestId = options.requestId;
    this.status = options.status ?? 0;
    this.details = options.details;
  }
}

type JsonRecord = Record<string, unknown>;

export interface ImmutableContextRef {
  kind: "document" | "knowledge" | "semantic" | "graph";
  objectId: string;
  revision: string;
  scope: "personal" | "team";
}

const contextRefs = new Map<string, ImmutableContextRef>();

function rememberContextRef(value: unknown): void {
  if (!isRecord(value)) return;
  const kind = value.kind;
  const objectId = value.objectId;
  const revision = value.revision;
  const scope = value.scope;
  if (
    !["document", "knowledge", "semantic", "graph"].includes(String(kind)) ||
    typeof objectId !== "string" ||
    typeof revision !== "string" ||
    !["personal", "team"].includes(String(scope))
  ) return;
  contextRefs.set(`${kind}:${objectId}`, {
    kind: kind as ImmutableContextRef["kind"],
    objectId,
    revision,
    scope: scope as ImmutableContextRef["scope"],
  });
}

function rememberResponseContextRefs(body: JsonRecord): void {
  rememberContextRef(body.contextRef);
  rememberContextRef(body.documentContextRef);
  rememberContextRef(body.knowledgeContextRef);
  if (isRecord(body.knowledgeBase)) {
    rememberContextRef(body.knowledgeBase.contextRef);
  }
}

export function getServerContextRef(
  objectId: string,
): ImmutableContextRef | undefined {
  for (const ref of contextRefs.values()) {
    if (ref.objectId === objectId) return { ...ref };
  }
  return undefined;
}

let fallbackRequestCounter = 0;

function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  fallbackRequestCounter += 1;
  return `domain-${Date.now()}-${fallbackRequestCounter}`;
}

function idempotencyKey(): string {
  return requestId();
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function responseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  return null;
}

function errorCode(status: number): DomainRequestErrorCode {
  if (status === 404) return "NOT_FOUND";
  if (status === 401 || status === 403) return "FORBIDDEN";
  if (status === 400 || status === 422) return "VALIDATION_ERROR";
  if (status >= 500) return "SERVER_ERROR";
  return "INVALID_RESPONSE";
}

async function request(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  const id = requestId();
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      signal,
      headers: {
        Accept: "application/json",
        "X-Request-ID": id,
        "Idempotency-Key": idempotencyKey(),
        ...init.headers,
      },
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new DomainRequestError({
      code: "NETWORK",
      message: "无法连接知识领域服务。",
      requestId: id,
    });
  }
  const body = await responseBody(response);
  if (!response.ok) {
    const message = isRecord(body) && typeof body.message === "string"
      ? body.message
      : `知识领域服务请求失败（${response.status}）。`;
    throw new DomainRequestError({
      code: errorCode(response.status),
      message,
      requestId: id,
      status: response.status,
      details: isRecord(body) ? body : undefined,
    });
  }
  if (!isRecord(body)) {
    throw new DomainRequestError({
      code: "INVALID_RESPONSE",
      message: "知识领域服务返回了无效响应。",
      requestId: id,
      status: response.status,
    });
  }
  rememberResponseContextRefs(body);
  return body;
}

export interface KnowledgeUploadResult {
  id?: string;
  name?: string;
  knowledgeBase?: JsonRecord;
  document?: JsonRecord;
  sourceRevision?: JsonRecord;
  goldenAssetRevision?: JsonRecord;
  index?: JsonRecord;
  chunks?: JsonRecord[];
  skillDraft?: JsonRecord;
  contextRef?: ImmutableContextRef;
  documentContextRef?: ImmutableContextRef;
  knowledgeContextRef?: ImmutableContextRef;
}

export async function createKnowledgeBase(
  input: { name: string; description: string; scope: "personal" | "team" },
  signal?: AbortSignal,
): Promise<KnowledgeUploadResult> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.createKnowledgeBase, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }, signal) as Promise<KnowledgeUploadResult>;
}

export async function uploadKnowledgeSource(
  knowledgeBaseId: string,
  input: { file: File; title: string; description: string; tags: string; chunkStrategy: string },
  signal?: AbortSignal,
): Promise<KnowledgeUploadResult> {
  const form = new FormData();
  form.set("file", input.file, input.file.name);
  form.set("title", input.title);
  form.set("description", input.description);
  form.set("tags", input.tags);
  form.set("chunk_strategy", input.chunkStrategy);
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.uploadSource(knowledgeBaseId), {
    method: "POST",
    body: form,
  }, signal) as Promise<KnowledgeUploadResult>;
}

export async function getKnowledgeBase(
  knowledgeBaseId: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.getKnowledgeBase(knowledgeBaseId), {}, signal);
}

export async function getKnowledgeDocument(
  sourceId: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.getDocument(sourceId), {}, signal);
}

export async function uploadStandaloneKnowledgeDocument(
  input: { file: File; title: string; description: string; tags: string; chunkStrategy: string; scope: string },
  signal?: AbortSignal,
): Promise<KnowledgeUploadResult> {
  const form = new FormData();
  form.set("file", input.file, input.file.name);
  form.set("title", input.title);
  form.set("description", input.description);
  form.set("tags", input.tags);
  form.set("chunk_strategy", input.chunkStrategy);
  form.set("scope", input.scope);
  return request(`${KNOWLEDGE_DOMAIN_BASE}/documents`, {
    method: "POST",
    body: form,
  }, signal) as Promise<KnowledgeUploadResult>;
}

export async function inspectFeishu(
  url: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.inspectFeishu, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  }, signal);
}

export async function syncFeishu(
  knowledgeBaseId: string,
  input: { url: string; includeChildren: boolean },
  signal?: AbortSignal,
): Promise<KnowledgeUploadResult> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.syncFeishu(knowledgeBaseId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }, signal) as Promise<KnowledgeUploadResult>;
}

export async function askKnowledgeBase(
  knowledgeBaseId: string,
  input: { question: string; topK?: number },
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.askKnowledgeBase(knowledgeBaseId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }, signal);
}

export async function getKnowledgeQueryResult(
  knowledgeBaseId: string,
  queryResultId: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.knowledgeQueryResult(knowledgeBaseId, queryResultId), {}, signal);
}

export async function publishKnowledgeBase(
  knowledgeBaseId: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.publishKnowledgeBase(knowledgeBaseId), {
    method: "POST",
  }, signal);
}

export async function getSemanticModel(
  resourceId: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.semanticModel(resourceId), {}, signal);
}

export async function validateSemanticModel(
  resourceId: string,
  mdl: string,
  sourceRevisionId?: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.semanticValidate(resourceId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mdl, sourceRevisionId }),
  }, signal);
}

export async function getSemanticSourceRevisions(
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.semanticSourceRevisions, {}, signal);
}

export async function saveSemanticRevision(
  resourceId: string,
  input: { mdl: string; expectedRevision: number; sourceRevisionId?: string },
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.semanticRevision(resourceId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }, signal);
}

export async function getGraphProjection(
  resourceId: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.graphProjection(resourceId), {}, signal);
}

export async function mutateGraph(
  resourceId: string,
  mutation: JsonRecord,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.graphMutation(resourceId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mutation),
  }, signal);
}

export async function queryGraph(
  resourceId: string,
  query: JsonRecord,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.graphQuery(resourceId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
  }, signal);
}

export async function getGraphQueryResult(
  resourceId: string,
  queryResultId: string,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  return request(KNOWLEDGE_DOMAIN_ENDPOINTS.graphQueryResult(resourceId, queryResultId), {}, signal);
}
