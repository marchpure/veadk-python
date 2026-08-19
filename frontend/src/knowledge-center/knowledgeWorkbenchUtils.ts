import type { AskDataQueryResult, KnowledgeAssetMetadata } from "../adk/knowledgeAssets";

export type WrenModelingField = {
  id: string;
  name: string;
  type: string;
  nodeType: "column" | "calculatedField" | "relationship" | "metric";
  isPrimaryKey: boolean;
  raw: Record<string, unknown>;
};

export type WrenModelingModel = {
  id: string;
  modelId: string;
  referenceName: string;
  displayName: string;
  nodeType: "MODEL" | "VIEW";
  table: string;
  description: string;
  fields: WrenModelingField[];
  calculatedFields: WrenModelingField[];
  relationFields: WrenModelingField[];
  metrics: WrenModelingField[];
  dimensions: WrenModelingField[];
  raw: Record<string, unknown>;
};

export type WrenModelingRelationship = {
  id: string;
  displayName: string;
  fromModelId: string;
  toModelId: string;
  fromField: string;
  toField: string;
  type: string;
  raw: Record<string, unknown>;
};

export type WrenModelingMetric = {
  id: string;
  displayName: string;
  modelId: string;
  expression: string;
  definition: string;
  raw: Record<string, unknown>;
};

export type WrenModelingViewModel = {
  models: WrenModelingModel[];
  views: WrenModelingModel[];
  relationships: WrenModelingRelationship[];
  metrics: WrenModelingMetric[];
  permissions: Record<string, unknown>;
  evidence: unknown[];
};

export type ByaanNotebookViewModel = {
  editorQuery: string;
  status: "idle" | "running" | "success" | "blocked" | "error";
  rowCount: number;
  returnedCount: number;
  executionTime: string;
  sql: string;
  metricDefinition: unknown;
  policyDecision: Record<string, unknown>;
  freshness: Record<string, unknown>;
  evidence: unknown[];
  lineage: unknown[];
  execution: Record<string, unknown>;
  rows: Array<Record<string, unknown>>;
};

export type ByaanDashboardViewModel = {
  title: string;
  description: string;
  filters: Array<Record<string, unknown>>;
  tiles: Array<Record<string, unknown>>;
  dataViews: Array<Record<string, unknown>>;
  queries: Array<Record<string, unknown>>;
};

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

export function mdlToModelingViewModel(mdl: Record<string, unknown>): WrenModelingViewModel {
  const entities = arrayValue(mdl.entities).filter(isRecord);
  const metrics = arrayValue(mdl.metrics).filter(isRecord);
  const dimensions = arrayValue(mdl.dimensions).filter(isRecord);
  const relationships = arrayValue(mdl.relationships).filter(isRecord);
  const modelRows = entities.map((entity, index) =>
    entityToWrenModel(entity, metrics, dimensions, relationships, index),
  );
  return {
    models: modelRows.filter((model) => model.nodeType === "MODEL"),
    views: modelRows.filter((model) => model.nodeType === "VIEW"),
    relationships: relationships.map((relationship, index) => relationshipToWren(relationship, index, modelRows)),
    metrics: metrics.map((metric, index) => metricToWren(metric, index)),
    permissions: objectValue(mdl.permissions),
    evidence: arrayValue(mdl.evidence),
  };
}

