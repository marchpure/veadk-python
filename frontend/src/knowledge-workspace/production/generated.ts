/* Generated from frontend/server/knowledge_assets/contracts.py. */

import type {
  LegacySkillManifestInput,
  SkillManifest,
} from "./generatedContracts";

export type ErrorCode =
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

export interface GeneratedError {
  code: ErrorCode | string;
  message: string;
  retryable: boolean;
  requestId: string;
  details?: Record<string, string>;
}

export type GeneratedManifest = SkillManifest;
export type GeneratedLegacyManifest = LegacySkillManifestInput;

export interface GeneratedSkillDraft {
  id: string;
  workspaceId: string;
  name: string;
  description: string;
  revision: number;
  lifecycle: "draft";
  viewState: "debug";
  createdAt: string;
  updatedAt: string;
  manifest: GeneratedManifest;
}

export interface GeneratedOperationEvent {
  schemaVersion: "knowledge-assets.event.v1";
  operationId: string;
  eventId: string;
  sequence: number;
  occurredAt: string;
  type: "accepted" | "progress" | "succeeded" | "failed" | "cancelled";
  terminal: boolean;
  result?: Record<string, unknown>;
  error?: GeneratedError;
}

export interface GeneratedOperation {
  operationId: string;
  status: "accepted" | "running" | "succeeded" | "failed" | "cancelled";
  version: number;
  events: GeneratedOperationEvent[];
  result?: Record<string, unknown>;
  error?: GeneratedError;
  nextActions: string[];
  audit: GeneratedAuditItem[];
}

export interface GeneratedAuditItem {
  requestId: string;
  operationId: string;
  workspaceId: string;
  action: string;
  resourceId: string;
  outcome: string;
  details: Record<string, unknown>;
  occurredAt: string;
}

export interface GeneratedOperationAudit {
  operationId: string;
  items: GeneratedAuditItem[];
}

export interface GeneratedBootstrap {
  resources: Array<{
    id: string;
    displayName: string;
    resourceKind: "skill_draft";
    subtype: "skill";
    space: "personal" | "team";
    lifecycle: "draft";
    version: string;
    revision: number;
    permission: boolean;
  }>;
  connections: Array<Record<string, string>>;
  publications: Array<Record<string, string>>;
  routes: string[];
  workspaceData: Record<string, unknown>;
  actionLoop: Record<string, unknown[]>;
  access: Record<string, unknown>;
  serverTime: string;
}

export type GeneratedCommand =
  | {
    command: "skill-draft.create";
    payload: {
      workspaceId: string;
      name: string;
      description: string;
      sourceRefs: string[];
    };
  }
  | {
    command: "skill-draft.save-manifest";
    payload: {
      draftId: string;
      baseRevision: number;
      manifest: GeneratedManifest | GeneratedLegacyManifest;
    };
  }
  | {
    command:
      | "resource.create"
      | "resource.update"
      | "resource.publish"
      | "resource.share"
      | "resource.revoke";
    payload: { resourceId: string };
  }
  | {
    command: "connector.create" | "connector.test";
    payload: { connectorKey: string };
  }
  | {
    command: "import.start" | "import.cancel";
    payload: { sourceId: string };
  }
  | {
    command: "stream.cancel";
    payload: {
      streamId: string;
      sourceCommand: "import.start" | "assistant.turn";
    };
  }
  | {
    command: "assistant.turn";
    payload: { text: string; contextIds: string[] };
  }
  | {
    command: "evaluation.run" | "evaluation.apply";
    payload: {
      targetId: string;
      suiteId: string;
      environment: "production" | "demo" | "test";
      caseIds: string[];
    };
  }
  | {
    command: "action.update";
    payload: { actionId: string };
  }
  | {
    command: "artifact.export";
    payload: { resourceId: string; format: "json" | "csv" | "html" };
  }
  | {
    command: "source.profile";
    payload: { sourceRevisionId: string; sampleLimit: number };
  }
  | {
    command: "source.clean";
    payload: { sourceRevisionId: string; recipeId: string };
  }
  | {
    command: "source-golden.connection.create";
    payload: import("./generatedContracts").SourceGoldenConnectionCreatePayload;
  }
  | {
    command: "source-golden.ingest";
    payload: import("./generatedContracts").SourceGoldenIngestPayload;
  }
  | {
    command: "skill-draft.retry";
    payload: {
      draftId: string;
      revision: number;
      traceId: string;
      maxSteps: number;
      budget: number;
      retryOfOperationId: string;
    };
  }
  | {
    command: "skill-draft.run";
    payload: {
      draftId: string;
      revision: number;
      traceId: string;
      maxSteps: number;
      budget: number;
    };
  }
  | {
    command: "publication.publish";
    payload: { draftId: string; revision: number; semver: string };
  }
  | {
    command: "refresh.run";
    payload: {
      skillId: string;
      trigger: "manual" | "schedule" | "event" | "freshness_on_read";
    };
  }
  | {
    command: "invocation.start";
    payload: {
      skillVersionId: string;
      inputRef: import("./generatedContracts").StorageRef;
      callerId: string;
    };
  };

export interface GeneratedCommandResponse {
  accepted: boolean;
  requestId: string;
  operationId?: string;
  result?: Record<string, unknown>;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function assertGeneratedCommandResponse(
  value: unknown,
): GeneratedCommandResponse {
  if (
    !isRecord(value) ||
    typeof value.accepted !== "boolean" ||
    typeof value.requestId !== "string" ||
    value.requestId.length === 0
  ) {
    throw new Error("Invalid Knowledge Asset command response");
  }
  return value as unknown as GeneratedCommandResponse;
}

export function assertGeneratedOperation(
  value: unknown,
): GeneratedOperation {
  if (
    !isRecord(value) ||
    typeof value.operationId !== "string" ||
    typeof value.status !== "string" ||
    !Array.isArray(value.events)
  ) {
    throw new Error("Invalid Knowledge Asset operation response");
  }
  return value as unknown as GeneratedOperation;
}

export function assertGeneratedOperationAudit(
  value: unknown,
): GeneratedOperationAudit {
  if (
    !isRecord(value) ||
    typeof value.operationId !== "string" ||
    !Array.isArray(value.items)
  ) {
    throw new Error("Invalid Knowledge Asset audit response");
  }
  return value as unknown as GeneratedOperationAudit;
}

export function assertGeneratedBootstrap(
  value: unknown,
): GeneratedBootstrap {
  if (
    !isRecord(value) ||
    !Array.isArray(value.resources) ||
    !Array.isArray(value.routes) ||
    typeof value.serverTime !== "string"
  ) {
    throw new Error("Invalid Knowledge Asset bootstrap response");
  }
  return value as unknown as GeneratedBootstrap;
}
