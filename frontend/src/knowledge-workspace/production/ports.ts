export type KnowledgeCommand =
  | "resource.create"
  | "resource.update"
  | "resource.publish"
  | "resource.share"
  | "resource.revoke"
  | "connector.create"
  | "connector.test"
  | "import.start"
  | "import.cancel"
  | "assistant.turn"
  | "evaluation.run"
  | "evaluation.apply"
  | "action.update"
  | "artifact.export"
  | "workspace.store-update";

export type KnowledgeErrorCode =
  | "UNAVAILABLE"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "CREDENTIAL_EXPIRED"
  | "RATE_LIMITED"
  | "TIMEOUT"
  | "CONFLICT"
  | "CANCELLED"
  | "PARTIAL_FAILURE"
  | "INVALID_RESPONSE"
  | "NETWORK";

export interface KnowledgeRequestContext {
  requestId: string;
  idempotencyKey: string;
  expectedVersion?: string;
  lastEventId?: string;
  signal?: AbortSignal;
}

export interface KnowledgeError {
  code: KnowledgeErrorCode;
  message: string;
  retryable: boolean;
  requestId: string;
  retryAfterMs?: number;
  details?: Record<string, string>;
}

export interface KnowledgeBootstrap {
  resources: unknown[];
  connections: unknown[];
  publications: unknown[];
  actionLoop?: unknown;
  access: {
    spaceId: string;
    role: string;
    capabilities: string[];
  };
  serverTime: string;
}

export interface KnowledgeCommandResult {
  accepted: boolean;
  requestId: string;
  version?: string;
  data?: unknown;
}

export interface KnowledgeStreamEvent {
  schema_version: string;
  stream_id: string;
  event_id: string;
  sequence: number;
  occurred_at: string;
  type: string;
  payload: unknown;
  terminal: boolean;
}

export interface KnowledgeStream {
  events: AsyncIterable<KnowledgeStreamEvent>;
  cancel: () => Promise<void>;
}

export interface WorkspaceAdapter {
  readonly kind: "production-http" | "contract";
  readonly allowOptimisticUpdates: boolean;
  bootstrap(signal?: AbortSignal): Promise<KnowledgeBootstrap>;
  command(
    command: KnowledgeCommand,
    payload: unknown,
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeCommandResult>;
  stream(
    command: KnowledgeCommand,
    payload: unknown,
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeStream>;
}

export class KnowledgeAdapterError extends Error {
  readonly issue: KnowledgeError;

  constructor(issue: KnowledgeError) {
    super(issue.message);
    this.name = "KnowledgeAdapterError";
    this.issue = issue;
  }
}

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `kw-${Date.now()}-${Math.random()}`;
}

function errorFromResponse(
  response: Response,
  requestIdValue: string,
): KnowledgeAdapterError {
  const status = response.status;
  const code: KnowledgeErrorCode =
    status === 401
      ? "UNAUTHENTICATED"
      : status === 403
        ? "FORBIDDEN"
        : status === 408
          ? "TIMEOUT"
          : status === 409
            ? "CONFLICT"
            : status === 429
              ? "RATE_LIMITED"
              : status >= 500
                ? "UNAVAILABLE"
                : "INVALID_RESPONSE";
  return new KnowledgeAdapterError({
    code,
    message:
      status === 401
        ? "登录状态已失效，请重新登录后重试。"
        : status === 403
          ? "当前账号没有执行此操作的权限。"
          : status === 429
            ? "请求过于频繁，请稍后重试。"
            : `知识服务返回 HTTP ${status}，请检查服务配置后重试。`,
    retryable: code === "RATE_LIMITED" || code === "TIMEOUT" || code === "UNAVAILABLE",
    requestId: requestIdValue,
    retryAfterMs: Number(response.headers.get("Retry-After") ?? 0) * 1000 || undefined,
  });
}

async function readJson(response: Response, requestIdValue: string): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new KnowledgeAdapterError({
      code: "INVALID_RESPONSE",
      message: `知识服务返回了非 JSON 响应（${response.status} ${contentType || "unknown"}）。`,
      retryable: false,
      requestId: requestIdValue,
    });
  }
  try {
    return await response.json();
  } catch {
    throw new KnowledgeAdapterError({
      code: "INVALID_RESPONSE",
      message: "知识服务响应无法解析，请联系管理员并提供请求 ID。",
      retryable: false,
      requestId: requestIdValue,
    });
  }
}

export class ProductionKnowledgeAdapter implements WorkspaceAdapter {
  readonly kind = "production-http" as const;
  readonly allowOptimisticUpdates = false;
  private readonly basePath: string;
  private readonly fetcher: typeof fetch;
  private readonly timeoutMs: number;

  constructor(options: {
    basePath?: string;
    fetcher?: typeof fetch;
    timeoutMs?: number;
  } = {}) {
    this.basePath = options.basePath ?? "/api/knowledge-assets";
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 15_000;
  }

