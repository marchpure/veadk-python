import type {
  GeneratedBootstrap,
  GeneratedCommand,
  GeneratedCommandResponse,
  GeneratedOperation,
  GeneratedOperationAudit,
} from "./generated";
import {
  assertGeneratedBootstrap,
  assertGeneratedCommandResponse,
  assertGeneratedOperation,
  assertGeneratedOperationAudit,
} from "./generated";

export class GeneratedClientHttpError extends Error {
  readonly status: number;
  readonly contentType: string;
  readonly headers: Record<string, string>;
  readonly body: unknown;

  constructor(
    status: number,
    contentType: string,
    headers: Record<string, string>,
    body: unknown,
  ) {
    super(`Knowledge Asset BFF returned ${status}`);
    this.name = "GeneratedClientHttpError";
    this.status = status;
    this.contentType = contentType;
    this.headers = headers;
    this.body = body;
  }
}

export interface KnowledgeAssetClient {
  bootstrap(signal?: AbortSignal): Promise<GeneratedBootstrap>;
  command(
    command: GeneratedCommand,
    context: {
      requestId: string;
      idempotencyKey: string;
      expectedVersion?: string;
      lastEventId?: string;
      signal?: AbortSignal;
    },
  ): Promise<GeneratedCommandResponse>;
  operation(operationId: string, signal?: AbortSignal): Promise<GeneratedOperation>;
  audit(operationId: string, signal?: AbortSignal): Promise<GeneratedOperationAudit>;
  stream(
    command: GeneratedCommand,
      context: {
      requestId: string;
      idempotencyKey: string;
      expectedVersion?: string;
      lastEventId?: string;
      signal?: AbortSignal;
    },
  ): Promise<Response>;
  cancel(
    operationId: string,
    context: { requestId: string; idempotencyKey: string; signal?: AbortSignal },
  ): Promise<GeneratedOperation>;
}

export function createKnowledgeAssetClient(
  fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
  basePath = "/api/knowledge-assets/v1",
): KnowledgeAssetClient {
  const request = async (
    path: string,
    init: RequestInit = {},
    signal?: AbortSignal,
  ): Promise<unknown> => {
    const response = await fetcher(`${basePath}${path}`, {
      ...init,
      signal,
      headers: {
        Accept: "application/json",
        ...init.headers,
      },
    });
    const contentType = response.headers.get("content-type") ?? "";
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // The typed transport error still carries status and headers.
    }
    if (!response.ok) {
      const headers: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        headers[key] = value;
      });
      throw new GeneratedClientHttpError(
        response.status,
        contentType,
        headers,
        body,
      );
    }
    return body;
  };
  return {
    bootstrap: async (signal) => {
      const workspace =
        typeof globalThis.location !== "undefined"
          ? new URLSearchParams(globalThis.location.search).get("workspace")
          : null;
      const path = workspace
        ? `/bootstrap?workspace=${encodeURIComponent(workspace)}`
        : "/bootstrap";
      return assertGeneratedBootstrap(await request(path, {}, signal));
    },
    command: (command, context) =>
      request(
        "/commands",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": context.requestId,
            "Idempotency-Key": context.idempotencyKey,
            ...(command.command === "skill-draft.run" ||
            command.command === "skill-draft.retry"
              ? { Prefer: "respond-async" }
              : {}),
            ...(context.expectedVersion ? { "If-Match": context.expectedVersion } : {}),
            ...(context.lastEventId ? { "Last-Event-ID": context.lastEventId } : {}),
          },
          body: JSON.stringify(command),
        },
        context.signal,
      ).then(assertGeneratedCommandResponse),
    operation: (operationId, signal) =>
      request(
        `/operations/${encodeURIComponent(operationId)}`,
        {},
        signal,
      ).then(assertGeneratedOperation),
    audit: (operationId, signal) =>
      request(
        `/operations/${encodeURIComponent(operationId)}/audit`,
        {},
        signal,
      ).then(assertGeneratedOperationAudit),
    stream: async (command, context) => {
      const response = await fetcher(`${basePath}/streams`, {
        method: "POST",
        signal: context.signal,
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
          "X-Request-ID": context.requestId,
          "Idempotency-Key": context.idempotencyKey,
          ...(context.expectedVersion ? { "If-Match": context.expectedVersion } : {}),
          ...(context.lastEventId ? { "Last-Event-ID": context.lastEventId } : {}),
        },
        body: JSON.stringify(command),
      });
      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        let body: unknown = null;
        try { body = await response.json(); } catch { /* problem body optional */ }
        const headers: Record<string, string> = {};
        response.headers.forEach((value, key) => { headers[key] = value; });
        throw new GeneratedClientHttpError(
          response.status, contentType, headers, body,
        );
      }
      return response;
    },
    cancel: (operationId, context) =>
      request(
        `/operations/${encodeURIComponent(operationId)}:cancel`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": context.requestId,
            "Idempotency-Key": context.idempotencyKey,
          },
        },
        context.signal,
      ).then(assertGeneratedOperation),
  };
}
