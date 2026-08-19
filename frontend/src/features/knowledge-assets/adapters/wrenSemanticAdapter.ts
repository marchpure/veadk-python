/*
 * AgentKit adapter for the source-ported Wren modeling workspace.
 * It maps /api/knowledge-assets/* source, snapshot, Semantic Skill, MDL,
 * relationship, and metric records into props consumed by Wren source-port
 * components without importing Wren Apollo/router/runtime services.
 */
import type {
  KnowledgeAssetBuildJob,
  KnowledgeAssetMetadata,
  KnowledgeAssetSnapshot,
  KnowledgeAssetSource,
} from "../../../adk/knowledgeAssets";
import {
  arrayValue,
  labelFrom,
  mdlToModelingViewModel,
  objectValue,
  semanticMdl,
  type WrenModelingField,
  type WrenModelingMetric,
  type WrenModelingModel,
  type WrenModelingRelationship,
  type WrenModelingViewModel,
} from "../../../knowledge-center/knowledgeWorkbenchUtils";

export type WrenSourcePortTreeRow = {
  id: string;
  label: string;
  detail: string;
  kind: "source" | "snapshot" | "asset" | "model" | "view" | "field" | "relationship" | "metric";
  parentId?: string;
  model?: WrenModelingModel;
  field?: WrenModelingField;
  relationship?: WrenModelingRelationship;
  metric?: WrenModelingMetric;
};

export type WrenSourcePortNode = {
  id: string;
  label: string;
  type: "MODEL" | "VIEW";
  table: string;
  description: string;
  fields: WrenModelingField[];
  calculatedFields: WrenModelingField[];
  relationFields: WrenModelingField[];
  metrics: WrenModelingField[];
  dimensions: WrenModelingField[];
  raw: Record<string, unknown>;
};

export type WrenSourcePortEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  sourceFields: string[];
  targetFields: string[];
  raw: Record<string, unknown>;
};

export type WrenSourcePortViewModel = {
  mdl: Record<string, unknown>;
  modeling: WrenModelingViewModel;
  sources: KnowledgeAssetSource[];
  snapshots: KnowledgeAssetSnapshot[];
  semanticAssets: KnowledgeAssetMetadata[];
  selectedAsset: KnowledgeAssetMetadata | null;
  latestJob: KnowledgeAssetBuildJob | null;
  nodes: WrenSourcePortNode[];
  edges: WrenSourcePortEdge[];
  tree: {
    sources: WrenSourcePortTreeRow[];
    snapshots: WrenSourcePortTreeRow[];
    models: WrenSourcePortTreeRow[];
    views: WrenSourcePortTreeRow[];
    relationships: WrenSourcePortTreeRow[];
    metrics: WrenSourcePortTreeRow[];
  };
  status: {
    buildStatus: string;
    agentStatus: string;
    runnerBackend: string;
    generationMode: string;
    blockedReason: string;
  };
};

export function createWrenSemanticSourcePortViewModel(input: {
  sources: KnowledgeAssetSource[];
  snapshots: KnowledgeAssetSnapshot[];
  assets: KnowledgeAssetMetadata[];
  buildJobs: KnowledgeAssetBuildJob[];
  selectedAssetId: string;
  lastJob?: KnowledgeAssetBuildJob | null;
}): WrenSourcePortViewModel {
  const semanticAssets = input.assets.filter(
    (asset) => asset.asset_type === "semantic_model" && asset.capability_kind === "semantic_skill",
  );
  const selectedAsset =
    semanticAssets.find((asset) => asset.asset_id === input.selectedAssetId) ?? semanticAssets[0] ?? null;
  const mdl = semanticMdl(selectedAsset);
  const modeling = mdlToModelingViewModel(mdl);
  const latestJob =
    input.lastJob ??
    input.buildJobs.find((job) => job.job_type.includes("semantic") && job.asset_id === selectedAsset?.asset_id) ??
    input.buildJobs.find((job) => job.job_type.includes("semantic")) ??
    null;
  return {
    mdl,
    modeling,
    sources: input.sources.filter((source) =>
      ["database", "schema_snapshot"].includes(String(source.source_type).toLowerCase()),
    ),
    snapshots: input.snapshots,
    semanticAssets,
    selectedAsset,
    latestJob,
    nodes: [...modeling.models, ...modeling.views].map(modelToSourcePortNode),
    edges: modeling.relationships.map(relationshipToSourcePortEdge),
    tree: {
      sources: input.sources.map((source) => ({
        id: source.id,
        label: source.name,
        detail: source.source_type,
        kind: "source",
      })),
      snapshots: input.snapshots.map((snapshot) => ({
        id: snapshot.id,
        label: String(snapshot.metadata?.name || snapshot.id),
        detail: snapshot.kind || "snapshot",
        kind: "snapshot",
      })),
      models: wrenTreeRows(modeling.models, "model"),
      views: wrenTreeRows(modeling.views, "view"),
      relationships: modeling.relationships.map((relationship) => ({
        id: relationship.id,
        label: relationship.displayName,
        detail: `${relationship.fromModelId}.${relationship.fromField || "*"} -> ${relationship.toModelId}.${relationship.toField || "*"}`,
        kind: "relationship",
        relationship,
      })),
      metrics: modeling.metrics.map((metric) => ({
        id: metric.id,
        label: metric.displayName,
        detail: metric.modelId || "metric",
        kind: "metric",
        metric,
      })),
    },
    status: {
      buildStatus: latestJob ? latestJob.status : "idle",
      agentStatus: String(latestJob?.output?.agent_status || selectedAsset?.provenance?.agent_status || "unknown"),
      runnerBackend: String(latestJob?.output?.runner_backend || selectedAsset?.provenance?.runner_backend || "pending"),
      generationMode: String(latestJob?.output?.generation_mode || selectedAsset?.capabilities?.generation_mode || "unknown"),
      blockedReason: semanticBlockedReason(latestJob, selectedAsset),
    },
  };
}