export function askDataToNotebookViewModel(
  result: AskDataQueryResult | null,
  fallbackQuestion: string,
  isRunning = false,
): ByaanNotebookViewModel {
  if (!result) {
    return {
      editorQuery: fallbackQuestion,
      status: isRunning ? "running" : "idle",
      rowCount: 0,
      returnedCount: 0,
      executionTime: "n/a",
      sql: "",
      metricDefinition: {},
      policyDecision: {},
      freshness: {},
      evidence: [],
      lineage: [],
      execution: {},
      rows: [],
    };
  }
  const execution = objectValue((result.data as unknown as Record<string, unknown>).execution);
  const status =
    result.status === "blocked"
      ? "blocked"
      : result.status === "completed"
        ? "success"
        : result.status === "error" || result.status === "failed"
          ? "error"
          : isRunning
            ? "running"
            : "idle";
  return {
    editorQuery: result.data.sql || fallbackQuestion,
    status,
    rowCount: result.data.rows.length,
    returnedCount: Number(result.data.returnedCount ?? result.data.rows.length),
    executionTime: String(execution.elapsed_ms ?? execution.elapsedMs ?? "n/a"),
    sql: result.data.sql || "",
    metricDefinition: result.data.metricDefinition ?? result.data.metric ?? {},
    policyDecision: objectValue(result.data.policyDecision),
    freshness: objectValue(result.data.freshness),
    evidence: arrayValue(result.data.evidence),
    lineage: arrayValue(result.data.lineage),
    execution,
    rows: result.data.rows,
  };
}

