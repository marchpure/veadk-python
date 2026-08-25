export interface WorkspaceConnectorDefinition {
  connectorKey: string;
  category: string;
  name: string;
  desc: string;
  capabilities: string[];
  inputSchema: Record<string, string>;
  credentialSchema: Record<string, string> | null;
  discoveryPipeline: string[];
  syncModes: string[];
}

export interface WorkspaceMcpProfile {
  profileId: string;
  label: string;
  transport: string;
  toolAllowlist: string[];
}

export interface WorkspaceDatasetField {
  name: string;
  type: string;
  desc: string;
}

export interface WorkspaceKpi {
  label: string;
  value: string;
  trend: string;
  isUp: boolean;
}

export interface WorkspaceTrendPoint {
  name: string;
  sales: number;
  profit: number;
}

export interface WorkspaceKnowledgeGraphEntity {
  id: string;
  name: string;
  props: number;
  constraints: string;
}

export interface WorkspaceKnowledgeGraphMapping {
  id: string;
  onto: string;
  db: string;
  status: string;
}

export interface WorkspaceBootstrapData {
  connectorCatalog: WorkspaceConnectorDefinition[];
  mcpProfileCatalog?: WorkspaceMcpProfile[];
  datasetFields: WorkspaceDatasetField[];
  dashboard: {
    kpis: WorkspaceKpi[];
    trendData: WorkspaceTrendPoint[];
  };
  knowledgeGraph: {
    entities: WorkspaceKnowledgeGraphEntity[];
    mappings: WorkspaceKnowledgeGraphMapping[];
  };
  skillViewRevision?: Record<string, unknown> | null;
}

export interface WorkspaceActionLoopState {
  signals: unknown[];
  policies: unknown[];
  todos: unknown[];
  reviews: unknown[];
  briefs: unknown[];
}

export interface KnowledgeBootstrap {
  resources: unknown[];
  connections: unknown[];
  publications: unknown[];
  routes?: string[];
  workspaceData: WorkspaceBootstrapData;
  actionLoop: WorkspaceActionLoopState;
  access: { spaceId: string; role: string; capabilities: string[] };
  serverTime: string;
}

type InvalidResponseFactory = (message: string) => Error;

function invalid(factory: InvalidResponseFactory, message: string): never {
  throw factory(message);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    isRecord(value) &&
    Object.values(value).every((item) => typeof item === "string")
  );
}

function isConnector(
  value: unknown,
): value is WorkspaceConnectorDefinition {
  if (!isRecord(value)) return false;
  return (
    typeof value.connectorKey === "string" &&
    typeof value.category === "string" &&
    typeof value.name === "string" &&
    typeof value.desc === "string" &&
    Array.isArray(value.capabilities) &&
    value.capabilities.every((item) => typeof item === "string") &&
    isStringRecord(value.inputSchema) &&
    (value.credentialSchema === null ||
      isStringRecord(value.credentialSchema)) &&
    Array.isArray(value.discoveryPipeline) &&
    value.discoveryPipeline.every((item) => typeof item === "string") &&
    Array.isArray(value.syncModes) &&
    value.syncModes.every((item) => typeof item === "string")
  );
}

function isDatasetField(value: unknown): value is WorkspaceDatasetField {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.type === "string" &&
    typeof value.desc === "string"
  );
}

function isKpi(value: unknown): value is WorkspaceKpi {
  return (
    isRecord(value) &&
    typeof value.label === "string" &&
    typeof value.value === "string" &&
    typeof value.trend === "string" &&
    typeof value.isUp === "boolean"
  );
}

function isTrendPoint(value: unknown): value is WorkspaceTrendPoint {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.sales === "number" &&
    Number.isFinite(value.sales) &&
    typeof value.profit === "number" &&
    Number.isFinite(value.profit)
  );
}

function isGraphEntity(
  value: unknown,
): value is WorkspaceKnowledgeGraphEntity {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.props === "number" &&
    Number.isInteger(value.props) &&
    value.props >= 0 &&
    typeof value.constraints === "string"
  );
}

