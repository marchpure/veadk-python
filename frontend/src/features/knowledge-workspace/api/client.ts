import { withAuth } from "../../../adk/auth";
import { withLocalUser } from "../../../adk/identity";
import { parseSSE } from "../../../adk/sse";
import { ConnectionJobPollError, waitForConnectionJob } from "./connectionJobs";
import type {
  ArchivedInvocationEvent,
  Artifact,
  ConnectorDefinition,
  ConnectionProfile,
  Draft,
  Invocation,
  JsonObject,
  KnowledgeInvocationEvent,
  Meta,
  Publication,
  Revision,
} from "../domain/types";

const API_ROOT = "/api/knowledge/v1";

export class KnowledgeApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = "UNKNOWN",
    readonly retryable = false,
    readonly details?: JsonObject,
  ) {
    super(message);
    this.name = "KnowledgeApiError";
  }
}

export interface ApiEnvelope<T> {
  data: T;
  meta: Meta;
}

export interface CreateConnectionInput {
  connector_key: string;
  display_name: string;
  scope: "personal" | "team";
  config: JsonObject;
  credential: JsonObject;
}

export interface CreateDraftInput {
  goal: string;
  connection_ids: string[];
  trial_task?: string;
  upload_ids?: string[];
}

export interface UpdateDraftInput {
  goal?: string;
  connection_ids?: string[];
  trial_task?: string;
}

export interface UploadResult {
  upload_id: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  media_type?: string;
}

export interface JobResult {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  event_url?: string;
  result?: JsonObject;
  error?: JsonObject;
}

export interface ConnectionJobWaitOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  pollIntervalMs?: number;
  retryAttempts?: number;
  wait?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
}

export interface FreezeRevisionInput {
  invocation_id: string;
}

export interface PublicationInvokeInput {
  message: string;
  connection_ids?: string[];
  upload_ids?: string[];
}

type RequestOptions = RequestInit & {
  idempotencyKey?: string;
  etag?: string;
  ifNoneMatch?: string;
};

function object(value: unknown, label: string): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}格式错误`);
  }
  return value as JsonObject;
}

function envelope<T>(value: unknown, label: string): ApiEnvelope<T> {
  const root = object(value, label);
  if (!("data" in root) || !("meta" in root)) throw new Error(`${label}缺少 data/meta`);
  return {
    data: root.data as T,
    meta: object(root.meta, `${label}.meta`) as unknown as Meta,
  };
}

async function readError(response: Response): Promise<KnowledgeApiError> {
  const raw = await response.text().catch(() => "");
  try {
    const root = object(JSON.parse(raw), "错误响应");
    const error = object(root.error, "错误响应.error");
    return new KnowledgeApiError(
      typeof error.message === "string" ? error.message : `请求失败（HTTP ${response.status}）`,
      response.status,
      typeof error.code === "string" ? error.code : "UNKNOWN",
      error.retryable === true,
      error.details && typeof error.details === "object" && !Array.isArray(error.details)
        ? error.details as JsonObject
        : undefined,
    );
  } catch {
    return new KnowledgeApiError(
      `请求失败（HTTP ${response.status}）`,
      response.status,
      "HTTP_ERROR",
      response.status >= 500,
    );
  }
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<{ envelope: ApiEnvelope<T>; response: Response }> {
  const headers = new Headers(options.headers);
  const identityHeaders = withLocalUser(headers);
  if (options.body && !(options.body instanceof FormData)) {
    identityHeaders.set("Content-Type", "application/json");
  }
  if (options.idempotencyKey) identityHeaders.set("Idempotency-Key", options.idempotencyKey);
  if (options.etag) identityHeaders.set("If-Match", options.etag);
  if (options.ifNoneMatch) identityHeaders.set("If-None-Match", options.ifNoneMatch);
  const response = await fetch(withAuth(`${API_ROOT}${path}`), {
    ...options,
    headers: identityHeaders,
  });
  if (!response.ok) throw await readError(response);
  if (response.status === 204) {
    return {
      envelope: { data: undefined as T, meta: { request_id: "" } },
      response,
    };
  }
  return { envelope: envelope<T>(await response.json(), path), response };
}

function key(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}-${random}`;
}

