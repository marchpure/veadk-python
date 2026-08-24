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

function replaceContents<T>(target: T[], next: T[]): void {
  target.splice(0, target.length, ...next);
}

export function hydrateWorkspaceData(data: WorkspaceBootstrapData): void {
  replaceContents(salesDatasetFields, data.datasetFields);
  replaceContents(workspaceKpis, data.dashboard.kpis);
  replaceContents(workspaceTrendData, data.dashboard.trendData);
  replaceContents(knowledgeGraphEntities, data.knowledgeGraph.entities);
  replaceContents(knowledgeGraphMappings, data.knowledgeGraph.mappings);
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
