import type { KnowledgeAssetMetadata } from "../adk/knowledgeAssets";

export function capabilityValues(
  asset: KnowledgeAssetMetadata | undefined | null,
  key: "metrics" | "dimensions" | "relationships",
): string[] {
  const direct = asset?.capabilities?.[key];
  if (Array.isArray(direct)) return direct.map(String).filter(Boolean);
  const mdl = semanticMdl(asset);
  const items = mdl[key];
  if (!Array.isArray(items)) return [];
  return items
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        return String(record.id ?? record.name ?? record.field ?? "").trim();
      }
      return "";
    })
    .filter(Boolean);
}

export function semanticMdl(
  asset: KnowledgeAssetMetadata | undefined | null,
): Record<string, unknown> {
  const pkg = asset?.capability_package;
  if (!pkg || typeof pkg !== "object") return {};
  const inline = pkg.mdl;
  if (inline && typeof inline === "object") {
    return inline as Record<string, unknown>;
  }
  const artifacts = pkg.artifacts ?? pkg.files;
  if (!artifacts || typeof artifacts !== "object") return {};
  const files = artifacts as Record<string, unknown>;
  const models = objectValue(files["mdl/models.json"]);
  const metrics = objectValue(files["mdl/metrics.json"]);
  const dimensions = objectValue(files["mdl/dimensions.json"]);
  const relationships = objectValue(files["mdl/relationships.json"]);
  const permissions = objectValue(files["mdl/permissions.json"]);
  const freshness = objectValue(files["mdl/freshness.json"]);
  return {
    schema: models.schema ?? "agentkit.mdl.v1",
    model: models.model ?? {},
    entities: arrayValue(models.entities),
    metrics: arrayValue(metrics.metrics),
    dimensions: arrayValue(dimensions.dimensions),
    relationships: arrayValue(relationships.relationships),
    permissions: objectValue(permissions.permissions),
    freshness: objectValue(freshness.freshness),
    evidence: arrayValue((pkg as Record<string, unknown>).evidence),
  };
}

export function dashboardSpec(
  asset: KnowledgeAssetMetadata | undefined | null,
): Record<string, unknown> {
  const pkg = asset?.capability_package;
  if (!pkg || typeof pkg !== "object") return {};
  const direct = pkg.dashboard;
  if (direct && typeof direct === "object") return direct as Record<string, unknown>;
  const artifacts = pkg.artifacts;
  if (!artifacts || typeof artifacts !== "object") return {};
  return objectValue((artifacts as Record<string, unknown>)["dashboard_spec.json"]);
}

export function rowsFromSpec(spec: Record<string, unknown>): Array<Record<string, unknown>> {
  const views = arrayValue(spec.data_views);
  for (const view of views) {
    if (!view || typeof view !== "object") continue;
    const rows = (view as Record<string, unknown>).rows;
    if (Array.isArray(rows)) {
      return rows.filter(
        (row): row is Record<string, unknown> =>
          Boolean(row) && typeof row === "object" && !Array.isArray(row),
      );
    }
  }
  return [];
}

export function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function labelFrom(value: unknown, fallback = "未命名"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of ["name", "title", "id", "field", "table"]) {
      const candidate = record[key];
      if (typeof candidate === "string" && candidate.trim()) {
        return candidate.trim();
      }
    }
  }
  return fallback;
}
