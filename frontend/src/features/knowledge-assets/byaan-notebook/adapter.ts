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
  const previewSpec = objectValue(preview);
  const artifactSpec = objectValue(artifacts["dashboard_spec.json"]);
  const spec = Object.keys(previewSpec).length ? previewSpec : artifactSpec;
  const renderedSpec = html ? "" : renderDashboardSpecHtml(spec, selectedDashboard?.name || buildResult?.dashboard?.name || "Dashboard Preview");
  const generatedCode = firstString(
    preview.generatedCode,
    html,
    renderedSpec,
    artifacts["SKILL.md"],
    Object.keys(spec).length ? formatJson(spec) : "",
  );
  return {
    processedHtmlContent: html || renderedSpec,
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

function renderDashboardSpecHtml(spec: Record<string, unknown>, fallbackTitle: string): string {
  const dataViews = Array.isArray(spec.data_views) ? spec.data_views.filter(isRecord) : [];
  const tiles = Array.isArray(spec.tiles) ? spec.tiles.filter(isRecord) : [];
  const primary = dataViews[0] ?? {};
  const rows = Array.isArray(primary.rows) ? primary.rows.filter(isRecord) : [];
  if (!dataViews.length && !tiles.length && !rows.length) return "";
  const metric = String(primary.metric || "Semantic metric");
  const title = String(spec.title || fallbackTitle);
  const returnedCount = Number(primary.returnedCount ?? rows.length);
  const policy = objectValue(primary.policyDecision);
  const freshness = objectValue(primary.freshness);
  const sql = String(primary.sql || "");
  const columns = rows.length ? Object.keys(rows[0]).slice(0, 8) : [];
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(title)}</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #18181b; }
    main { display: grid; gap: 16px; min-height: 100vh; box-sizing: border-box; padding: 24px; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid #e4e4e7; padding-bottom: 14px; }
    h1 { margin: 0; font-size: 22px; line-height: 1.2; }
    .meta { color: #707078; font-size: 12px; line-height: 1.5; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
    .card, table, pre { border: 1px solid #e4e4e7; border-radius: 8px; background: #fff; box-shadow: 0 1px 2px rgb(0 0 0 / 0.04); }
    .card { padding: 14px; }
    .label { color: #707078; font-size: 12px; }
    .value { margin-top: 6px; font-size: 24px; font-weight: 650; }
    table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; font-size: 13px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #f0f0f1; text-align: left; }
    th { background: #f8f9fb; color: #4f5159; font-size: 12px; font-weight: 600; }
    tr:last-child td { border-bottom: 0; }
    pre { margin: 0; padding: 12px; overflow: auto; color: #4f5159; font-size: 12px; line-height: 1.55; white-space: pre-wrap; }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>${escapeHtml(title)}</h1>
        <div class="meta">${escapeHtml(metric)} · ${returnedCount} governed rows</div>
      </div>
      <div class="meta">Policy: ${escapeHtml(String(policy.decision || "checked"))}<br />Freshness: ${escapeHtml(String(freshness.status || freshness.as_of || "reported"))}</div>
    </header>
    <section class="grid">
      <div class="card"><div class="label">Metric</div><div class="value">${escapeHtml(metric)}</div></div>
      <div class="card"><div class="label">Rows</div><div class="value">${returnedCount}</div></div>
      <div class="card"><div class="label">Policy</div><div class="value">${escapeHtml(String(policy.decision || "allow"))}</div></div>
    </section>
    ${columns.length ? `<table><thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(String(row[column] ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody></table>` : ""}
    ${sql ? `<pre>${escapeHtml(sql)}</pre>` : ""}
  </main>
</body>
</html>`;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char] || char));
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
