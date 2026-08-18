import {
  KnowledgeAssetError,
  listKnowledgeAssets,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetType,
  type KnowledgeCapabilityKind,
} from "../../adk/knowledgeAssets";
import type { DataStudioAssetType, DataStudioCapabilityKind, SkillHit } from "./types";

export { KnowledgeAssetError };

export interface KnowledgeAssetPickerResponse {
  assets: KnowledgeAssetMetadata[];
  total: number;
  page: number;
  pageSize: number;
  mock?: boolean;
}

function labelArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      const record = item as Record<string, unknown>;
      for (const key of ["id", "name", "businessName", "field", "label"]) {
        if (typeof record[key] === "string" && record[key].trim()) {
          return record[key].trim();
        }
      }
      return "";
    })
    .filter(Boolean);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function compactLabels(values: unknown[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const label = String(value ?? "").trim();
    if (!label || seen.has(label)) continue;
    seen.add(label);
    out.push(label);
  }
  return out;
}

function collectSourceCoverage(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  const labels: unknown[] = [];
  for (const key of [
    "source_label",
    "source_name",
    "source",
    "datasource",
    "datasource_kind",
    "source_resource_type",
    "provider",
    "knowledge_base_id",
    "default_knowledge_base_id",
  ]) {
    labels.push(record[key]);
  }
  for (const key of ["sources", "source_ids", "sourceIds", "lineage"]) {
    const value = record[key];
    if (!Array.isArray(value)) continue;
    for (const item of value) {
      if (typeof item === "string") {
        labels.push(item);
      } else if (item && typeof item === "object") {
        const child = item as Record<string, unknown>;
        labels.push(
          child.name ??
            child.label ??
            child.title ??
            child.id ??
            child.source_id ??
            child.sourceId,
        );
      }
    }
  }
  return compactLabels(labels);
}

const SENSITIVE_PACKAGE_KEY_RE =
  /(authorization|cookie|credential|secret|token|password|api[_-]?key|connection[_-]?obj|connection[_-]?string|session|dsn)/i;
const SENSITIVE_PACKAGE_VALUE_RE =
  /(bearer\s+[a-z0-9._~-]+|password\s*=|:\/\/[^/\s:@]+:[^@\s]+@|-----BEGIN [A-Z ]*PRIVATE KEY-----)/i;

function safeStructuredValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safeStructuredValue);
  if (typeof value === "string" && SENSITIVE_PACKAGE_VALUE_RE.test(value)) {
    return "[REDACTED]";
  }
  if (!value || typeof value !== "object") return value;
  const out: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    out[key] = SENSITIVE_PACKAGE_KEY_RE.test(key)
      ? "[REDACTED]"
      : safeStructuredValue(child);
  }
  return out;
}

function safeRecord(value: unknown): Record<string, unknown> | undefined {
  const safe = safeStructuredValue(value);
  return safe && typeof safe === "object" && !Array.isArray(safe)
    ? (safe as Record<string, unknown>)
    : undefined;
}

export function knowledgeCapabilityLabel(
  type?: string,
  kind?: string,
): string {
  if (kind === "retrieval_binding" || type === "knowledge_resource") {
    return "资料检索";
  }
  if (kind === "dashboard_skill" || type === "dashboard") {
    return "Dashboard 指标 Skill";
  }
  return "语义问数 Skill";
}

export function knowledgeAssetTypeLabel(type?: string): string {
  if (type === "knowledge_resource") return "检索绑定";
  if (type === "dashboard") return "Dashboard Skill";
  return "Semantic Skill";
}

export function knowledgeSourceCoverageText(values?: string[]): string {
  const labels = compactLabels(values ?? []);
  if (!labels.length) return "来源待声明";
  return labels.slice(0, 3).join(" + ");
}