export interface KnowledgeApi {
  listConnectorDefinitions(signal?: AbortSignal): Promise<ApiEnvelope<ConnectorDefinition[]>>;
  listConnections(signal?: AbortSignal): Promise<ApiEnvelope<ConnectionProfile[]>>;
  getConnection(id: string, signal?: AbortSignal): Promise<{ value: ApiEnvelope<ConnectionProfile>; etag: string }>;
  createConnection(input: CreateConnectionInput): Promise<ApiEnvelope<ConnectionProfile>>;
  uploadFile(file: File, purpose: "context" | "skill_input", onProgress?: (percent: number) => void): Promise<ApiEnvelope<UploadResult>>;
  validateConnection(id: string): Promise<ApiEnvelope<JobResult>>;
  discoverConnection(id: string): Promise<ApiEnvelope<JobResult>>;
  getConnectionJob(id: string, signal?: AbortSignal): Promise<ApiEnvelope<JobResult>>;
  waitForConnectionJob(
    initial: ApiEnvelope<JobResult>,
    options?: ConnectionJobWaitOptions,
  ): Promise<ApiEnvelope<JobResult>>;
  listDrafts(signal?: AbortSignal): Promise<ApiEnvelope<Draft[]>>;
  getDraft(id: string, signal?: AbortSignal): Promise<{ value: ApiEnvelope<Draft>; etag: string }>;
  createDraft(input: CreateDraftInput): Promise<{ value: ApiEnvelope<Draft>; etag: string }>;
  updateDraft(id: string, input: UpdateDraftInput, etag?: string): Promise<{ value: ApiEnvelope<Draft>; etag: string }>;
  generateDraft(id: string, etag?: string, message?: string): Promise<ApiEnvelope<Invocation>>;
  sendDraftMessage(id: string, message: string, intent: "update" | "run", etag?: string, uploadIds?: string[]): Promise<ApiEnvelope<Invocation>>;
  cancelInvocation(id: string): Promise<ApiEnvelope<Invocation>>;
  listRevisions(id: string, signal?: AbortSignal): Promise<ApiEnvelope<Revision[]>>;
  freezeRevision(id: string, input: FreezeRevisionInput, etag?: string): Promise<{ value: ApiEnvelope<Revision>; etag: string }>;
  runRevision(id: string, connection_ids: string[], message: string, uploadIds?: string[]): Promise<ApiEnvelope<Invocation>>;
  getArtifact(id: string, signal?: AbortSignal): Promise<{ value: ApiEnvelope<Artifact>; etag: string }>;
  publishRevision(id: string, target_space: "personal" | "team", display_name?: string): Promise<ApiEnvelope<Publication>>;
  invokePublication(id: string, input: PublicationInvokeInput): Promise<ApiEnvelope<Invocation>>;
  streamInvocationEvents(
    invocation: Invocation,
    options: { signal?: AbortSignal; lastEventId?: string; onUnknown?: (event: ArchivedInvocationEvent) => void },
  ): AsyncGenerator<KnowledgeInvocationEvent, void, unknown>;
}

