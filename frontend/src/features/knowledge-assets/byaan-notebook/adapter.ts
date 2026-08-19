import type {
  AskDataQueryResult,
  DashboardSkillBuildResult,
  KnowledgeAssetMetadata,
} from "../../../adk/knowledgeAssets";
import { formatJson, objectValue } from "../../../knowledge-center/knowledgeWorkbenchUtils";
import type {
  ByaanDashboardOption,
  ByaanDashboardPreviewModel,
  ByaanNotebookMessage,
  ByaanSemanticModelOption,
  ByaanSemanticQueryResultEvent,
} from "./types";
import type { Block } from "../../../blocks";

export function semanticAssetToByaanModel(asset: KnowledgeAssetMetadata): ByaanSemanticModelOption {
  return {
    id: asset.asset_id,
    name: asset.name,
    publishedVersion: asset.version || "v1",
    metrics: stringArray(asset.capabilities?.metrics),
    dimensions: stringArray(asset.capabilities?.dimensions),
  };
}

export function dashboardAssetToByaanOption(asset: KnowledgeAssetMetadata): ByaanDashboardOption {
  return {
    id: asset.asset_id,
    name: asset.name,
    version: asset.version || "v1",
  };
}

export function askDataToSemanticQueryResultEvent(result: AskDataQueryResult | null): ByaanSemanticQueryResultEvent | null {
  if (!result) return null;
  const policy = objectValue(result.data.policyDecision);
  const freshness = objectValue(result.data.freshness);
  const metric = objectValue(result.data.metric);
  const metricDefinition = result.data.metricDefinition;
  return {
    type: "semantic_query_result",
    result: {
      resolvedMetric: String(metric.name || metric.id || "Semantic metric"),
      sql: result.data.sql || "",
      metricDefinition: typeof metricDefinition === "string" ? metricDefinition : formatJson(metricDefinition),
      policyDecision: String(policy.decision || policy.policyDecision || result.status),
      policyDecisionRaw: policy,
      freshness,
      dataThrough: typeof freshness.as_of === "string" ? freshness.as_of : undefined,
      lineage: result.data.lineage ?? [],
      evidence: result.data.evidence ?? [],
      rows: result.data.rows ?? [],
      returnedCount: Number(result.data.returnedCount ?? result.data.rows?.length ?? 0),
      modelVersion: result.asset.version,
      snapshotId: lineageLabel(result.data.lineage?.[0]),
      execution: result.data.execution,
    },
  };
}

export function roundsToByaanMessages(rounds: Array<{
  id: string;
  question: string;
  status: "running" | "completed" | "blocked" | "error";
  blocks: Block[];
  error?: string;
}>): ByaanNotebookMessage[] {
  return rounds.flatMap((round) => [
    {
      id: `${round.id}-user`,
      role: "user" as const,
      content: round.question,
    },
    {
      id: `${round.id}-assistant`,
      role: "assistant" as const,
      content: finalText(round.blocks),
      status: round.status,
      blocks: round.blocks,
      error: round.error,
    },
  ]);
}

export function dashboardPreviewFromAgentKit({
  selectedDashboard,
  buildResult,
  queryResult,
  busyBuild,
}: {
  selectedDashboard: KnowledgeAssetMetadata | null;
  buildResult: DashboardSkillBuildResult | null;
  queryResult: AskDataQueryResult | null;
  busyBuild: boolean;
}): ByaanDashboardPreviewModel {
  const preview = objectValue(buildResult?.preview);
  const dashboardPackage = objectValue(selectedDashboard?.capability_package);
  const artifacts = objectValue(dashboardPackage.artifacts);
  const html = firstString(
    preview.processedHtmlContent,
    preview.html,
    artifacts["index.html"],
    artifacts["dashboard.html"],
  );
  const spec = objectValue(artifacts["dashboard_spec.json"]) || {};
  const generatedCode = firstString(
    preview.generatedCode,
    html,
    artifacts["SKILL.md"],
    Object.keys(spec).length ? formatJson(spec) : "",
  );
  return {
    processedHtmlContent: html,
    generatedCode,
    title: selectedDashboard?.name || buildResult?.dashboard?.name || "Dashboard Preview",
    versionInfo: selectedDashboard?.version ? `v${selectedDashboard.version}` : "v1",
    queryResult: askDataToSemanticQueryResultEvent(queryResult),
    isGenerating: busyBuild,
  };
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

function finalText(blocks: Block[]): string {
  const text = blocks
    .filter((block): block is Extract<Block, { kind: "text" }> => block.kind === "text")
    .map((block) => block.text)
    .join("");
  return text.trim();
}

function lineageLabel(item: unknown): string | undefined {
  if (!item) return undefined;
  if (typeof item === "string") return item;
  if (typeof item !== "object") return undefined;
  const record = item as Record<string, unknown>;
  const value = record.name || record.title || record.table || record.ref || record.id;
  return typeof value === "string" ? value : undefined;
}