  async bootstrap(signal?: AbortSignal): Promise<KnowledgeBootstrap> {
    const id = requestId();
    const response = await this.request("GET", "/v1/bootstrap", undefined, {
      requestId: id,
      idempotencyKey: id,
      signal,
    });
    const body = await readJson(response, id);
    if (!body || typeof body !== "object") {
      throw new KnowledgeAdapterError({
        code: "INVALID_RESPONSE",
        message: "知识服务 bootstrap 响应缺少有效数据。",
        retryable: false,
        requestId: id,
      });
    }
    return body as KnowledgeBootstrap;
  }

  async command(
    command: KnowledgeCommand,
    payload: unknown,
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeCommandResult> {
    const response = await this.request(
      "POST",
      "/v1/commands",
      { command, payload },
      context,
    );
    const body = await readJson(response, context.requestId);
    if (!body || typeof body !== "object" || !("accepted" in body)) {
      throw new KnowledgeAdapterError({
        code: "INVALID_RESPONSE",
        message: "知识服务 mutation 响应缺少 accepted 字段。",
        retryable: false,
        requestId: context.requestId,
      });
    }
    return body as KnowledgeCommandResult;
  }

  async stream(
    command: KnowledgeCommand,
    payload: unknown,
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeStream> {
    const controller = new AbortController();
    const response = await this.request(
      "POST",
      "/v1/streams",
      { command, payload },
      { ...context, signal: controller.signal },
    );
    if (!response.body) {
      throw new KnowledgeAdapterError({
        code: "INVALID_RESPONSE",
        message: "知识服务没有返回可恢复的 SSE 流。",
        retryable: true,
        requestId: context.requestId,
      });
    }
    return {
      events: parseSse(response.body),
      cancel: async () => {
        controller.abort();
        await this.command(
          "import.cancel",
          { streamId: context.requestId },
          {
            requestId: requestId(),
            idempotencyKey: requestId(),
          },
        );
      },
    };
  }

  private async request(
    method: "GET" | "POST",
    path: string,
    body: unknown,
    context: Pick<
      KnowledgeRequestContext,
      "requestId" | "idempotencyKey" | "expectedVersion" | "lastEventId" | "signal"
    >,
  ): Promise<Response> {
    const timeout = new AbortController();
    const timer = globalThis.setTimeout(() => timeout.abort(), this.timeoutMs);
    const abort = () => timeout.abort();
    context.signal?.addEventListener("abort", abort, { once: true });
    try {
      const response = await this.fetcher(`${this.basePath}${path}`, {
        method,
        signal: timeout.signal,
        headers: {
          Accept: method === "GET" ? "application/json" : "application/json",
          ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
          "X-Request-ID": context.requestId,
          ...(method === "POST" ? { "Idempotency-Key": context.idempotencyKey } : {}),
          ...(context.expectedVersion
            ? { "If-Match": context.expectedVersion }
            : {}),
          ...(context.lastEventId
            ? { "Last-Event-ID": context.lastEventId }
            : {}),
        },
        body: method === "POST" ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) throw errorFromResponse(response, context.requestId);
      return response;
    } catch (error) {
      if (error instanceof KnowledgeAdapterError) throw error;
      throw new KnowledgeAdapterError({
        code: timeout.signal.aborted ? "TIMEOUT" : "NETWORK",
        message: timeout.signal.aborted
          ? "知识服务请求超时，请稍后重试。"
          : "无法连接知识服务，请检查网络或服务状态。",
        retryable: true,
        requestId: context.requestId,
      });
    } finally {
      globalThis.clearTimeout(timer);
      context.signal?.removeEventListener("abort", abort);
    }
  }
}

async function* parseSse(body: ReadableStream<Uint8Array>): AsyncIterable<KnowledgeStreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      buffer += decoder.decode(next.value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (!data) continue;
        yield JSON.parse(data) as KnowledgeStreamEvent;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function createRequestContext(expectedVersion?: string): KnowledgeRequestContext {
  return {
    requestId: requestId(),
    idempotencyKey: requestId(),
    expectedVersion,
  };
}

export interface SignedArtifactManifest {
  artifactId: string;
  contentSha256: string;
  signature: string;
  allowedOrigins: string[];
  expiresAt: string;
}

export async function validateSignedHtmlArtifact(
  manifest: SignedArtifactManifest,
  html: string,
  now = Date.now(),
): Promise<{ ok: true } | { ok: false; reason: string }> {
  if (!manifest.signature || !manifest.artifactId || !manifest.contentSha256) {
    return { ok: false, reason: "缺少后端签发的 Artifact manifest。" };
  }
  if (Date.parse(manifest.expiresAt) <= now) {
    return { ok: false, reason: "Artifact manifest 已过期。" };
  }
  if (
    /^[\s\S]*<\s*(script|iframe|object|embed)\b/i.test(html) ||
    /\bon[a-z]+\s*=/i.test(html) ||
    /\b(src|href)\s*=\s*["']\s*(https?:|\/\/|javascript:|data:)/i.test(html) ||
    /\b(fetch|XMLHttpRequest|WebSocket|eval|Function)\s*\(/.test(html)
  ) {
    return { ok: false, reason: "Artifact 内容包含不允许的脚本或外部网络能力。" };
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(html),
  );
  const actualHash = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  if (actualHash !== manifest.contentSha256.toLowerCase()) {
    return { ok: false, reason: "Artifact 内容摘要与后端 manifest 不一致。" };
  }
  return { ok: true };
}
