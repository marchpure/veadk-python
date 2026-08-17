import type { DataStudioAssetType, SkillHit } from "./types";

export interface DataStudioGate {
  score?: number;
  passed?: boolean;
}

export interface DataStudioAsset {
  asset_type: DataStudioAssetType;
  asset_id: string;
  name: string;
  description: string;
  status: string;
  publish_state: "draft" | "validating" | "blocked" | "published" | "archived";
  gate: DataStudioGate & Record<string, unknown>;
  version: string;
  consumers: string[];
  capabilities: {
    metrics?: string[];
    dimensions?: string[];
    time_field?: string;
    example_questions?: string[];
    [key: string]: unknown;
  };
  freshness: Record<string, unknown>;
  provenance: Record<string, unknown>;
  usage_policy: {
    permission_hint?: string;
    masked_fields?: string[];
    export_allowed?: boolean;
    [key: string]: unknown;
  };
  sample_evidence: Array<Record<string, unknown>>;
  mcp_url?: string;
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
    // fall through to text
  }
  try {
    const text = await res.text();
    if (text.trim()) return text.trim();
  } catch {
    // ignore
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

function evidenceText(asset: DataStudioAsset): string[] {
  return asset.sample_evidence
    .map((item) => {
      const type = typeof item.type === "string" ? item.type : "evidence";
      const content = typeof item.content === "string" ? item.content : "";
      return content ? `${type}: ${content}` : "";
    })
    .filter(Boolean);
}

export function dataStudioAssetToHit(asset: DataStudioAsset): SkillHit {
  const metrics = Array.isArray(asset.capabilities.metrics)
    ? asset.capabilities.metrics.filter((item): item is string => typeof item === "string")
    : [];
  const dimensions = Array.isArray(asset.capabilities.dimensions)
    ? asset.capabilities.dimensions.filter((item): item is string => typeof item === "string")
    : [];
  const examples = Array.isArray(asset.capabilities.example_questions)
    ? asset.capabilities.example_questions.filter(
        (item): item is string => typeof item === "string",
      )
    : [];
  const folder = `datastudio-${asset.asset_type.replace(/_/g, "-")}-${asset.asset_id}`
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "datastudio-asset";
  return {
    source: "datastudio",
    id: `${asset.asset_type}:${asset.asset_id}`,
    name: asset.name,
    folder,
    description: asset.description,
    dataStudioAssetType: asset.asset_type,
    dataStudioAssetId: asset.asset_id,
    dataStudioVersion: asset.version,
    dataStudioGateScore:
      typeof asset.gate.score === "number" ? asset.gate.score : undefined,
    dataStudioMetrics: metrics,
    dataStudioExampleQuestions: examples,
    dataStudioPermissionHint: asset.usage_policy.permission_hint,
    dataStudioMcpUrl: asset.mcp_url,
    dataStudioTimeField:
      typeof asset.capabilities.time_field === "string"
        ? asset.capabilities.time_field
        : undefined,
    dataStudioDimensions: dimensions,
    dataStudioEvidence: evidenceText(asset),
  };
}
