import { WorkspaceStore } from "./store";

export interface Signal {
  id: string;
  dashboardId: string;
  elementId: string;
  metric: string;
  dimensions: Record<string, string>;
  observedValue: string;
  expectedRange: string;
  detectedAt: string;
  evidenceSnapshot: string;
  title: string;
  description: string;
  severity: "low" | "medium" | "high" | "critical";
}

export interface ActionPolicy {
  id: string;
  metric: string;
  dimensionScope: string;
  threshold: string;
  severity: string;
  agentStrategy: string;
  autoCreateTodo: boolean;
  defaultOwner: string;
  slaHours: number;
  reviewer: string;
}

export interface Todo {
  id: string;
  signalId: string;
  title: string;
  recommendedActions: string[];
  owner: string;
  dueAt: string;
  status: "open" | "in_progress" | "pending_review" | "completed";
  resolution?: string;
  evidence?: string;
  createdBy: "human" | "agent";
  createdAt: string;
}

export interface Review {
  id: string;
  todoId: string;
  reviewer: string;
  outcome: "有效" | "部分有效" | "无效";
  beforeMetric?: string;
  afterMetric?: string;
  comment: string;
  evidence?: string;
  reviewedAt: string;
}

export interface DecisionBrief {
  id: string;
  dashboardId: string;
  period: string;
  scope: string;
  basedOnTodos: string[];
  facts: string[];
  agentSuggestions: string[];
  alternatives: string[];
  impactRisk: string;
  confidence: string;
  decisionMaker: string;
  status: "draft" | "approved";
  createdAt: string;
}

export interface ActionLoopState {
  signals: Signal[];
  policies: ActionPolicy[];
  todos: Todo[];
  reviews: Review[];
  briefs: DecisionBrief[];
}

export const defaultActionLoopState: ActionLoopState = {
  signals: [],
  policies: [],
  todos: [],
  reviews: [],
  briefs: [],
};

export const actionLoopStore = new WorkspaceStore<ActionLoopState>(
  "action-loop",
  defaultActionLoopState,
);
