import type {
  AuthoringEvent,
  AuthoringStreamOptions,
  StartedAuthoringOperation,
  StartAuthoringInput,
} from "./contracts";
import { parseAuthoringSse } from "./sse";

const API_ROOT = "/api/knowledge-assets/v1";

export class AuthoringHttpError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly requestId?: string;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      requestId?: string;
      retryable?: boolean;
    },
  ) {
    super(message);
    this.name = "AuthoringHttpError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
    this.retryable = options.retryable ?? options.status >= 500;
  }
}

function requestId(value?: string): string {
  return value ?? crypto.randomUUID();
}

async function throwHttpError(response: Response, action: string): Promise<never> {
  let body: Record<string, unknown> = {};
  try {
    body = await response.json() as Record<string, unknown>;
  } catch {
    // Gateways can return HTML/plain text. Keep that body out of the UI.
  }
  throw new AuthoringHttpError(
    typeof body.message === "string"
      ? body.message
      : `${action} failed with HTTP ${response.status}.`,
    {
      status: response.status,
      code: typeof body.code === "string" ? body.code : undefined,
      requestId:
        typeof body.requestId === "string" ? body.requestId : undefined,
      retryable:
        typeof body.retryable === "boolean" ? body.retryable : undefined,
    },
  );
}

export async function startAuthoringOperation(
  input: StartAuthoringInput,
  options: AuthoringStreamOptions & { idempotencyKey?: string } = {},
): Promise<StartedAuthoringOperation> {
  const response = await fetch(`${options.baseUrl ?? API_ROOT}/streams`, {
    method: "POST",
    credentials: "same-origin",
    signal: options.signal,
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      "X-Request-ID": requestId(options.requestId),
      "Idempotency-Key": options.idempotencyKey ?? crypto.randomUUID(),
      ...(options.lastEventId
        ? { "Last-Event-ID": options.lastEventId }
        : {}),
    },
    body: JSON.stringify({
      command: "skill-authoring.start",
      payload: input,
    }),
  });
  if (!response.ok) await throwHttpError(response, "Starting authoring");
  const operationId = response.headers.get("X-Operation-ID")?.trim();
  if (!operationId) {
    await response.body?.cancel();
    throw new Error("Authoring stream did not identify its operation.");
  }
  return {
    operationId,
    events: parseAuthoringSse(response),
  };
}

export async function* followAuthoringOperation(
  operationId: string,
  options: AuthoringStreamOptions = {},
): AsyncGenerator<AuthoringEvent> {
  const response = await fetch(
    `${options.baseUrl ?? API_ROOT}/authoring/operations/${encodeURIComponent(operationId)}/events`,
    {
      method: "GET",
      credentials: "same-origin",
      signal: options.signal,
      headers: {
        Accept: "text/event-stream",
        "X-Request-ID": options.requestId ?? crypto.randomUUID(),
        ...(options.lastEventId
          ? { "Last-Event-ID": options.lastEventId }
          : {}),
      },
    },
  );
  if (!response.ok) {
    await throwHttpError(response, "Authoring stream");
  }
  yield* parseAuthoringSse(response);
}

async function operationAction(
  operationId: string,
  action: "cancel" | "retry",
  options: Pick<AuthoringStreamOptions, "baseUrl" | "signal" | "requestId"> = {},
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `${options.baseUrl ?? API_ROOT}/authoring/operations/${encodeURIComponent(operationId)}:${action}`,
    {
      method: "POST",
      credentials: "same-origin",
      signal: options.signal,
      headers: {
        Accept: "application/json",
        "X-Request-ID": requestId(options.requestId),
      },
    },
  );
  if (!response.ok) {
    await throwHttpError(response, `Authoring ${action}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export const cancelAuthoringOperation = (
  operationId: string,
  options?: Pick<AuthoringStreamOptions, "baseUrl" | "signal" | "requestId">,
) => operationAction(operationId, "cancel", options);

export const retryAuthoringOperation = (
  operationId: string,
  options?: Pick<AuthoringStreamOptions, "baseUrl" | "signal" | "requestId">,
) => operationAction(operationId, "retry", options);