function evidenceText(asset: KnowledgeAssetMetadata): string[] {
  return (asset.sample_evidence ?? [])
    .map((item) => {
      const type =
        typeof item.kind === "string"
          ? item.kind
          : typeof item.type === "string"
            ? item.type
            : "evidence";
      if (typeof item.content === "string" && item.content.trim()) {
        return `${type}: ${item.content.trim()}`;
      }
      const parts: string[] = [];
      for (const key of ["title", "metric", "definition", "formula"]) {
        if (typeof item[key] === "string" && item[key].trim()) {
          parts.push(`${key}=${item[key].trim()}`);
        }
      }
      if (item.policy && typeof item.policy === "object") {
        parts.push(`policy=${JSON.stringify(item.policy)}`);
      }
      return parts.length ? `${type}: ${parts.join("; ")}` : "";
    })
    .filter(Boolean);
}

function assetToDataStudioType(type: KnowledgeAssetType): DataStudioAssetType {
  return type;
}

function capabilityKind(kind: KnowledgeCapabilityKind): DataStudioCapabilityKind {
  return kind;
}

export function knowledgeAssetToHit(asset: KnowledgeAssetMetadata): SkillHit {
  const capabilities = asset.capabilities ?? {};
  const packagePayload = asset.capability_package ?? {};
  const metrics = labelArray(capabilities.metrics);
  const dimensions = labelArray(capabilities.dimensions);
  const examples = stringArray(capabilities.example_questions);
  const sourceCoverage = compactLabels([
    ...collectSourceCoverage(packagePayload),
    ...collectSourceCoverage(asset.provenance),
    ...collectSourceCoverage(asset.capabilities),
  ]);
  const folder =
    `knowledge-${asset.asset_type.replace(/_/g, "-")}-${asset.asset_id}`
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64) || "knowledge-asset";
  return {
    source: "datastudio",
    id: `${asset.asset_type}:${asset.asset_id}`,
    name: asset.name,
    folder,
    description: asset.description ?? "",
    dataStudioAssetType: assetToDataStudioType(asset.asset_type),
    dataStudioAssetId: asset.asset_id,
    dataStudioCapabilityKind: capabilityKind(
      asset.capability_kind ??
        (asset.asset_type === "knowledge_resource"
          ? "retrieval_binding"
          : asset.asset_type === "dashboard"
            ? "dashboard_skill"
            : "semantic_skill"),
    ),
    dataStudioCapabilityPackage: safeRecord(packagePayload),
    dataStudioVersion: asset.version ?? undefined,
    dataStudioGateScore:
      typeof asset.gate?.score === "number" ? asset.gate.score : undefined,
    dataStudioMetrics: metrics,
    dataStudioExampleQuestions: examples,
    dataStudioPermissionHint:
      typeof asset.usage_policy?.permission_hint === "string"
        ? asset.usage_policy.permission_hint
        : undefined,
    dataStudioQueryUrl: asset.query_url ?? undefined,
    dataStudioTimeField:
      typeof capabilities.time_field === "string"
        ? capabilities.time_field
        : undefined,
    dataStudioDimensions: dimensions,
    dataStudioEvidence: evidenceText(asset),
    dataStudioSourceCoverage: sourceCoverage,
    dataStudioFreshness: safeRecord(asset.freshness),
    dataStudioProvenance: safeRecord(asset.provenance),
    dataStudioUsagePolicy: safeRecord(asset.usage_policy),
  };
}

export async function listKnowledgeAssetCapabilities({
  query = "",
  page = 1,
  pageSize = 12,
}: {
  query?: string;
  page?: number;
  pageSize?: number;
} = {}): Promise<KnowledgeAssetPickerResponse> {
  const payload = await listKnowledgeAssets({
    query,
    limit: pageSize,
    cursor: page > 1 ? String((page - 1) * pageSize) : null,
  });
  return {
    assets: payload.items ?? [],
    total: payload.total ?? payload.items?.length ?? 0,
    page,
    pageSize,
    mock: payload.mock,
  };
}