function isGraphMapping(
  value: unknown,
): value is WorkspaceKnowledgeGraphMapping {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.onto === "string" &&
    typeof value.db === "string" &&
    typeof value.status === "string"
  );
}

export function parseBootstrap(
  body: unknown,
  requestIdValue: string,
  createInvalidResponse: (message: string, requestId: string) => Error,
): KnowledgeBootstrap {
  const value = isRecord(body) ? body : null;
  const access = value?.access;
  const workspaceData = isRecord(value?.workspaceData)
    ? value.workspaceData
    : undefined;
  const dashboard = isRecord(workspaceData?.dashboard)
    ? workspaceData.dashboard
    : undefined;
  const knowledgeGraph = isRecord(workspaceData?.knowledgeGraph)
    ? workspaceData.knowledgeGraph
    : undefined;
  const actionLoop = isRecord(value?.actionLoop) ? value.actionLoop : undefined;
  const fail = (message: string): never =>
    invalid(
      (reason) => createInvalidResponse(reason, requestIdValue),
      message,
    );

  if (
    !value ||
    !Array.isArray(value.resources) ||
    !Array.isArray(value.connections) ||
    !Array.isArray(value.publications) ||
    !workspaceData ||
    !Array.isArray(workspaceData.connectorCatalog) ||
    !Array.isArray(workspaceData.datasetFields) ||
    !dashboard ||
    !Array.isArray(dashboard.kpis) ||
    !Array.isArray(dashboard.trendData) ||
    !knowledgeGraph ||
    !Array.isArray(knowledgeGraph.entities) ||
    !Array.isArray(knowledgeGraph.mappings) ||
    !actionLoop ||
    !Array.isArray(actionLoop.signals) ||
    !Array.isArray(actionLoop.policies) ||
    !Array.isArray(actionLoop.todos) ||
    !Array.isArray(actionLoop.reviews) ||
    !Array.isArray(actionLoop.briefs) ||
    !isRecord(access) ||
    typeof value.serverTime !== "string" ||
    Number.isNaN(Date.parse(value.serverTime)) ||
    (value.routes !== undefined && !Array.isArray(value.routes))
  ) {
    return fail("知识服务 bootstrap 响应不符合约定。");
  }
  if (
    workspaceData.skillViewRevision !== undefined &&
    workspaceData.skillViewRevision !== null &&
    !isRecord(workspaceData.skillViewRevision)
  ) {
    return fail("知识服务 bootstrap 的 SkillViewRevision 不符合约定。");
  }
  if (
    !workspaceData.connectorCatalog.every(isConnector) ||
    (workspaceData.mcpProfileCatalog !== undefined &&
      (!Array.isArray(workspaceData.mcpProfileCatalog) ||
      !workspaceData.mcpProfileCatalog.every(
      (profile) =>
        isRecord(profile) &&
        typeof profile.profileId === "string" &&
        typeof profile.label === "string" &&
        typeof profile.transport === "string" &&
        Array.isArray(profile.toolAllowlist) &&
        profile.toolAllowlist.every((tool) => typeof tool === "string"),
      ))) ||
    !workspaceData.datasetFields.every(isDatasetField) ||
    !dashboard.kpis.every(isKpi) ||
    !dashboard.trendData.every(isTrendPoint) ||
    !knowledgeGraph.entities.every(isGraphEntity) ||
    !knowledgeGraph.mappings.every(isGraphMapping)
  ) {
    return fail("知识服务 bootstrap 工作区数据不符合约定。");
  }
  if (
    typeof access.spaceId !== "string" ||
    typeof access.role !== "string" ||
    !Array.isArray(access.capabilities) ||
    !access.capabilities.every((item) => typeof item === "string")
  ) {
    return fail("知识服务 bootstrap 缺少有效的访问上下文。");
  }
  return body as KnowledgeBootstrap;
}
