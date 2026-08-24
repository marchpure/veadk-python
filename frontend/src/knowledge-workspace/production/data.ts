import type {
  WorkspaceBootstrapData,
  WorkspaceDatasetField,
  WorkspaceKpi,
  WorkspaceKnowledgeGraphEntity,
  WorkspaceKnowledgeGraphMapping,
  WorkspaceTrendPoint,
} from "./bootstrapSchema";

export const salesDatasetFields: WorkspaceDatasetField[] = [];
export const workspaceKpis: WorkspaceKpi[] = [];
export const workspaceTrendData: WorkspaceTrendPoint[] = [];
// Compatibility aliases for frozen-ui imports; both arrays are hydrated only
// from the validated production bootstrap response above.
export const mockKpis = workspaceKpis;
export const mockTrendData = workspaceTrendData;
export const knowledgeGraphEntities: WorkspaceKnowledgeGraphEntity[] = [];
export const knowledgeGraphMappings: WorkspaceKnowledgeGraphMapping[] = [];
export let activeSkillViewRevision: Record<string, unknown> | null = null;

function replaceContents<T>(target: T[], next: T[]): void {
  target.splice(0, target.length, ...next);
}

export function hydrateWorkspaceData(data: WorkspaceBootstrapData): void {
  replaceContents(salesDatasetFields, data.datasetFields);
  replaceContents(workspaceKpis, data.dashboard.kpis);
  replaceContents(workspaceTrendData, data.dashboard.trendData);
  replaceContents(knowledgeGraphEntities, data.knowledgeGraph.entities);
  replaceContents(knowledgeGraphMappings, data.knowledgeGraph.mappings);
  activeSkillViewRevision = data.skillViewRevision ?? null;
  const viewModel =
    activeSkillViewRevision?.viewModel &&
    typeof activeSkillViewRevision.viewModel === "object"
      ? activeSkillViewRevision.viewModel as Record<string, unknown>
      : null;
  if (viewModel?.template === "chart") {
    const series = Array.isArray(viewModel.series) ? viewModel.series[0] : null;
    const points = series && typeof series === "object" && Array.isArray((series as Record<string, unknown>).points)
      ? (series as Record<string, unknown>).points
      : [];
    const numericPoints = points.filter(
      (point): point is [string, number] =>
        Array.isArray(point) && typeof point[0] === "string" &&
        typeof point[1] === "number" && Number.isFinite(point[1]),
    );
    if (numericPoints.length > 0) {
      const total = numericPoints.reduce((sum, [, value]) => sum + value, 0);
      const highest = Math.max(...numericPoints.map(([, value]) => value));
      replaceContents(workspaceKpis, [
        { label: "总计", value: String(total), trend: "unknown", isUp: true },
        { label: "最高维度", value: String(highest), trend: "unknown", isUp: true },
        { label: "数据点", value: String(numericPoints.length), trend: "unknown", isUp: true },
      ]);
      replaceContents(workspaceTrendData, numericPoints.map(([name, value]) => ({
        name,
        sales: value,
        profit: 0,
      })));
    }
  }
}

export function getKnowledgeGraphData(): {
  entities: WorkspaceKnowledgeGraphEntity[];
  mappings: WorkspaceKnowledgeGraphMapping[];
} {
  return {
    entities: knowledgeGraphEntities,
    mappings: knowledgeGraphMappings,
  };
}
