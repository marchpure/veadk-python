import type { DataStudioAssetType, SkillHit } from "./types.ts";

export interface DataStudioAsset {
  asset_type: DataStudioAssetType;
  asset_id: string;
  name: string;
  description?: string;
  status?: string;
  publish_state: "draft" | "validating" | "blocked" | "published" | "archived";
  gate?: { score?: number; [key: string]: unknown };
  version?: string;
  consumers?: string[];
  capabilities?: {
    metrics?: string[];
    dimensions?: string[];
    time_field?: string;
    default_time_field?: string;
    example_questions?: string[];
    [key: string]: unknown;
  };
  query_url?: string;
  freshness?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  usage_policy?: {
    permission_hint?: string;
    [key: string]: unknown;
  };
  sample_evidence?: Array<Record<string, unknown>>;
}

export interface DataStudioAssetsResponse {
  assets: DataStudioAsset[];
  total: number;
  page: number;
  pageSize: number;
  nextCursor?: string | null;
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
    nextCursor: payload.nextCursor,
    mock: payload.mock,
  };
}

function evidenceText(asset: DataStudioAsset): string[] {
  return (asset.sample_evidence ?? [])
    .map((item) => {
      const type = typeof item.type === "string" ? item.type : "evidence";
      const content = typeof item.content === "string" ? item.content : "";
      return content ? `${type}: ${content}` : "";
    })
    .filter(Boolean);
}

function cleanFolder(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/_/g, "-")
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64) || "datastudio-asset"
  );
}

export function dataStudioAssetToHit(asset: DataStudioAsset): SkillHit {
  const capabilities = asset.capabilities ?? {};
  const metrics = Array.isArray(capabilities.metrics)
    ? capabilities.metrics.filter((item): item is string => typeof item === "string")
    : [];
  const dimensions = Array.isArray(capabilities.dimensions)
    ? capabilities.dimensions.filter((item): item is string => typeof item === "string")
    : [];
  const examples = Array.isArray(capabilities.example_questions)
    ? capabilities.example_questions.filter((item): item is string => typeof item === "string")
    : [];
  const folder = cleanFolder(`datastudio-${asset.asset_type}-${asset.asset_id}`);
  return {
    source: "datastudio",
    id: `${asset.asset_type}:${asset.asset_id}`,
    name: asset.name,
    folder,
    description: asset.description ?? "",
    dataStudioAssetType: asset.asset_type,
    dataStudioAssetId: asset.asset_id,
    dataStudioVersion: asset.version ?? "",
    dataStudioGateScore: typeof asset.gate?.score === "number" ? asset.gate.score : undefined,
    dataStudioMetrics: metrics,
    dataStudioExampleQuestions: examples,
    dataStudioPermissionHint: asset.usage_policy?.permission_hint ?? "",
    dataStudioQueryUrl: asset.query_url ?? "",
    dataStudioTimeField:
      typeof capabilities.time_field === "string"
        ? capabilities.time_field
        : typeof capabilities.default_time_field === "string"
          ? capabilities.default_time_field
          : "",
    dataStudioDimensions: dimensions,
    dataStudioEvidence: evidenceText(asset),
  };
}