export function wrenTreeRows(
  models: WrenModelingModel[],
  kind: "model" | "view",
): WrenSourcePortTreeRow[] {
  return models.flatMap((model) => [
    {
      id: model.id,
      label: model.displayName,
      detail: `${model.table} · ${model.fields.length} columns`,
      kind,
      model,
    },
    ...model.fields.slice(0, 12).map((field) => ({
      id: `${model.id}:${field.id}`,
      label: field.name,
      detail: field.type,
      kind: "field" as const,
      parentId: model.id,
      model,
      field,
    })),
    ...model.calculatedFields.slice(0, 6).map((field) => ({
      id: `${model.id}:calc:${field.id}`,
      label: field.name,
      detail: "calculated field",
      kind: "field" as const,
      parentId: model.id,
      model,
      field,
    })),
    ...model.relationFields.slice(0, 6).map((field) => ({
      id: `${model.id}:rel:${field.id}`,
      label: field.name,
      detail: field.type,
      kind: "field" as const,
      parentId: model.id,
      model,
      field,
    })),
  ]);
}

export function relationshipJoinFields(relationship: Record<string, unknown>): {
  source: string[];
  target: string[];
} {
  const joinFields = arrayValue(relationship.join_fields ?? relationship.joinFields);
  const source = new Set<string>();
  const target = new Set<string>();
  joinFields.forEach((item) => {
    const record = objectValue(item);
    const from = String(record.from ?? record.from_column ?? record.source_field ?? record.source ?? "");
    const to = String(record.to ?? record.to_column ?? record.target_field ?? record.target ?? "");
    if (from) source.add(from);
    if (to) target.add(to);
  });
  for (const key of ["from_column", "fromField", "source_column", "source_field"]) {
    const value = relationship[key];
    if (value) source.add(String(value));
  }
  for (const key of ["to_column", "toField", "target_column", "target_field"]) {
    const value = relationship[key];
    if (value) target.add(String(value));
  }
  return { source: [...source], target: [...target] };
}

export function semanticBlockedReason(
  latestJob: KnowledgeAssetBuildJob | null,
  selectedAsset: KnowledgeAssetMetadata | null,
): string {
  const errorMessage = latestJob?.error?.message;
  if (typeof errorMessage === "string" && errorMessage.trim()) return errorMessage;
  const jobBlockers = latestJob?.output?.blocked_reasons;
  if (Array.isArray(jobBlockers) && jobBlockers.length) return jobBlockers.map(String).join(", ");
  const blockers = selectedAsset?.gate?.blockers;
  if (Array.isArray(blockers) && blockers.length) return blockers.join(", ");
  return "none";
}

function modelToSourcePortNode(model: WrenModelingModel): WrenSourcePortNode {
  return {
    id: model.id,
    label: model.displayName,
    type: model.nodeType,
    table: model.table,
    description: model.description,
    fields: model.fields,
    calculatedFields: model.calculatedFields,
    relationFields: model.relationFields,
    metrics: model.metrics,
    dimensions: model.dimensions,
    raw: model.raw,
  };
}

function relationshipToSourcePortEdge(relationship: WrenModelingRelationship): WrenSourcePortEdge {
  const joins = relationshipJoinFields(relationship.raw);
  return {
    id: relationship.id,
    source: relationship.fromModelId,
    target: relationship.toModelId,
    label: relationship.displayName || relationship.type,
    sourceFields: relationship.fromField ? [relationship.fromField, ...joins.source] : joins.source,
    targetFields: relationship.toField ? [relationship.toField, ...joins.target] : joins.target,
    raw: relationship.raw,
  };
}

export function sourcePortLabel(value: unknown, fallback = "Untitled"): string {
  return labelFrom(value, fallback);
}
