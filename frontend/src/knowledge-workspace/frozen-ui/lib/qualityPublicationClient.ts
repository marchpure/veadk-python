import { createRequestContext } from "../../production/ports";
import { bootstrapWorkspace, getWorkspaceAdapter } from "../../production/store";

type CommandEnvelope = {
  command: string;
  payload: Record<string, unknown>;
};

export type ServerCommandResult = {
  accepted: boolean;
  requestId: string;
  operationId?: string;
  result?: Record<string, unknown>;
};

export type PublishedSkillOption = {
  id: string;
  skillId: string;
  version: string;
  revision: string;
  status: string;
  skillViewRevisionId: string;
  name: string;
  manifest?: Record<string, unknown>;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  dependencies: string[];
  permissions: string[];
  compatibilityTargets: string[];
  qualityScore?: string;
  invocationCount?: string;
  freshness?: string;
  consumerCount?: string;
  callerRef?: string;
  dataRevisionRefs: string[];
};

export type ServerBackedHistoryItem = {
  id: string;
  label: string;
  status: string;
  detail: string;
  createdAt?: string;
};

function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `kw-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function commandErrorMessage(result: ServerCommandResult | null | undefined): string {
  const error = asRecord(result?.result?.error);
  return String(error.message ?? "服务端未接受此操作；本地不会伪造完成状态。");
}

export async function postKnowledgeCommand(
  envelope: CommandEnvelope,
): Promise<ServerCommandResult> {
  const context = createRequestContext();
  const response = await fetch("/api/knowledge-assets/v1/commands", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Request-ID": context.requestId,
      "Idempotency-Key": context.idempotencyKey,
    },
    body: JSON.stringify(envelope),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = asRecord(payload);
    throw new Error(String(error.message ?? `知识服务请求失败: ${response.status}`));
  }
  return payload as ServerCommandResult;
}

export async function runTypedCommand(
  envelope: CommandEnvelope,
): Promise<ServerCommandResult> {
  const result = await postKnowledgeCommand(envelope);
  await bootstrapWorkspace(undefined, getWorkspaceAdapter()).catch(() => undefined);
  return result;
}

export async function inlineJsonStorageRef(
  value: unknown,
  purpose: string,
): Promise<{ uri: string; kind: "inline"; sha256: string; mediaType: "application/json"; bytes: number }> {
  const encoded = new TextEncoder().encode(JSON.stringify(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", encoded);
  const sha256 = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return {
    uri: `inline://knowledge-workspace/${purpose}/${sha256}`,
    kind: "inline",
    sha256,
    mediaType: "application/json",
    bytes: encoded.byteLength,
  };
}

export function publishedSkillOptions(publications: unknown[]): PublishedSkillOption[] {
  return publications
    .map((item) => {
      const raw = asRecord(item);
      const manifest = asRecord(raw.manifest);
      const spec = asRecord(manifest.spec);
      const contract = asRecord(spec.contract);
      const dependencies = asRecord(spec.dependencies);
      const metadata = asRecord(manifest.metadata);
      const skillViewRevisionId = String(raw.skillViewRevisionId ?? raw.skillViewRef ?? "");
      return {
        id: String(raw.id ?? ""),
        skillId: String(raw.skillId ?? ""),
        version: String(raw.version ?? raw.semver ?? ""),
        revision: String(raw.revision ?? ""),
        status: String(raw.status ?? ""),
        skillViewRevisionId,
        name: String(metadata.name ?? raw.name ?? raw.skillId ?? raw.id ?? "Published Skill"),
        manifest,
        inputSchema: asRecord(contract.inputSchema),
        outputSchema: asRecord(contract.outputSchema),
        dependencies: [
          ...Object.values(asRecord(dependencies)).flatMap((value) =>
            Array.isArray(value) ? value : value ? [String(value)] : []
          ),
        ].map(String),
        permissions: Array.isArray(spec.permissions)
          ? spec.permissions.map(String)
          : Array.isArray(raw.permissions)
          ? raw.permissions.map(String)
          : [],
        compatibilityTargets: Array.isArray(spec.compatibilityTargets)
          ? spec.compatibilityTargets.map(String)
          : Array.isArray(raw.compatibilityTargets)
          ? raw.compatibilityTargets.map(String)
          : [],
        qualityScore: raw.qualityScore === undefined ? undefined : String(raw.qualityScore),
        invocationCount: raw.invocationCount === undefined ? undefined : String(raw.invocationCount),
        freshness: raw.freshness === undefined ? undefined : String(raw.freshness),
        consumerCount: raw.consumerCount === undefined ? undefined : String(raw.consumerCount),
        callerRef: raw.callerRef === undefined ? undefined : String(raw.callerRef),
        dataRevisionRefs: Array.isArray(raw.dataRevisionRefs)
          ? raw.dataRevisionRefs.map(String)
          : [],
      };
    })
    .filter((item) =>
      item.id &&
      item.status === "published" &&
      item.id.startsWith("published://") &&
      item.skillViewRevisionId
    );
}

export function historyFromBootstrap(
  publications: unknown[],
  resources: unknown[],
): ServerBackedHistoryItem[] {
  const publicationItems = publishedSkillOptions(publications).map((item) => ({
    id: item.id,
    label: `Published Skill ${item.version}`,
    status: item.status,
    detail: `skill=${item.skillId}; revision=${item.revision}; view=${item.skillViewRevisionId}`,
  }));
  const resourceItems = resources
    .map(asRecord)
    .filter((item) => item.id || item.displayName || item.name)
    .map((item) => ({
      id: String(item.id ?? item.displayName ?? item.name),
      label: String(item.displayName ?? item.name ?? item.id),
      status: String(item.lifecycle ?? item.status ?? "server"),
      detail: `kind=${String(item.resourceKind ?? item.type ?? "resource")}; version=${String(item.version ?? "—")}`,
      createdAt: typeof item.createdAt === "string" ? item.createdAt : undefined,
    }));
  return [...publicationItems, ...resourceItems];
}

export function buildEvaluationCase(
  id: string,
  question: string,
  expected: string,
  category = "normal",
  source = "manual",
  candidateConfirmed = false,
): Record<string, unknown> {
  return {
    id,
    source,
    category,
    input: { question },
    expected: { answer: expected },
    grading: { method: "exact" },
    candidateConfirmed,
  };
}

export function nextStableId(prefix: string): string {
  return `${prefix}-${requestId().replaceAll("-", "").slice(0, 16)}`;
}
