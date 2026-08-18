import type { DataStudioAssetType, SkillHit } from "./types";

export interface DataStudioGate {
  score?: number;
  passed?: boolean;
}

export interface DataStudioAsset {
  asset_type: DataStudioAssetType;
  asset_id: string;
  name: string;
  description?: string;
  status?: string;
  publish_state: "draft" | "validating" | "blocked" | "published" | "archived";
  gate?: DataStudioGate & Record<string, unknown>;
  version?: string;
  consumers?: string[];
  capabilities?: {
    metrics?: Array<string | Record<string, unknown>>;
    dimensions?: Array<string | Record<string, unknown>>;
    time_field?: string;
    example_questions?: string[];
    [key: string]: unknown;
  };
  freshness?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  usage_policy?: {
    permission_hint?: string;
    masked_fields?: string[];
    export_allowed?: boolean;
    [key: string]: unknown;
  };
  sample_evidence?: Array<Record<string, unknown>>;
  query_url?: string;
}

export interface DataStudioAssetsResponse {
  assets: DataStudioAsset[];
  total: number;
  page: number;
  pageSize: number;
  mock?: boolean;
}

export class DataStudioError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "DataStudioError";
    this.status = status;
  }
}

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const payload = await res.json();
    if (typeof payload?.detail === "string") return payload.detail;
    if (typeof payload?.message === "string") return payload.message;
  } catch {
    // Fall through to text.
  }
  try {
    const text = await res.text();
    if (text.trim()) return text.trim();
  } catch {
    // Ignore.
  }
  return fallback;
}

export async function listDataStudioAssets({
  query = "",
  page = 1,
  pageSize = 12,
}: {
  query?: string;
  page?: number;
  pageSize?: number;
} = {}): Promise<DataStudioAssetsResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (query.trim()) params.set("q", query.trim());
  const res = await fetch(`/web/datastudio/assets?${params.toString()}`);
  if (!res.ok) {
    throw new DataStudioError(
      res.status,
      await errorMessage(res, `Data Studio assets failed: ${res.status}`),
    );
  }
  const payload = (await res.json()) as Partial<DataStudioAssetsResponse>;
  return {
    assets: payload.assets ?? [],
    total: payload.total ?? payload.assets?.length ?? 0,
    page: payload.page ?? page,
    pageSize: payload.pageSize ?? pageSize,
    mock: payload.mock,
  };
}

function labelArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      const record = item as Record<string, unknown>;
      for (const key of ["id", "name", "businessName", "field"]) {
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

function evidenceText(asset: DataStudioAsset): string[] {
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

export function dataStudioAssetToHit(asset: DataStudioAsset): SkillHit {
  const capabilities = asset.capabilities ?? {};
  const metrics = labelArray(capabilities.metrics);
  const dimensions = labelArray(capabilities.dimensions);
  const examples = stringArray(capabilities.example_questions);
  const folder =
    `datastudio-${asset.asset_type.replace(/_/g, "-")}-${asset.asset_id}`
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64) || "datastudio-asset";
  return {
    source: "datastudio",
    id: `${asset.asset_type}:${asset.asset_id}`,
    name: asset.name,
    folder,
    description: asset.description ?? "",
    dataStudioAssetType: asset.asset_type,
    dataStudioAssetId: asset.asset_id,
    dataStudioVersion: asset.version,
    dataStudioGateScore:
      typeof asset.gate?.score === "number" ? asset.gate.score : undefined,
    dataStudioMetrics: metrics,
    dataStudioExampleQuestions: examples,
    dataStudioPermissionHint: asset.usage_policy?.permission_hint,
    dataStudioQueryUrl: asset.query_url,
    dataStudioTimeField:
      typeof capabilities.time_field === "string" ? capabilities.time_field : undefined,
    dataStudioDimensions: dimensions,
    dataStudioEvidence: evidenceText(asset),
  };
}
