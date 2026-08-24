import { GeneratedClientHttpError } from "./generatedClient";
import {
  KnowledgeAdapterError,
  type KnowledgeError,
  type KnowledgeErrorCode,
} from "./typedPorts";

let requestSequence = 0;
export function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  requestSequence += 1;
  return `kw-${Date.now().toString(36)}-${requestSequence.toString(36)}`;
}
export const TRANSPORT_SCHEMA_VERSION = "knowledge-workspace.transport.v1";
export function isJsonMediaType(contentType: string): boolean {
  return (
    contentType.includes("application/json") || contentType.includes("+json")
  );
}
export function isEventStreamMediaType(contentType: string): boolean {
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
export async function errorFromResponse(
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

export function errorFromGeneratedClient(
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
export async function readJson(
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
