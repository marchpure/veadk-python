import { withAuth } from "../../../adk/auth";
import { withLocalUser } from "../../../adk/identity";
import type { JsonObject } from "../domain/types";

const ROOT = "/api/data-workshop/v1/mcp-publications";

export type McpPublicationStatus =
  | "draft" | "provisioning" | "verifying" | "active" | "failed"
  | "retrying" | "updating" | "disabling" | "disabled" | "external-managed";

export interface McpActionPolicy {
  preset: "read_only" | "read_write" | "custom";
  actionIds?: string[];
}

export interface McpAudience {
  type: "applications" | "users_and_groups";
  clientIds?: string[];
  userIds?: string[];
  groupIds?: string[];
}

export interface McpSubject {
  publication_id: string;
  revision_id: string;
  subject_type: "user" | "group" | "application";
  subject_ref: string;
}

export interface McpRevision {
  id: string;
  publication_id: string;
  version: number;
  endpoint_ref?: string;
  connection_scope: string[];
  resolved_action_scope: string[];
  action_policy_source: McpActionPolicy;
  audience_type: McpAudience["type"];
  gateway_endpoint?: string;
  state: string;
  verification_summary: JsonObject;
  created_at: string;
}

export interface McpOperation {
  operation_id: string;
  stage: string;
  attempt: number;
  last_error?: { code?: string; message?: string; retryable?: boolean };
  updated_at: string;
}

export interface McpAudit {
  id: string;
  actor: string;
  event_type: string;
  request_id: string;
  created_at: string;
}

export interface McpPublicationView {
  publication: {
    id: string;
    name: string;
    status: McpPublicationStatus;
    active_revision_id?: string;
    created_at: string;
    updated_at: string;
  };
  activeRevision?: McpRevision;
  revisions: McpRevision[];
  subjects: McpSubject[];
  operations: McpOperation[];
  auditEvents: McpAudit[];
  capabilities: {
    audienceTypes: McpAudience["type"][];
    connectionConsoleUrl?: string;
    usersAndGroups?: { enabled: boolean; reason?: string };
  };
}

export interface CreateMcpPublicationInput {
  name: string;
  connectionIds: string[];
  actionPolicy: McpActionPolicy;
  audience: McpAudience;
  idempotencyKey: string;
}

class McpPublicationApiError extends Error {
  constructor(message: string, readonly code: string, readonly retryable: boolean) {
    super(message);
  }
}

async function call<T>(path = "", options: RequestInit = {}): Promise<T> {
  const headers = withLocalUser(new Headers(options.headers));
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(withAuth(`${ROOT}${path}`), { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = body.detail || body.error || {};
    throw new McpPublicationApiError(
      error.message || `请求失败（HTTP ${response.status}）`,
      error.code || "UNKNOWN",
      error.retryable === true,
    );
  }
  return body.data as T;
}

function key(prefix: string): string {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`;
}

export const mcpPublicationApi = {
  capabilities: () => call<McpPublicationView["capabilities"]>("/capabilities"),
  list: () => call<McpPublicationView[]>(),
  get: (id: string) => call<McpPublicationView>(`/${encodeURIComponent(id)}`),
  create: (input: Omit<CreateMcpPublicationInput, "idempotencyKey">) =>
    call<McpPublicationView>("", {
      method: "POST",
      body: JSON.stringify({ ...input, idempotencyKey: key("publish") }),
    }),
  revise: (id: string, input: Omit<CreateMcpPublicationInput, "name" | "idempotencyKey">) =>
    call<McpPublicationView>(`/${encodeURIComponent(id)}/revisions`, {
      method: "POST",
      body: JSON.stringify({ ...input, idempotencyKey: key("revision") }),
    }),
  verify: (id: string) => call<McpPublicationView>(`/${encodeURIComponent(id)}/verify`, { method: "POST" }),
  retry: (id: string) => call<McpPublicationView>(`/${encodeURIComponent(id)}/retry`, { method: "POST" }),
  rotate: (id: string) => call<McpPublicationView>(`/${encodeURIComponent(id)}/rotate-credential`, { method: "POST" }),
  disable: (id: string) => call<McpPublicationView>(`/${encodeURIComponent(id)}/disable`, { method: "POST" }),
};