export const knowledgeApi: KnowledgeApi = {
  async listConnectorDefinitions(signal) {
    const result = await request<ConnectorDefinition[]>("/connector-definitions", { signal });
    return result.envelope;
  },
  async listConnections(signal) {
    const result = await request<ConnectionProfile[]>("/connections", { signal });
    return result.envelope;
  },
  async getConnection(id, signal) {
    const result = await request<ConnectionProfile>(`/connections/${encodeURIComponent(id)}`, { signal });
    return { value: result.envelope, etag: result.response.headers.get("ETag") ?? "" };
  },
  async createConnection(input) {
    const result = await request<ConnectionProfile>("/connections", {
      method: "POST",
      body: JSON.stringify(input),
      idempotencyKey: key("connection"),
    });
    return result.envelope;
  },
  async uploadFile(file, purpose, onProgress) {
    const form = new FormData();
    form.append("file", file);
    form.append("purpose", purpose);
    const response = await new Promise<Response>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", withAuth(`${API_ROOT}/uploads`));
      xhr.withCredentials = true;
      const headers = withLocalUser();
      headers.forEach((value, name) => xhr.setRequestHeader(name, value));
      xhr.setRequestHeader("Idempotency-Key", key("upload"));
      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
      });
      xhr.addEventListener("load", () => resolve(new Response(xhr.responseText, {
        status: xhr.status,
        headers: { "Content-Type": xhr.getResponseHeader("Content-Type") || "application/json" },
      })));
      xhr.addEventListener("error", () => reject(new Error("上传失败，请检查网络后重试。")));
      xhr.addEventListener("abort", () => reject(new DOMException("上传已取消", "AbortError")));
      xhr.send(form);
    });
    if (!response.ok) throw await readError(response);
    return envelope<UploadResult>(await response.json(), "/uploads");
  },
  async validateConnection(id) {
    const result = await request<JobResult>(
      `/connections/${encodeURIComponent(id)}/validate`,
      { method: "POST", body: JSON.stringify({}), idempotencyKey: key("validate") },
    );
    return result.envelope;
  },
  async discoverConnection(id) {
    const result = await request<JobResult>(
      `/connections/${encodeURIComponent(id)}/discover`,
      { method: "POST", body: JSON.stringify({}), idempotencyKey: key("discover") },
    );
    return result.envelope;
  },
  async getConnectionJob(id, signal) {
    const result = await request<JobResult>(
      `/connection-jobs/${encodeURIComponent(id)}`,
      { signal },
    );
    return result.envelope;
  },
  async waitForConnectionJob(initial, options = {}) {
    try {
      return await waitForConnectionJob(
        initial,
        (jobId, signal) => knowledgeApi.getConnectionJob(jobId, signal),
        options,
      );
    } catch (error) {
      if (error instanceof ConnectionJobPollError) {
        throw new KnowledgeApiError(
          error.message,
          error.code === "CONNECTION_JOB_TIMEOUT" ? 408 : 502,
          error.code,
          error.retryable,
          error.details,
        );
      }
      throw error;
    }
  },
  async listDrafts(signal) {
    const result = await request<Draft[]>("/skills/drafts", { signal });
    return result.envelope;
  },
  async getDraft(id, signal) {
    const result = await request<Draft>(`/skills/drafts/${encodeURIComponent(id)}`, { signal });
    return { value: result.envelope, etag: result.response.headers.get("ETag") ?? "" };
  },
  async createDraft(input) {
    const result = await request<Draft>("/skills/drafts", {
      method: "POST",
      body: JSON.stringify(input),
      idempotencyKey: key("draft"),
    });
    return { value: result.envelope, etag: result.response.headers.get("ETag") ?? "" };
  },
  async updateDraft(id, input, etag) {
    const result = await request<Draft>(`/skills/drafts/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      etag,
      idempotencyKey: key("draft-update"),
    });
    return { value: result.envelope, etag: result.response.headers.get("ETag") ?? "" };
  },
  async generateDraft(id, etag, message) {
    const result = await request<Invocation>(`/skills/drafts/${encodeURIComponent(id)}/generate`, {
      method: "POST",
      body: JSON.stringify(message ? { message } : {}),
      etag,
      idempotencyKey: key("generate"),
    });
    return result.envelope;
  },
  async sendDraftMessage(id, message, intent, etag, uploadIds) {
    const result = await request<Invocation>(`/skills/drafts/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      body: JSON.stringify({
        message,
        intent,
        ...(uploadIds?.length ? { upload_ids: uploadIds } : {}),
      }),
      etag,
      idempotencyKey: key("message"),
    });
    return result.envelope;
  },
  async cancelInvocation(id) {
    const result = await request<Invocation>(`/invocations/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      idempotencyKey: key("cancel"),
    });
    return result.envelope;
  },
  async listRevisions(id, signal) {
    const result = await request<Revision[]>(
      `/skills/drafts/${encodeURIComponent(id)}/revisions`,
      { signal },
    );
    return result.envelope;
  },
  async freezeRevision(id, input, etag) {
    const result = await request<Revision>(`/skills/drafts/${encodeURIComponent(id)}/revisions`, {
      method: "POST",
      body: JSON.stringify(input),
      etag,
      idempotencyKey: key("revision"),
    });
    return { value: result.envelope, etag: result.response.headers.get("ETag") ?? "" };
  },
  async runRevision(id, connection_ids, message, uploadIds) {
    const result = await request<Invocation>(`/skill-revisions/${encodeURIComponent(id)}/run`, {
      method: "POST",
      body: JSON.stringify({
        connection_ids,
        message,
        ...(uploadIds?.length ? { upload_ids: uploadIds } : {}),
      }),
      idempotencyKey: key("run"),
    });
    return result.envelope;
  },
  async getArtifact(id, signal) {
    const result = await request<Artifact>(`/artifacts/${encodeURIComponent(id)}`, { signal });
    return { value: result.envelope, etag: result.response.headers.get("ETag") ?? "" };
  },
  async publishRevision(id, target_space, display_name) {
    const result = await request<Publication>(`/skill-revisions/${encodeURIComponent(id)}/publish`, {
      method: "POST",
      body: JSON.stringify({ target_space, ...(display_name ? { display_name } : {}) }),
      idempotencyKey: key("publish"),
    });
    return result.envelope;
  },
  async invokePublication(id, input) {
    const result = await request<Invocation>(`/publications/${encodeURIComponent(id)}/invoke`, {
      method: "POST",
      body: JSON.stringify(input),
      idempotencyKey: key("publication-invoke"),
    });
    return result.envelope;
  },
  async *streamInvocationEvents(invocation, options) {
    const url = withAuth(`${API_ROOT}/invocations/${encodeURIComponent(invocation.invocation_id)}/events`);
    const headers = withLocalUser();
    if (options.lastEventId) headers.set("Last-Event-ID", options.lastEventId);
    const response = await fetch(url, {
      headers,
      signal: options.signal,
    });
    if (!response.ok) throw await readError(response);
    for await (const raw of parseSSE(response)) {
      const candidate = raw && typeof raw === "object" && !Array.isArray(raw)
        ? raw as JsonObject
        : {};
      const event = normalizeEvent(candidate);
      if (event) {
        yield event;
      } else {
        options.onUnknown?.({
          id: typeof candidate.id === "string" ? candidate.id : "unknown",
          type: typeof candidate.type === "string" ? candidate.type : "unknown",
          invocation_id: typeof candidate.invocation_id === "string"
            ? candidate.invocation_id
            : invocation.invocation_id,
          occurred_at: typeof candidate.occurred_at === "string"
            ? candidate.occurred_at
            : new Date().toISOString(),
          data: candidate.data && typeof candidate.data === "object" && !Array.isArray(candidate.data)
            ? candidate.data as JsonObject
            : {},
        });
      }
    }
  },
};

function normalizeEvent(value: JsonObject): KnowledgeInvocationEvent | undefined {
  const type = value.type;
  if (
    typeof value.id !== "string" ||
    typeof value.invocation_id !== "string" ||
    typeof value.occurred_at !== "string" ||
    typeof type !== "string" ||
    !value.data ||
    typeof value.data !== "object" ||
    Array.isArray(value.data)
  ) return undefined;
  const data = value.data as JsonObject;
  if (
    type === "run.started" &&
    (data.status === "running") &&
    typeof data.kind === "string"
  ) return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  if (
    type === "assistant.delta" &&
    typeof data.text === "string" &&
    typeof data.sequence === "number"
  ) return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  if (type === "plan.updated" && Array.isArray(data.steps)) {
    return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  }
  if (
    (type === "tool.started" || type === "tool.completed") &&
    typeof data.tool_call_id === "string" &&
    typeof data.tool_name === "string"
  ) return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  if (
    type === "artifact.created" &&
    typeof data.artifact_id === "string" &&
    typeof data.revision_id === "string" &&
    typeof data.media_type === "string" &&
    typeof data.sha256 === "string"
  ) return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  if (
    type === "revision.created" &&
    typeof data.revision_id === "string" &&
    typeof data.draft_id === "string" &&
    typeof data.number === "number" &&
    typeof data.sha256 === "string"
  ) return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  if (
    type === "run.completed" &&
    data.status === "succeeded" &&
    typeof data.finished_at === "string"
  ) return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  if (
    type === "run.failed" &&
    data.status === "failed" &&
    data.error &&
    typeof data.error === "object" &&
    !Array.isArray(data.error)
  ) return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  if (type === "run.cancelled" && data.status === "cancelled") {
    return { ...value, type, data } as unknown as KnowledgeInvocationEvent;
  }
  return undefined;
}