export function dashboardSpecToByaanViewModel(
  spec: Record<string, unknown>,
  fallbackAsset?: KnowledgeAssetMetadata | null,
): ByaanDashboardViewModel {
  const dataViews = arrayValue(spec.data_views).filter(isRecord);
  return {
    title: String(spec.title || fallbackAsset?.name || "Dashboard"),
    description: String(spec.description || fallbackAsset?.description || "Governed dashboard workspace"),
    filters: arrayValue(spec.filters).filter(isRecord),
    tiles: arrayValue(spec.tiles).filter(isRecord),
    dataViews,
    queries: dataViews.map((view, index) => ({
      id: String(view.id || `query_${index + 1}`),
      title: String(view.title || view.name || view.id || `Query ${index + 1}`),
      sql: String(view.sql || ""),
      metricDefinition: view.metricDefinition ?? view.metric_definition ?? view.metric ?? {},
      policyDecision: objectValue(view.policyDecision ?? view.policy_decision),
      freshness: objectValue(view.freshness),
      evidence: arrayValue(view.evidence),
      lineage: arrayValue(view.lineage),
    })),
  };
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

function entityToWrenModel(
  entity: Record<string, unknown>,
  metrics: Record<string, unknown>[],
  dimensions: Record<string, unknown>[],
  relationships: Record<string, unknown>[],
  index: number,
): WrenModelingModel {
  const id = String(entity.id || entity.table || entity.name || `model_${index + 1}`);
  const table = String(entity.table || entity.name || id);
  const kind = String(entity.kind || entity.type || "").toLowerCase();
  const entityFields = arrayValue(entity.fields).filter(isRecord);
  const entityMetrics = metrics.filter((metric) => belongsToEntity(metric, id));
  const entityDimensions = dimensions.filter((dimension) => belongsToEntity(dimension, id));
  const relationFields = relationships
    .filter((relationship) => relationshipTouchesEntity(relationship, id, table))
    .map((relationship, relIndex) => relationshipFieldToWren(relationship, relIndex, id));
  return {
    id,
    modelId: id,
    referenceName: table,
    displayName: labelFrom(entity, table),
    nodeType: kind.includes("view") ? "VIEW" : "MODEL",
    table,
    description: String(entity.description || ""),
    fields: entityFields.map((field, fieldIndex) => fieldToWren(field, fieldIndex)),
    calculatedFields: entityMetrics.map((metric, metricIndex) => metricFieldToWren(metric, metricIndex)),
    relationFields,
    metrics: entityMetrics.map((metric, metricIndex) => metricFieldToWren(metric, metricIndex)),
    dimensions: entityDimensions.map((dimension, dimensionIndex) => dimensionFieldToWren(dimension, dimensionIndex)),
    raw: entity,
  };
}

function fieldToWren(field: Record<string, unknown>, index: number): WrenModelingField {
  const name = labelFrom(field, `field_${index + 1}`);
  return {
    id: String(field.id || field.name || field.field || name),
    name,
    type: String(field.type ?? field.data_type ?? "field"),
    nodeType: "column",
    isPrimaryKey: Boolean(field.primary_key || field.isPrimaryKey),
    raw: field,
  };
}

function metricFieldToWren(metric: Record<string, unknown>, index: number): WrenModelingField {
  const name = labelFrom(metric, `metric_${index + 1}`);
  return {
    id: String(metric.id || metric.name || name),
    name,
    type: String(metric.type || metric.aggregation || "metric"),
    nodeType: "calculatedField",
    isPrimaryKey: false,
    raw: metric,
  };
}

function dimensionFieldToWren(dimension: Record<string, unknown>, index: number): WrenModelingField {
  const name = labelFrom(dimension, `dimension_${index + 1}`);
  return {
    id: String(dimension.id || dimension.name || dimension.field || name),
    name,
    type: String(dimension.type || dimension.data_type || "dimension"),
    nodeType: "column",
    isPrimaryKey: false,
    raw: dimension,
  };
}

function relationshipFieldToWren(
  relationship: Record<string, unknown>,
  index: number,
  currentEntityId: string,
): WrenModelingField {
  const converted = relationshipToWren(relationship, index, []);
  const opposite =
    converted.fromModelId === currentEntityId
      ? `${converted.toModelId}.${converted.toField}`
      : `${converted.fromModelId}.${converted.fromField}`;
  return {
    id: converted.id,
    name: opposite,
    type: converted.type,
    nodeType: "relationship",
    isPrimaryKey: false,
    raw: relationship,
  };
}

function relationshipToWren(
  relationship: Record<string, unknown>,
  index: number,
  models: WrenModelingModel[],
): WrenModelingRelationship {
  const source = String(relationship.from_entity || relationship.from || relationship.from_table || relationship.source || models[0]?.id || "");
  const target = String(relationship.to_entity || relationship.to || relationship.to_table || relationship.target || models[1]?.id || "");
  const highlights = relationshipFieldPair(relationship);
  return {
    id: String(relationship.id || `relationship_${index + 1}`),
    displayName: String(relationship.label || relationship.kind || `${source} -> ${target}`),
    fromModelId: source,
    toModelId: target,
    fromField: highlights.from,
    toField: highlights.to,
    type: String(relationship.type || relationship.kind || "many_to_one"),
    raw: relationship,
  };
}

function metricToWren(metric: Record<string, unknown>, index: number): WrenModelingMetric {
  return {
    id: String(metric.id || metric.name || `metric_${index + 1}`),
    displayName: labelFrom(metric, `metric_${index + 1}`),
    modelId: String(metric.entity || metric.entityId || metric.model || ""),
    expression: String(metric.expression || metric.sql || metric.formula || ""),
    definition: String(metric.definition || metric.description || metric.label || ""),
    raw: metric,
  };
}

function relationshipFieldPair(relationship: Record<string, unknown>): { from: string; to: string } {
  const joinFields = arrayValue(relationship.join_fields ?? relationship.joinFields);
  const firstJoin = objectValue(joinFields[0]);
  return {
    from: String(
      firstJoin.from ??
        firstJoin.from_column ??
        firstJoin.source_field ??
        relationship.from_column ??
        relationship.source_field ??
        "",
    ),
    to: String(
      firstJoin.to ??
        firstJoin.to_column ??
        firstJoin.target_field ??
        relationship.to_column ??
        relationship.target_field ??
        "",
    ),
  };
}

function belongsToEntity(record: Record<string, unknown>, entityId: string): boolean {
  return String(record.entity || record.entityId || record.model || record.modelId || "") === entityId;
}

function relationshipTouchesEntity(
  relationship: Record<string, unknown>,
  entityId: string,
  table: string,
): boolean {
  const candidates = [
    relationship.from_entity,
    relationship.from,
    relationship.from_table,
    relationship.source,
    relationship.to_entity,
    relationship.to,
    relationship.to_table,
    relationship.target,
  ].map(String);
  return candidates.includes(entityId) || candidates.includes(table);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
