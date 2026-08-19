import type {
  AskDataQueryResult,
  DashboardSkillBuildResult,
  KnowledgeAssetMetadata,
} from "../../../../../adk/knowledgeAssets";
import type {
  ByaanDashboardViewModel,
  ByaanNotebookViewModel,
} from "../../../../../knowledge-center/knowledgeWorkbenchUtils";

export type QueryListItem = {
  id: string;
  name: string;
  query_type: string;
  skill_name: string | null;
};

export type QueryResult = {
  query: string;
  results: Array<Record<string, unknown>>;
  executionTime: string;
  rowCount: number;
  totalCount?: number;
  returnedCount?: number;
  limited?: boolean;
  error?: string;
  rawResult?: string;
  metricDefinition?: unknown;
  policyDecision?: Record<string, unknown>;
  freshness?: Record<string, unknown>;
  evidence?: unknown[];
  lineage?: unknown[];
};

export type DashboardWorkspaceTab = "dashboard" | "data" | "lineage" | "code";

export type ByaanOriginalWorkspaceModel = {
  notebook: ByaanNotebookViewModel;
  dashboard: ByaanDashboardViewModel;
  dashboardSpec: Record<string, unknown>;
  previewRows: Array<Record<string, unknown>>;
  queryResult: AskDataQueryResult | null;
  buildResult: DashboardSkillBuildResult | null;
  selectedSkill: KnowledgeAssetMetadata | null;
  selectedDashboard: KnowledgeAssetMetadata | null;
};
