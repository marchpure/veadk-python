import {
  parseBootstrap,
  type KnowledgeBootstrap,
  type WorkspaceActionLoopState,
  type WorkspaceBootstrapData,
  type WorkspaceConnectorDefinition,
  type WorkspaceDatasetField,
  type WorkspaceKpi,
  type WorkspaceKnowledgeGraphEntity,
  type WorkspaceKnowledgeGraphMapping,
  type WorkspaceTrendPoint,
} from "./bootstrapSchema";
import {
  createKnowledgeAssetClient,
  GeneratedClientHttpError,
  type KnowledgeAssetClient,
} from "./generatedClient";
import type { GeneratedCommand } from "./generated";

export type KnowledgeCommandName =
  | "resource.create"
  | "resource.update"
  | "resource.publish"
  | "resource.share"
  | "resource.revoke"
  | "connector.create"
  | "connector.test"
  | "import.start"
  | "import.cancel"
  | "stream.cancel"
  | "assistant.turn"
  | "evaluation.run"
  | "evaluation.apply"
  | "action.update"
  | "artifact.export"
  | "skill-draft.create"
  | "skill-draft.save-manifest"
  | "source.profile"
  | "source.clean"
  | "skill-draft.run"
  | "publication.publish"
  | "refresh.run"
  | "invocation.start";

export interface ActionUpdatePayload {
  actionId: string;
}
export interface SkillDraftCreatePayload {
  workspaceId: string;
  name: string;
  description: string;
  sourceRefs: string[];
}
export interface SkillDraftSaveManifestPayload {
  draftId: string;
  baseRevision: number;
  manifest: {
    name: string;
    version: string;
    description: string;
    actions: Array<{ name: string; description: string }>;
    schema: {
      type: "object";
      properties: Record<string, {
        type: "string" | "number" | "boolean" | "object" | "array";
        description: string;
      }>;
      required: string[];
      additionalProperties: boolean;
    };
  };
}
export interface ResourceCommandPayload {
  resourceId: string;
}
export interface ConnectorCommandPayload {
  connectorKey: string;
}
export interface ImportCommandPayload {
  sourceId: string;
}
export interface AssistantTurnPayload {
  text: string;
  contextIds: string[];
}
export interface EvaluationPayload {
  targetId: string;
}
export interface ArtifactExportPayload {
  resourceId: string;
  format: "json" | "csv" | "html";
}
export interface StreamCancelPayload {
  streamId: string;
  sourceCommand: "import.start" | "assistant.turn";
}
export type EmptyPayload = Record<string, never>;
export type KnowledgeCommand =
  | { command: "action.update"; payload: ActionUpdatePayload }
  | { command: "skill-draft.create"; payload: SkillDraftCreatePayload }
  | {
    command: "skill-draft.save-manifest";
    payload: SkillDraftSaveManifestPayload;
  }
  | { command: "resource.create" | "resource.update" | "resource.publish" | "resource.share" | "resource.revoke"; payload: ResourceCommandPayload }
  | { command: "connector.create" | "connector.test"; payload: ConnectorCommandPayload }
  | { command: "import.start" | "import.cancel"; payload: ImportCommandPayload }
  | { command: "stream.cancel"; payload: StreamCancelPayload }
  | { command: "assistant.turn"; payload: AssistantTurnPayload }
  | { command: "evaluation.run" | "evaluation.apply"; payload: EvaluationPayload }
  | { command: "artifact.export"; payload: ArtifactExportPayload }
  | {
    command:
      | "source.profile"
      | "source.clean"
      | "skill-draft.run"
      | "publication.publish"
      | "refresh.run"
      | "invocation.start";
    payload: EmptyPayload;
  };
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
  | "NETWORK"
  | "VALIDATION_ERROR"
  | "DRAFT_NOT_FOUND"
  | "OPERATION_NOT_FOUND";
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

