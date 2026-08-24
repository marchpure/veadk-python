import type {
  WorkspaceBootstrapData,
  WorkspaceDatasetField,
  WorkspaceKpi,
  WorkspaceKnowledgeGraphEntity,
  WorkspaceKnowledgeGraphMapping,
  WorkspaceTrendPoint,
} from "./bootstrapSchema";

export const salesDatasetFields: WorkspaceDatasetField[] = [];
export const mockKpis: WorkspaceKpi[] = [];
export const mockTrendData: WorkspaceTrendPoint[] = [];
export const knowledgeGraphEntities: WorkspaceKnowledgeGraphEntity[] = [];
export const knowledgeGraphMappings: WorkspaceKnowledgeGraphMapping[] = [];

function replaceContents<T>(target: T[], next: T[]): void {
  target.splice(0, target.length, ...next);
}

export function hydrateWorkspaceData(data: WorkspaceBootstrapData): void {
  replaceContents(salesDatasetFields, data.datasetFields);
  replaceContents(mockKpis, data.dashboard.kpis);
  replaceContents(mockTrendData, data.dashboard.trendData);
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
