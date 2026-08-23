import { Store } from './store';

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
  severity: 'low' | 'medium' | 'high' | 'critical';
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
  status: 'open' | 'in_progress' | 'pending_review' | 'completed';
  resolution?: string;
  evidence?: string;
  createdBy: 'human' | 'agent';
  createdAt: string;
}

export interface Review {
  id: string;
  todoId: string;
  reviewer: string;
  outcome: '有效' | '部分有效' | '无效';
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
  status: 'draft' | 'approved';
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
  signals: [
    {
      id: 'sig_vn_hc_anomaly',
      dashboardId: 'res_dash_recruitment',
      elementId: 'card_vn_anomaly',
      metric: '招聘需求',
      dimensions: { country: '越南', role: '销售岗位' },
      observedValue: '+38%',
      expectedRange: '-5% ~ +5%',
      detectedAt: new Date().toISOString(),
      evidenceSnapshot: '缺口 26，预计影响 Q4 市场拓展',
      title: '越南 · 销售岗位需求激增',
      description: '越南销售岗位需求本周突增 38%，当前缺口 26 人，可能严重影响 Q4 东南亚市场拓展计划。',
      severity: 'high'
    },
    {
      id: 'sig_vix_anomaly',
      dashboardId: 'res_dash_finance',
      elementId: 'card_vix_anomaly',
      metric: 'VIX 恐慌指数',
      dimensions: { market: 'Global' },
      observedValue: '+15.2%',
      expectedRange: '< +10%',
      detectedAt: new Date().toISOString(),
      evidenceSnapshot: '指数突增 15.2%',
      title: 'VIX 恐慌指数异常飙升',
      description: 'VIX 恐慌指数单日涨幅超过 15%，市场波动风险极高。',
      severity: 'critical'
    }
  ],
  policies: [
    {
      id: 'pol_recruitment',
      metric: '招聘需求',
      dimensionScope: '国家=越南；岗位=销售',
      threshold: '周环比 > 30%',
      severity: 'high',
      agentStrategy: '核验 HC 来源与优先级、检查渠道转化、调配招聘资源、确认当地薪酬/审批瓶颈。',
      autoCreateTodo: false,
      defaultOwner: 'Linh Nguyen',
      slaHours: 24,
      reviewer: '张总监 (VP of HR)'
    },
    {
      id: 'pol_finance',
      metric: 'VIX 恐慌指数',
      dimensionScope: '市场=Global',
      threshold: '单日涨幅 > 10%',
      severity: 'critical',
      agentStrategy: '提取昨日量化策略收益率，评估风险暴露，调低高风险资产仓位。',
      autoCreateTodo: true,
      defaultOwner: '量化分析组',
      slaHours: 2,
      reviewer: 'Risk Manager'
    }
  ],
  todos: [],
  reviews: [],
  briefs: []
};

export const actionLoopStore = new Store<ActionLoopState>('v2113_action_loop', defaultActionLoopState);