export type {
  KnowledgeBootstrap,
  WorkspaceActionLoopState,
  WorkspaceBootstrapData,
  WorkspaceConnectorDefinition,
  WorkspaceDatasetField,
  WorkspaceKpi,
  WorkspaceKnowledgeGraphEntity,
  WorkspaceKnowledgeGraphMapping,
  WorkspaceTrendPoint,
};
export interface KnowledgeCommandResult {
  accepted: boolean;
  requestId: string;
  operationId?: string;
  version?: string;
  result?: {
    draft?: Record<string, string | number>;
    replayed?: boolean;
  };
}
export interface KnowledgeStreamEvent {
  schema_version: string;
  stream_id: string;
  event_id: string;
  sequence: number;
  occurred_at: string;
  type: string;
  payload: Record<string, unknown>;
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
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeCommandResult>;
  stream(
    command: Extract<
      KnowledgeCommand,
      { command: "import.start" | "assistant.turn" }
    >,
    context: KnowledgeRequestContext,
  ): Promise<KnowledgeStream>;
}
type LegacyCommandName = KnowledgeCommandName;
export class KnowledgeAdapterError extends Error {
  readonly issue: KnowledgeError;
  constructor(issue: KnowledgeError) {
    super(issue.message);
    this.name = "KnowledgeAdapterError";
    this.issue = issue;
  }
}
let requestSequence = 0;
function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  requestSequence += 1;
  return `kw-${Date.now().toString(36)}-${requestSequence.toString(36)}`;
}
const TRANSPORT_SCHEMA_VERSION = "knowledge-workspace.transport.v1";
function isJsonMediaType(contentType: string): boolean {
  return (
    contentType.includes("application/json") || contentType.includes("+json")
  );
}
function isEventStreamMediaType(contentType: string): boolean {
  return (
    contentType.split(";")[0]?.trim().toLowerCase() === "text/event-stream"
  );
}
function knownErrorCode(value: unknown): KnowledgeErrorCode | null {
  const codes: KnowledgeErrorCode[] = [
    "UNAVAILABLE",
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "CREDENTIAL_EXPIRED",
    "RATE_LIMITED",
    "TIMEOUT",
    "CONFLICT",
    "CANCELLED",
    "PARTIAL_FAILURE",
    "INVALID_RESPONSE",
    "NETWORK",
    "VALIDATION_ERROR",
    "DRAFT_NOT_FOUND",
    "OPERATION_NOT_FOUND",
  ];
  return typeof value === "string" &&
      codes.includes(value as KnowledgeErrorCode)
    ? (value as KnowledgeErrorCode)
    : null;
}
async function errorFromResponse(
  response: Response,
  requestIdValue: string,
): Promise<KnowledgeAdapterError> {
  const status = response.status;
  const fallbackCode: KnowledgeErrorCode = status === 401
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
  let envelope: Record<string, unknown> | null = null;
  if (isJsonMediaType(response.headers.get("content-type") ?? "")) {
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object") {
        envelope = body as Record<string, unknown>;
      }
    } catch {
      // The status-based fallback below remains actionable when the error body
      // is empty or malformed.
    }
  }
  const code = knownErrorCode(envelope?.code) ?? fallbackCode;
  const message =
    typeof envelope?.message === "string" && envelope.message.trim()
      ? envelope.message
      : status === 401
      ? "登录状态已失效，请重新登录后重试。"
      : status === 403
      ? "当前账号没有执行此操作的权限。"
      : status === 429
      ? "请求过于频繁，请稍后重试。"
      : `知识服务返回 HTTP ${status}，请检查服务配置后重试。`;
  const retryAfterMs =
    typeof envelope?.retry_after_ms === "number" && envelope.retry_after_ms >= 0
      ? envelope.retry_after_ms
      : Number(response.headers.get("Retry-After") ?? 0) * 1000 || undefined;
  const details = envelope?.details && typeof envelope.details === "object"
    ? Object.fromEntries(
      Object.entries(envelope.details).filter(
        ([key, value]) =>
          /^[a-zA-Z0-9_.-]+$/.test(key) &&
          !/credential|token|cookie|secret|password/i.test(key) &&
          typeof value === "string",
      ),
    )
    : undefined;
  return new KnowledgeAdapterError({
    code,
    message,
    retryable: typeof envelope?.retryable === "boolean"
      ? envelope.retryable
      : code === "RATE_LIMITED" ||
        code === "TIMEOUT" ||
        code === "UNAVAILABLE",
    requestId: requestIdValue,
    retryAfterMs,
    details: details && Object.keys(details).length > 0 ? details : undefined,
  });
}

