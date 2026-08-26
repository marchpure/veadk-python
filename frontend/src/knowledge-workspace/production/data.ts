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
export let workspaceRecommendedPrompts: Array<{ id: string; label: string; prompt: string }> = [];
export let workspaceChartConfig: {
  title: string;
  xField: string;
  yField: string;
  series: Array<{ name: string; dataKey: string; color: string }>;
  data: Array<Record<string, string | number>>;
} | null = null;

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
  workspaceRecommendedPrompts = Array.isArray(data.recommendedPrompts)
    ? data.recommendedPrompts.filter((item) =>
      Boolean(item) &&
      typeof item.id === "string" &&
      typeof item.label === "string" &&
      typeof item.prompt === "string",
    )
    : [];
  workspaceChartConfig = null;
  const viewModel =
    activeSkillViewRevision?.viewModel &&
    typeof activeSkillViewRevision.viewModel === "object"
      ? activeSkillViewRevision.viewModel as Record<string, unknown>
      : null;
  if (viewModel?.template === "chart") {
    const seriesList = Array.isArray(viewModel.series)
      ? viewModel.series.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
      : [];
    const firstSeries = seriesList[0];
    const points = firstSeries && Array.isArray(firstSeries.points) ? firstSeries.points : [];
    const numericPoints = points.filter((point): point is [string, number] =>
      Array.isArray(point) && typeof point[0] === "string" &&
      typeof point[1] === "number" && Number.isFinite(point[1]),
    );
    if (numericPoints.length > 0) {
      const xField = typeof viewModel.xField === "string" ? viewModel.xField : "dimension";
      const yField = typeof viewModel.yField === "string" ? viewModel.yField : "value";
      const chartSeries = seriesList.map((series, index) => ({
        name: typeof series.name === "string" ? series.name : `series-${index + 1}`,
        dataKey: `series_${index}`,
        color: index === 0 ? "#3b82f6" : "#10b981",
      }));
      const chartData = numericPoints.map(([label, value], pointIndex) => {
        const row: Record<string, string | number> = { [xField]: label };
        seriesList.forEach((series, seriesIndex) => {
          const seriesPoints = Array.isArray(series.points) ? series.points : [];
          const candidate = seriesPoints[pointIndex];
          row[`series_${seriesIndex}`] =
            Array.isArray(candidate) && typeof candidate[1] === "number" ? candidate[1] : 0;
        });
        return row;
      });
      workspaceChartConfig = {
        title: typeof viewModel.title === "string" ? viewModel.title : "Generated chart",
        xField,
        yField,
        series: chartSeries,
        data: chartData,
      };
      const total = numericPoints.reduce((sum, [, value]) => sum + value, 0);
      const highest = Math.max(...numericPoints.map(([, value]) => value));
      replaceContents(workspaceKpis, [
        { label: `${yField} total`, value: String(total), trend: "unknown", isUp: true },
        { label: `${yField} max`, value: String(highest), trend: "unknown", isUp: true },
        { label: `${xField} count`, value: String(numericPoints.length), trend: "unknown", isUp: true },
      ]);
      replaceContents(workspaceTrendData, numericPoints.map(([name, value]) => ({
        name,
        sales: value,
        profit: 0,
      })));
    }
  }
}

export function setActiveSkillViewRevision(
  revision: Record<string, unknown> | null,
): void {
  activeSkillViewRevision = revision;
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
