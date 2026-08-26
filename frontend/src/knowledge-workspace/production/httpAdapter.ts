import {
  parseBootstrap,
  type KnowledgeBootstrap,
} from "./bootstrapSchema";
import {
  createKnowledgeAssetClient,
  GeneratedClientHttpError,
  type KnowledgeAssetClient,
} from "./generatedClient";
import type { GeneratedLegacyManifest, GeneratedManifest } from "./generated";
import {
  KnowledgeAdapterError,
  type KnowledgeCommand,
  type KnowledgeCommandName,
  type KnowledgeCommandResult,
  type KnowledgeError,
  type KnowledgeErrorCode,
  type KnowledgeRequestContext,
  type KnowledgeStream,
  type KnowledgeStreamEvent,
  type KnowledgeStreamCommand,
  type WorkspaceAdapter,
} from "./typedPorts";
import {
  requestId,
  isJsonMediaType,
  isEventStreamMediaType,
  errorFromGeneratedClient,
  errorFromResponse,
  readJson,
  TRANSPORT_SCHEMA_VERSION,
} from "./httpSupport";

type LegacyCommandName = KnowledgeCommandName;
type KnowledgeCommandEnvelope = Parameters<KnowledgeAssetClient["command"]>[0];

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
    const body = await this.generatedClient.bootstrap(signal);
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
    try {
      const generated = await this.generatedClient.command(
        toGeneratedCommand(normalized.command),
        context,
      );
      if (
        (normalized.command.command === "skill-draft.run" ||
          normalized.command.command === "skill-draft.retry") &&
        generated.operationId &&
        !generated.result
      ) {
        return await this.waitForBuilderOperation(
          generated.operationId,
          context.requestId,
          context.signal,
        );
      }
      return parseCommandResult(generated, context.requestId);
    } catch (error) {
      if (error instanceof GeneratedClientHttpError) {
        throw errorFromGeneratedClient(error, context.requestId);
      }
      throw error;
    }
  }
  private async waitForBuilderOperation(
    operationId: string,
    requestIdValue: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeCommandResult> {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (signal?.aborted) {
        throw new KnowledgeAdapterError({
          code: "CANCELLED",
          message: "Builder Operation 已取消。",
          retryable: true,
          requestId: requestIdValue,
        });
      }
      const operation = await this.generatedClient.operation(operationId, signal);
      if (
        operation.status === "succeeded" ||
        operation.status === "failed" ||
        operation.status === "cancelled"
      ) {
        return parseCommandResult(
          {
            accepted: operation.status === "succeeded",
            requestId: requestIdValue,
            operationId,
            result: operation.result,
          },
          requestIdValue,
        );
      }
      await new Promise<void>((resolve) => globalThis.setTimeout(resolve, 100));
    }
    throw new KnowledgeAdapterError({
      code: "TIMEOUT",
      message: "Builder Operation 等待超时。",
      retryable: true,
      requestId: requestIdValue,
    });
  }
  async stream(
    command: KnowledgeStreamCommand | "assistant.turn",
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
      response = await this.generatedClient.stream(
        toGeneratedCommand(normalized.command),
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
                    sourceId: normalized.command.payload.sourceId,
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
            await this.command(cancelCommand, cancelContext);
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
  const result = value.result;
  if (
    result &&
    typeof result === "object" &&
    (result as Record<string, unknown>).resultType === "skill-authoring.start"
  ) {
    const authoring = result as Record<string, unknown>;
    const operation = authoring.operation;
    if (operation && typeof operation === "object") {
      const operationRecord = operation as Record<string, unknown>;
      if (
        operationRecord.clarification_questions !== undefined &&
        operationRecord.clarificationQuestions === undefined
      ) {
        operationRecord.clarificationQuestions =
          operationRecord.clarification_questions;
      }
    }
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
  command: KnowledgeStreamCommand | "assistant.turn",
  contextOrPayload: KnowledgeRequestContext | Record<string, unknown>,
  legacyContext?: KnowledgeRequestContext,
): {
  command: KnowledgeStreamCommand;
  context: KnowledgeRequestContext;
} {
  if (typeof command !== "string") {
    return { command, context: contextOrPayload as KnowledgeRequestContext };
  }
  return {
    command: legacyCommand(command, contextOrPayload as Record<string, unknown>) as KnowledgeStreamCommand,
    context: legacyContext ?? (contextOrPayload as KnowledgeRequestContext),
  };
}

function toGeneratedCommand(command: KnowledgeCommand): KnowledgeCommandEnvelope {
  return command as unknown as KnowledgeCommandEnvelope;
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
      return {
        command,
        payload: {
          targetId: "legacy",
          suiteId: "default-step3",
          environment: "test",
          caseIds: [],
        },
      };
    case "source.profile":
      return {
        command,
        payload: { sourceRevisionId: "legacy", sampleLimit: 100 },
      };
    case "source.clean":
      return {
        command,
        payload: { sourceRevisionId: "legacy", recipeId: "legacy" },
      };
    case "source-golden.connection.create":
      return {
        command,
        payload: {
          connectorKey: typeof payload.connectorKey === "string"
            ? payload.connectorKey
            : "legacy",
          displayName: typeof payload.displayName === "string"
            ? payload.displayName
            : "Legacy connection",
          scope: payload.scope === "team" ? "team" : "personal",
          configuration: {},
        },
      };
    case "source-golden.ingest":
      return {
        command,
        payload: {
          connectionId: typeof payload.connectionId === "string"
            ? payload.connectionId
            : "legacy",
          recipeOperations: ["trim"],
          toolArguments: {},
        },
      };
    case "skill-draft.run":
      return {
        command,
        payload: {
          draftId: "legacy",
          revision: 1,
          traceId: "legacy",
          maxSteps: 10,
          budget: 10_000,
        },
      };
    case "skill-draft.retry":
      return {
        command,
        payload: {
          draftId: "legacy",
          revision: 1,
          traceId: "legacy",
          maxSteps: 10,
          budget: 10_000,
          retryOfOperationId: "legacy",
        },
      };
    case "publication.publish":
      return {
        command,
        payload: { draftId: "legacy", revision: 1, semver: "1.0.0", visibility: "team" },
      };
    case "refresh.run":
      return {
        command,
        payload: { skillId: "legacy", trigger: "manual" },
      };
    case "invocation.start":
      return {
        command,
        payload: {
          skillVersionId: "legacy",
          skillViewRevisionId: "legacy",
          inputRef: {
            uri: "inline://legacy",
            kind: "inline",
            sha256: "0".repeat(64),
            mediaType: "application/json",
          },
          callerId: "legacy",
        },
      };
    case "skill-authoring.start":
      return {
        command,
        payload: {
          prompt: typeof payload.prompt === "string" ? payload.prompt : "",
          requestedKind: "knowledge",
          scope: "personal",
        },
      };
    case "skill-authoring.answer":
      return {
        command,
        payload: {
          prompt: typeof payload.prompt === "string" ? payload.prompt : "",
        },
      };
    case "skill-authoring.patch":
      return {
        command,
        payload: {
          draftId: typeof payload.draftId === "string" ? payload.draftId : "",
          baseRevision: typeof payload.baseRevision === "number"
            ? payload.baseRevision
            : 1,
          patch: payload.patch as import("./generatedContracts").SkillAuthoringPatchPayload["patch"],
        },
      };
    case "skill-authoring.execute":
      return {
        command,
        payload: {
          draftId: typeof payload.draftId === "string" ? payload.draftId : "",
          revision: typeof payload.revision === "number" ? payload.revision : null,
        },
      };
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
