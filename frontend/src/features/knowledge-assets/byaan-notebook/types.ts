import type { Block } from "../../../blocks";

export interface ByaanSemanticModelOption {
  id: string;
  name: string;
  publishedVersion?: string | null;
  metrics: string[];
  dimensions: string[];
}

export interface ByaanDashboardOption {
  id: string;
  name: string;
  version?: string | null;
}

export interface ByaanNotebookMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: "running" | "completed" | "blocked" | "error";
  blocks?: Block[];
  error?: string;
}

export interface ByaanSemanticQueryResultEvent {
  type: "semantic_query_result";
  result: {
    resolvedMetric: string;
    sql: string;
    metricDefinition: string;
    policyDecision: string;
    policyDecisionRaw: Record<string, unknown>;
    freshness: Record<string, unknown>;
    dataThrough?: string;
    lineage: unknown[];
    evidence: Array<Record<string, unknown>>;
    rows: Array<Record<string, unknown>>;
    returnedCount: number;
    modelVersion?: string;
    snapshotId?: string;
    execution?: Record<string, unknown>;
  };
}

export interface ByaanDashboardPreviewModel {
  processedHtmlContent: string;
  generatedCode: string;
  title: string;
  versionInfo: string;
  queryResult: ByaanSemanticQueryResultEvent | null;
  isGenerating: boolean;
}