function errorFromGeneratedClient(
  error: GeneratedClientHttpError,
  requestIdValue: string,
): KnowledgeAdapterError {
  const envelope = error.body && typeof error.body === "object"
    ? error.body as Record<string, unknown>
    : null;
  const fallbackCode: KnowledgeErrorCode = error.status === 401
    ? "UNAUTHENTICATED"
    : error.status === 403
    ? "FORBIDDEN"
    : error.status === 408
    ? "TIMEOUT"
    : error.status === 409
    ? "CONFLICT"
    : error.status === 429
    ? "RATE_LIMITED"
    : error.status >= 500
    ? "UNAVAILABLE"
    : "INVALID_RESPONSE";
  const code = knownErrorCode(envelope?.code) ?? fallbackCode;
  const retryAfterMs =
    typeof envelope?.retry_after_ms === "number" && envelope.retry_after_ms >= 0
      ? envelope.retry_after_ms
      : Number(error.headers["retry-after"] ?? 0) * 1000 || undefined;
  const details = envelope?.details && typeof envelope.details === "object"
    ? Object.fromEntries(
      Object.entries(envelope.details).filter(
        ([key, value]) =>
          /^[a-zA-Z0-9_.-]+$/.test(key) &&
          !/credential|token|cookie|secret|password/i.test(key) &&
          typeof value === "string",
      ),
    )
    : undefined;
  return new KnowledgeAdapterError({
    code,
    message:
      typeof envelope?.message === "string" && envelope.message.trim()
        ? envelope.message
        : `知识服务返回 HTTP ${error.status}，请检查服务配置后重试。`,
    retryable: typeof envelope?.retryable === "boolean"
      ? envelope.retryable
      : code === "RATE_LIMITED" ||
        code === "TIMEOUT" ||
        code === "UNAVAILABLE",
    requestId: requestIdValue,
    retryAfterMs,
    details: details && Object.keys(details).length > 0 ? details : undefined,
  });
}
async function readJson(
  response: Response,
  requestIdValue: string,
): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!isJsonMediaType(contentType)) {
    throw new KnowledgeAdapterError({
      code: "INVALID_RESPONSE",
      message: `知识服务返回了非 JSON 响应（${response.status} ${
        contentType || "unknown"
      }）。`,
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
  private readonly generatedClient: KnowledgeAssetClient;
  constructor(
    options: {
      basePath?: string;
      fetcher?: typeof fetch;
      timeoutMs?: number;
    } = {},
  ) {
    this.basePath = options.basePath ?? "/api/knowledge-assets";
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 15_000;
    this.generatedClient = createKnowledgeAssetClient(
      this.fetcher,
      `${this.basePath}/v1`,
    );
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
    return parseBootstrap(body, id, (message, requestIdValue) =>
      new KnowledgeAdapterError({
        code: "INVALID_RESPONSE",
        message,
        retryable: false,
        requestId: requestIdValue,
      }),
    );
  }
  async command(
    command: KnowledgeCommand | LegacyCommandName,
    contextOrPayload: KnowledgeRequestContext | Record<string, unknown>,
    legacyContext?: KnowledgeRequestContext,
  ): Promise<KnowledgeCommandResult> {
    const normalized = normalizeCommand(command, contextOrPayload, legacyContext);
    const context = normalized.context;
    if (
      normalized.command.command === "skill-draft.create" ||
      normalized.command.command === "action.update"
    ) {
      let generated;
      try {
        generated = await this.generatedClient.command(
          normalized.command as GeneratedCommand,
          context,
        );
      } catch (error) {
        if (error instanceof GeneratedClientHttpError) {
          throw errorFromGeneratedClient(error, context.requestId);
        }
        throw error;
      }
      return parseCommandResult(generated, context.requestId);
    }
    const response = await this.request(
      "POST",
      "/v1/commands",
      normalized.command,
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
    return parseCommandResult(body, context.requestId);
  }
  async stream(
    command: Extract<
      KnowledgeCommand,
      { command: "import.start" | "assistant.turn" }
    > | "assistant.turn",
    contextOrPayload: KnowledgeRequestContext | Record<string, unknown>,
    legacyContext?: KnowledgeRequestContext,
  ): Promise<KnowledgeStream> {
    const normalized = normalizeStreamCommand(
      command,
      contextOrPayload,
      legacyContext,
    );
    const context = normalized.context;
    const controller = new AbortController();
    let callerAbortListener: (() => void) | undefined;
    if (context.signal) {
      callerAbortListener = () => controller.abort();
      if (context.signal.aborted) controller.abort();
      else {
        context.signal.addEventListener("abort", callerAbortListener, {
          once: true,
        });
      }
    }
    let streamId = undefined as string | undefined;
    let terminalReached = false;
    let response: Response;
    try {
      response = await this.request(
        "POST",
        "/v1/streams",
        normalized.command,
        { ...context, signal: controller.signal },
      );
    } catch (error) {
      callerAbortListener &&
        context.signal?.removeEventListener("abort", callerAbortListener);
      throw error;
    }
    if (!isEventStreamMediaType(response.headers.get("content-type") ?? "")) {
      callerAbortListener &&
        context.signal?.removeEventListener("abort", callerAbortListener);
      throw new KnowledgeAdapterError({
        code: "INVALID_RESPONSE",
        message: "知识服务返回的流不是受支持的 SSE 响应。",
        retryable: false,
        requestId: context.requestId,
      });
    }
    const responseStreamId = response.headers.get("X-Stream-ID");
    if (responseStreamId) streamId = responseStreamId;
    if (!response.body) {
      callerAbortListener &&
        context.signal?.removeEventListener("abort", callerAbortListener);
      throw new KnowledgeAdapterError({
        code: "INVALID_RESPONSE",
        message: "知识服务没有返回可恢复的 SSE 流。",
        retryable: true,
        requestId: context.requestId,
      });
    }
    const events = parseSse(
      response.body,
      context.requestId,
      controller.signal,
      (nextStreamId) => {
        streamId ??= nextStreamId;
      },
      () => {
        terminalReached = true;
        callerAbortListener &&
          context.signal?.removeEventListener("abort", callerAbortListener);
      },
    );
    return {
      events,
      cancel: (() => {
        let cancelPromise: Promise<void> | undefined;
        return () => {
          cancelPromise ??= (async () => {
            if (terminalReached) return;
            controller.abort();
            callerAbortListener &&
              context.signal?.removeEventListener("abort", callerAbortListener);
            const cancelCommand: KnowledgeCommand =
              normalized.command.command === "import.start"
                ? {
                  command: "import.cancel",
                  payload: {
                    sourceId: (normalized.command as Extract<
                      KnowledgeCommand,
                      { command: "import.start" }
                    >).payload.sourceId,
                  },
                }
                : {
                  command: "stream.cancel",
                  payload: {
                    streamId: streamId ?? context.requestId,
                    sourceCommand: "assistant.turn",
                  },
                };
            const cancelContext = createRequestContext();
            const result = await this.command(cancelCommand, cancelContext);
            if (!result.accepted) {
              throw new KnowledgeAdapterError({
                code: "UNAVAILABLE",
                message: "知识服务未确认取消请求。",
                retryable: true,
                requestId: cancelContext.requestId,
              });
            }
          })();
          return cancelPromise;
        };
      })(),
    };
  }
  private async request(
    method: "GET" | "POST",
    path: string,
    body: unknown,
    context: Pick<
      KnowledgeRequestContext,
      | "requestId"
      | "idempotencyKey"
      | "expectedVersion"
      | "lastEventId"
      | "signal"
    >,
  ): Promise<Response> {
    const timeout = new AbortController();
    const timer = globalThis.setTimeout(() => timeout.abort(), this.timeoutMs);
    let callerAborted = context.signal?.aborted ?? false;
    const abort = () => {
      callerAborted = true;
      timeout.abort();
    };
    context.signal?.addEventListener("abort", abort, { once: true });
    if (callerAborted) timeout.abort();
    try {
      const response = await this.fetcher(`${this.basePath}${path}`, {
        method,
        signal: timeout.signal,
        headers: {
          Accept: path === "/v1/streams"
            ? "text/event-stream"
            : "application/json",
          ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
          "X-Request-ID": context.requestId,
          ...(method === "POST"
            ? { "Idempotency-Key": context.idempotencyKey }
            : {}),
          ...(context.expectedVersion
            ? { "If-Match": context.expectedVersion }
            : {}),
          ...(context.lastEventId
            ? { "Last-Event-ID": context.lastEventId }
            : {}),
        },
        body: method === "POST" ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        throw await errorFromResponse(response, context.requestId);
      }
      return response;
    } catch (error) {
      if (error instanceof KnowledgeAdapterError) throw error;
      throw new KnowledgeAdapterError({
        code: callerAborted
          ? "CANCELLED"
          : timeout.signal.aborted
          ? "TIMEOUT"
          : "NETWORK",
        message: callerAborted
          ? "操作已取消。"
          : timeout.signal.aborted
          ? "知识服务请求超时，请稍后重试。"
          : "无法连接知识服务，请检查网络或服务状态。",
        retryable: !callerAborted,
        requestId: context.requestId,
      });
    } finally {
      globalThis.clearTimeout(timer);
      context.signal?.removeEventListener("abort", abort);
    }
  }
}
function parseCommandResult(
  body: unknown,
  requestIdValue: string,
): KnowledgeCommandResult {
  const value = body as Record<string, unknown> | null;
  if (
    !value ||
    typeof value.accepted !== "boolean" ||
    typeof value.requestId !== "string" ||
    !value.requestId
  ) {
    throw new KnowledgeAdapterError({
      code: "INVALID_RESPONSE",
      message: "知识服务 mutation 响应缺少有效的 accepted 字段。",
      retryable: false,
      requestId: requestIdValue,
    });
  }
  return body as KnowledgeCommandResult;
}

function normalizeCommand(
  command: KnowledgeCommand | LegacyCommandName,
  contextOrPayload: KnowledgeRequestContext | Record<string, unknown>,
  legacyContext?: KnowledgeRequestContext,
): { command: KnowledgeCommand; context: KnowledgeRequestContext } {
  if (typeof command !== "string") {
    return { command, context: contextOrPayload as KnowledgeRequestContext };
  }
  return {
    command: legacyCommand(command, contextOrPayload as Record<string, unknown>),
    context: legacyContext ?? (contextOrPayload as KnowledgeRequestContext),
  };
}

function normalizeStreamCommand(
  command: Extract<
    KnowledgeCommand,
    { command: "import.start" | "assistant.turn" }
  > | "assistant.turn",
  contextOrPayload: KnowledgeRequestContext | Record<string, unknown>,
  legacyContext?: KnowledgeRequestContext,
): {
  command: Extract<
    KnowledgeCommand,
    { command: "import.start" | "assistant.turn" }
  >;
  context: KnowledgeRequestContext;
} {
  if (typeof command !== "string") {
    return { command, context: contextOrPayload as KnowledgeRequestContext };
  }
  return {
    command: legacyCommand(command, contextOrPayload as Record<string, unknown>) as Extract<
      KnowledgeCommand,
      { command: "import.start" | "assistant.turn" }
    >,
    context: legacyContext ?? (contextOrPayload as KnowledgeRequestContext),
  };
}

function legacyCommand(
  command: LegacyCommandName,
  payload: Record<string, unknown>,
): KnowledgeCommand {
  switch (command) {
    case "assistant.turn":
      return {
        command,
        payload: {
          text: typeof payload.text === "string" ? payload.text : "",
          contextIds: [],
        },
      };
    case "import.start":
    case "import.cancel":
      return {
        command,
        payload: { sourceId: typeof payload.sourceId === "string" ? payload.sourceId : "legacy" },
      };
    case "stream.cancel":
      return {
        command,
        payload: { streamId: "legacy", sourceCommand: "assistant.turn" },
      };
    case "artifact.export":
      return {
        command,
        payload: { resourceId: "legacy", format: "json" },
      };
    case "action.update":
      return { command, payload: { actionId: "legacy" } };
    case "skill-draft.create":
      return {
        command,
        payload: {
          workspaceId: "legacy",
          name: "Legacy draft",
          description: "",
          sourceRefs: [],
        },
      };
    case "skill-draft.save-manifest":
      return {
        command,
        payload: {
          draftId: "legacy",
          baseRevision: 1,
          manifest: {
            name: "Legacy draft",
            version: "1.0.0",
            description: "",
            actions: [{ name: "answer", description: "" }],
            schema: {
              type: "object",
              properties: {},
              required: [],
              additionalProperties: false,
            },
          },
        },
      };
    case "resource.create":
    case "resource.update":
    case "resource.publish":
    case "resource.share":
    case "resource.revoke":
      return { command, payload: { resourceId: "legacy" } };
    case "connector.create":
    case "connector.test":
      return { command, payload: { connectorKey: "legacy" } };
    case "evaluation.run":
    case "evaluation.apply":
      return { command, payload: { targetId: "legacy" } };
    case "source.profile":
    case "source.clean":
    case "skill-draft.run":
    case "publication.publish":
    case "refresh.run":
    case "invocation.start":
      return { command, payload: {} };
  }
}
async function* parseSse(
  body: ReadableStream<Uint8Array>,
  requestIdValue: string,
  signal: AbortSignal,
  onStreamId: (streamId: string) => void,
  onTerminal: () => void,
): AsyncIterable<KnowledgeStreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    lastSequence = 0,
    started = false,
    terminal = false;
  let streamId: string | undefined;
  const seenEventIds = new Set<string>();
  const cancelReader = () => {
    void reader.cancel();
  };
  signal.addEventListener("abort", cancelReader, { once: true });
  try {
    while (true) {
      const next = await reader.read();
      buffer += next.done
        ? `${decoder.decode()}\n\n`
        : decoder.decode(next.value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (!data) continue;
        let event: KnowledgeStreamEvent;
        try {
          event = JSON.parse(data) as KnowledgeStreamEvent;
        } catch {
          throw new KnowledgeAdapterError({
            code: "INVALID_RESPONSE",
            message: "知识服务 SSE 事件无法解析。",
            retryable: false,
            requestId: requestIdValue,
          });
        }
        if (
          !event ||
          typeof event !== "object" ||
          event.schema_version !== TRANSPORT_SCHEMA_VERSION ||
          typeof event.stream_id !== "string" ||
          !event.stream_id ||
          typeof event.event_id !== "string" ||
          !event.event_id ||
          typeof event.occurred_at !== "string" ||
          Number.isNaN(Date.parse(event.occurred_at)) ||
          typeof event.type !== "string" ||
          !event.type ||
          typeof event.terminal !== "boolean" ||
          typeof event.sequence !== "number" ||
          !Number.isInteger(event.sequence) ||
          event.sequence < 1 ||
          !Object.prototype.hasOwnProperty.call(event, "payload") ||
          (streamId !== undefined && event.stream_id !== streamId)
        ) {
          throw new KnowledgeAdapterError({
            code: "INVALID_RESPONSE",
            message: "知识服务 SSE 顺序或 terminal 无效。",
            retryable: false,
            requestId: requestIdValue,
          });
        }
        if (seenEventIds.has(event.event_id) && event.stream_id === streamId) {
          continue;
        }
        if ((started && event.sequence !== lastSequence + 1) || terminal) {
          throw new KnowledgeAdapterError({
            code: "INVALID_RESPONSE",
            message: "知识服务 SSE 顺序或 terminal 无效。",
            retryable: false,
            requestId: requestIdValue,
          });
        }
        streamId ??= event.stream_id;
        onStreamId(streamId);
        seenEventIds.add(event.event_id);
        started = true;
        lastSequence = event.sequence;
        terminal ||= event.terminal;
        if (event.terminal) onTerminal();
        yield event;
      }
      if (next.done) {
        if (!terminal && !signal.aborted) {
          throw new KnowledgeAdapterError({
            code: "INVALID_RESPONSE",
            message: "知识服务 SSE 缺少 terminal 事件。",
            retryable: false,
            requestId: requestIdValue,
          });
        }
        break;
      }
    }
  } finally {
    signal.removeEventListener("abort", cancelReader);
    reader.releaseLock();
  }
}
export function createRequestContext(
  expectedVersion?: string,
): KnowledgeRequestContext {
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
    return {
      ok: false,
      reason: "Artifact 内容包含不允许的脚本或外部网络能力。",
    };
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
