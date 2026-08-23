import { useSyncExternalStore } from 'react';

type Listener = () => void;

export class Store<T> {
  private state: T;
  private listeners: Set<Listener> = new Set();
  private key: string;

  constructor(key: string, defaultState: T) {
    this.key = key;
    try {
      const saved = localStorage.getItem(key);
      this.state = saved ? JSON.parse(saved) : defaultState;
    } catch {
      this.state = defaultState;
    }
  }

  getState = () => this.state;

  setState = (updater: (prev: T) => T) => {
    this.state = updater(this.state);
    localStorage.setItem(this.key, JSON.stringify(this.state));
    this.listeners.forEach(l => l());
  };

  subscribe = (l: Listener) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };
}

export function useStore<T>(store: Store<T>) {
  return useSyncExternalStore(store.subscribe, store.getState);
}

export interface WorkspaceResource {
  id: string;
  displayName: string;
  resourceKind: 'source' | 'dataset' | 'document' | 'knowledge_base' | 'semantic_model' | 'skill' | 'artifact' | 'automation' | 'publication' | 'connection';
  subtype: string;
  space: 'personal' | 'team';
  owner: string;
  version: string;
  lifecycle: 'draft' | 'published';
  permission: boolean;
  capabilities: string[];
  configRef?: any;
  lineage: { sourceIds: string[] };
  createdAt: string;
  updatedAt: string;
  tokenEstimate?: number;
  content?: string;
  chunksCount?: number;
  type?: string;
  artifactType?: string;
  name?: string;
  readonly?: boolean;
}

export interface ConnectorDef {
  connectorKey: string;
  category: 'office' | 'file' | 'db' | 'api' | 'custom';
  name: string;
  desc: string;
  capabilities: string[];
  inputSchema: any;
  credentialSchema: any;
  discoveryPipeline: string[];
  syncModes: string[];
}

export const initialConnectorRegistry: ConnectorDef[] = [
  // Office (10)
  { connectorKey: 'lark_doc', category: 'office', name: '飞书文档', desc: '同步飞书文档内容', capabilities: ['非结构化', '权限继承'], inputSchema: { url: 'string', scope: 'select' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '抓取内容块', '分段提取'], syncModes: ['incremental'] },
  { connectorKey: 'lark_wiki', category: 'office', name: '飞书知识库 Wiki', desc: '整库同步与结构解析', capabilities: ['非结构化', '层级保留'], inputSchema: { url: 'string' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '遍历目录树', '分段提取'], syncModes: ['incremental'] },
  { connectorKey: 'lark_drive', category: 'office', name: '飞书云盘', desc: '读取云盘文件资源', capabilities: ['文件', '多格式'], inputSchema: { folder_url: 'string' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '遍历文件列表', '文件类型识别'], syncModes: ['incremental'] },
  { connectorKey: 'lark_meeting', category: 'office', name: '飞书会议', desc: '按条件选取并导入会议纪要', capabilities: ['会议纪要', '时间范围'], inputSchema: { calendar: 'select', date_range: 'select', attendees: 'string' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '检索会议纪要', '提取文本与总结'], syncModes: ['incremental'] },
  { connectorKey: 'lark_minutes', category: 'office', name: '飞书妙记', desc: '单篇或批量会议纪要', capabilities: ['音视频转写'], inputSchema: { url: 'string' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '抓取文本', '解析时间轴'], syncModes: ['incremental'] },
  { connectorKey: 'lark_group', category: 'office', name: '飞书群聊/话题消息', desc: '读取用户有权限的群聊与话题', capabilities: ['会话上下文', '带附件'], inputSchema: { group_id: 'select', time_range: 'select', include_attachments: 'select' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '抓取消息记录', '过滤有效信息'], syncModes: ['incremental'] },
  { connectorKey: 'lark_chat', category: 'office', name: '单聊记录', desc: '读取单聊对话', capabilities: ['个人记录'], inputSchema: { user_id: 'select', time_range: 'select' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '抓取消息'], syncModes: ['incremental'] },
  { connectorKey: 'lark_sheet', category: 'office', name: '飞书电子表格', desc: '读取表格数据为结构化表', capabilities: ['结构化数据'], inputSchema: { url: 'string', sheet_name: 'string' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '解析行列结构', '类型推断'], syncModes: ['incremental'] },
  { connectorKey: 'lark_base', category: 'office', name: '飞书多维表格 Base', desc: '读取 Base 数据表与视图', capabilities: ['关系型表'], inputSchema: { app_token: 'string', table_id: 'select' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '获取表元数据', '读取记录'], syncModes: ['incremental'] },
  { connectorKey: 'lark_mail', category: 'office', name: '飞书邮件', desc: '提取指定条件的邮件内容', capabilities: ['邮件检索'], inputSchema: { folder: 'select', query: 'string' }, credentialSchema: { oauth: 'oauth' }, discoveryPipeline: ['检查权限', '检索邮件', '提取正文与附件元数据'], syncModes: ['incremental'] },
  
  // File (8)
  { connectorKey: 'csv', category: 'file', name: 'CSV', desc: '纯文本表格数据', capabilities: ['结构化'], inputSchema: { file: 'file' }, credentialSchema: null, discoveryPipeline: ['上传并切片', '解析元数据', '识别列类型'], syncModes: ['full'] },
  { connectorKey: 'excel', category: 'file', name: 'Excel', desc: '支持 .xlsx, .xls', capabilities: ['结构化', '多Sheet'], inputSchema: { file: 'file', sheet: 'string' }, credentialSchema: null, discoveryPipeline: ['上传并解析', 'Sheet选择', '列类型推断'], syncModes: ['full'] },
  { connectorKey: 'json', category: 'file', name: 'JSON', desc: '半结构化数据', capabilities: ['半结构化'], inputSchema: { file: 'file' }, credentialSchema: null, discoveryPipeline: ['上传', '解析层级', '拍平字段'], syncModes: ['full'] },
  { connectorKey: 'parquet', category: 'file', name: 'Parquet', desc: '列式存储文件', capabilities: ['大数据', '结构化'], inputSchema: { file: 'file' }, credentialSchema: null, discoveryPipeline: ['上传', '读取 Schema', '验证格式'], syncModes: ['full'] },
  { connectorKey: 'doc_txt', category: 'file', name: 'PDF/Markdown/TXT/HTML', desc: '非结构化文档', capabilities: ['文档', '长文本'], inputSchema: { file: 'file' }, credentialSchema: null, discoveryPipeline: ['上传', '文本提取', '结构化分块'], syncModes: ['full'] },
  { connectorKey: 'local_file', category: 'file', name: '本地文件', desc: '从本地上传通用文件', capabilities: ['通用'], inputSchema: { file: 'file' }, credentialSchema: null, discoveryPipeline: ['上传', '格式检测'], syncModes: ['full'] },
  { connectorKey: 's3', category: 'file', name: 'AWS S3', desc: 'Amazon 对象存储', capabilities: ['云存储'], inputSchema: { bucket: 'string', path: 'string' }, credentialSchema: { access_key: 'string', secret_key: 'password' }, discoveryPipeline: ['连接测试', '遍历对象列表'], syncModes: ['incremental'] },
  { connectorKey: 'oss', category: 'file', name: 'Aliyun OSS', desc: '阿里云对象存储', capabilities: ['云存储'], inputSchema: { bucket: 'string', path: 'string' }, credentialSchema: { access_key: 'string', secret_key: 'password' }, discoveryPipeline: ['连接测试', '遍历对象列表'], syncModes: ['incremental'] },

  // DB/DW (11)
  { connectorKey: 'postgresql', category: 'db', name: 'PostgreSQL', desc: '开源关系型数据库', capabilities: ['关系型', '实时'], inputSchema: { host: 'string', port: 'number', database: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '抓取库表', '采样校验'], syncModes: ['full', 'incremental'] },
  { connectorKey: 'mysql', category: 'db', name: 'MySQL', desc: '流行开源数据库', capabilities: ['关系型'], inputSchema: { host: 'string', port: 'number', database: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '抓取库表', '采样校验'], syncModes: ['full', 'incremental'] },
  { connectorKey: 'oracle', category: 'db', name: 'Oracle', desc: '企业级关系型数据库', capabilities: ['关系型', '企业级'], inputSchema: { host: 'string', port: 'number', service_name: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '抓取库表', '采样校验'], syncModes: ['full', 'incremental'] },
  { connectorKey: 'sqlserver', category: 'db', name: 'SQL Server', desc: '微软数据库', capabilities: ['关系型'], inputSchema: { host: 'string', port: 'number', database: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '抓取库表', '采样校验'], syncModes: ['full', 'incremental'] },
  { connectorKey: 'sqlite', category: 'db', name: 'SQLite', desc: '本地轻量级库', capabilities: ['关系型', '本地'], inputSchema: { file: 'file' }, credentialSchema: null, discoveryPipeline: ['加载文件', '读取列表'], syncModes: ['full'] },
  { connectorKey: 'clickhouse', category: 'db', name: 'ClickHouse', desc: '列式 OLAP', capabilities: ['OLAP', '大数据'], inputSchema: { host: 'string', port: 'number', database: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '同步元数据'], syncModes: ['incremental'] },
  { connectorKey: 'doris', category: 'db', name: 'Doris', desc: '实时分析型', capabilities: ['OLAP', '实时'], inputSchema: { host: 'string', port: 'number', database: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '同步元数据'], syncModes: ['incremental'] },
  { connectorKey: 'starrocks', category: 'db', name: 'StarRocks', desc: '极速湖仓', capabilities: ['OLAP'], inputSchema: { host: 'string', port: 'number', database: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '同步元数据'], syncModes: ['incremental'] },
  { connectorKey: 'snowflake', category: 'db', name: 'Snowflake', desc: '云原生数据仓库', capabilities: ['云数仓'], inputSchema: { account: 'string', warehouse: 'string', database: 'string' }, credentialSchema: { user: 'string', pass: 'password' }, discoveryPipeline: ['连接测试', '抓取元数据'], syncModes: ['incremental'] },
  { connectorKey: 'bigquery', category: 'db', name: 'BigQuery', desc: 'Google 云数仓', capabilities: ['云数仓'], inputSchema: { project_id: 'string', dataset_id: 'string' }, credentialSchema: { service_account_json: 'file' }, discoveryPipeline: ['鉴权测试', '抓取元数据'], syncModes: ['incremental'] },
  { connectorKey: 'hive', category: 'db', name: 'Hive', desc: 'Hadoop 体系表', capabilities: ['大数据'], inputSchema: { host: 'string', port: 'number', database: 'string' }, credentialSchema: { user: 'string' }, discoveryPipeline: ['连接测试', '抓取元数据'], syncModes: ['incremental'] },

  // API (5)
  { connectorKey: 'rest_api', category: 'api', name: 'REST / OpenAPI', desc: '标准 HTTP 接口或 Swagger', capabilities: ['接口调用'], inputSchema: { spec_url_or_endpoint: 'string' }, credentialSchema: { api_key: 'password', auth_type: 'select' }, discoveryPipeline: ['校验地址', '解析定义', '推断操作'], syncModes: ['realtime'] },
  { connectorKey: 'graphql', category: 'api', name: 'GraphQL', desc: 'GraphQL 查询接口', capabilities: ['按需查询'], inputSchema: { endpoint: 'string' }, credentialSchema: { token: 'password' }, discoveryPipeline: ['获取结构', '构建节点树'], syncModes: ['realtime'] },
  { connectorKey: 'web_discovery', category: 'api', name: 'Web API Discovery', desc: '网页自动抓包封装为 API', capabilities: ['智能发现'], inputSchema: { target_url: 'string' }, credentialSchema: { login_cookie: 'password' }, discoveryPipeline: ['模拟访问', '捕获请求', '推断接口定义'], syncModes: ['realtime'] },
  { connectorKey: 'webhook', category: 'api', name: 'Webhook', desc: '被动接收推送数据', capabilities: ['事件驱动'], inputSchema: { listen_path: 'string' }, credentialSchema: { secret: 'string' }, discoveryPipeline: ['生成接收地址', '等待请求', '推断格式'], syncModes: ['realtime'] },
  { connectorKey: 'kafka', category: 'api', name: 'Kafka', desc: '流式消息队列', capabilities: ['流数据'], inputSchema: { bootstrap_servers: 'string', topic: 'string' }, credentialSchema: { sasl_jaas: 'password' }, discoveryPipeline: ['连接集群', '订阅流', '解析消息定义'], syncModes: ['realtime'] },

  // Custom (3)
  { connectorKey: 'mcp_custom', category: 'custom', name: 'MCP Server', desc: '标准 Model Context Protocol 服务', capabilities: ['Agent Tools', '可执行'], inputSchema: { transport: 'select', endpoint: 'string' }, credentialSchema: { token: 'password' }, discoveryPipeline: ['握手校验', '发现可用工具'], syncModes: ['realtime'] },
  { connectorKey: 'custom_http', category: 'custom', name: '自定义 HTTP Connector', desc: '从头编写请求与解析逻辑', capabilities: ['高可定制'], inputSchema: { name: 'string', base_url: 'string' }, credentialSchema: { custom_headers: 'string' }, discoveryPipeline: ['保存定义', '测试连接'], syncModes: ['realtime'] },
  { connectorKey: 'openapi_spec', category: 'custom', name: '上传 OpenAPI Spec', desc: '直接上传 YAML/JSON API 描述文件', capabilities: ['静态解析'], inputSchema: { spec_file: 'file' }, credentialSchema: { token: 'password' }, discoveryPipeline: ['解析定义', '列出操作'], syncModes: ['realtime'] },
];

export const customRegistryStore = new Store<ConnectorDef[]>('v2106_custom_connectors', []);

export const getRegistry = () => {
  return [...initialConnectorRegistry, ...customRegistryStore.getState()];
};

const defaultResourcesV3: WorkspaceResource[] = [
  { id: 'res_sample_postgres', displayName: 'PostgreSQL_ERP', name: 'PostgreSQL_ERP', resourceKind: 'source', subtype: 'postgresql', space: 'personal', owner: 'haoxingjun', version: 'V1.0', lifecycle: 'published', permission: true, capabilities: ['refreshable', 'queryable'], lineage: { sourceIds: [] }, createdAt: '2023-10-24', updatedAt: '2023-10-24', tokenEstimate: 0.5, type: 'source' },
  { id: 'res_sample_csv', displayName: '库存明细.csv', name: '库存明细.csv', resourceKind: 'dataset', subtype: 'excel', space: 'personal', owner: 'haoxingjun', version: 'V1.0', lifecycle: 'published', permission: true, capabilities: ['queryable'], lineage: { sourceIds: [] }, createdAt: '2023-10-24', updatedAt: '2023-10-24', tokenEstimate: 0.8, type: 'dataset' },
  { id: 'res_dash_east', displayName: '华东销售看板', name: '华东销售看板', resourceKind: 'artifact', subtype: 'dashboard', space: 'personal', owner: 'haoxingjun', version: 'V2.1', lifecycle: 'draft', permission: true, capabilities: ['refreshable', 'shareable'], lineage: { sourceIds: ['res_sample_postgres'] }, createdAt: '2023-10-25', updatedAt: '刚刚', tokenEstimate: 3.0, type: 'personal_artifact', artifactType: 'dashboard' },
  { id: 'skill_finance_monitor', displayName: '金融行情监控 Skill', name: '金融行情监控 Skill', resourceKind: 'skill', subtype: 'custom_http', space: 'personal', owner: 'haoxingjun', version: 'V1.0', lifecycle: 'draft', permission: true, capabilities: ['executable'], lineage: { sourceIds: ['conn_custom_http_finance'] }, createdAt: '刚刚', updatedAt: '刚刚', tokenEstimate: 1.0, type: 'personal_artifact', artifactType: 'skill' }
];

export const resourceStore = new Store<WorkspaceResource[]>('v2113_resources', defaultResourcesV3);
export const agentPublicationStore = new Store<any[]>('v2113_agent_publications', []);

export const addResource = (item: WorkspaceResource) => {
  resourceStore.setState(prev => {
    if(prev.find(r => r.id === item.id)) return prev.map(r => r.id === item.id ? item : r);
    return [item, ...prev];
  });
};

export const getFullCatalog = () => {
  return resourceStore.getState();
};

export const connectionStore = new Store('v2113_connections', [
  {
    id: 'conn_custom_http_finance',
    type: 'custom_http',
    name: '全球金融实时行情 API',
    status: 'connected',
    owner: 'haoxingjun',
    isTeam: false,
    syncPolicy: '实时流',
    schemas: []
  }
]);

export function getResourceDescriptor(fileId: string, searchParams: URLSearchParams, allResources: any[]) {
  if (fileId === 'evaluation_detail') {
    const targetId = searchParams.get('eval_target');
    let targetName = '产物质量评测';
    if (targetId) {
      const targetItem = allResources.find((r:any) => r.id === targetId || r.resourceId === targetId);
      if (targetItem) {
        targetName = `评测 · ${targetItem.displayName || targetItem.name}`;
      } else {
        if (targetId.includes('dashboard_sales_east')) targetName = '评测 · 华东销售经营看板';
        else if (targetId === 'res_dash_east') targetName = '评测 · 华东销售看板';
        else targetName = `评测 · ${targetId}`;
      }
    }
    return {
      identity: `eval_${targetId || 'general'}`,
      id: 'evaluation_detail',
      name: targetName,
      type: 'evaluation',
      artifactType: 'evaluation',
      version: searchParams.get('version') || 'V1.0',
      isResourceLevel: true
    };
  }

  const storeItem = allResources.find((r:any) => r.id === fileId || r.resourceId === fileId);
  if (storeItem) {
    return {
      identity: storeItem.id,
      id: storeItem.id,
      name: searchParams.get('custom_name') || storeItem.displayName || storeItem.name,
      type: storeItem.resourceKind || storeItem.type,
      artifactType: storeItem.subtype || storeItem.artifactType || storeItem.type,
      version: searchParams.get('version') || storeItem.version || 'V1.0',
      space: storeItem.space || 'personal',
      isResourceLevel: true,
      resourceKind: storeItem.resourceKind,
      subtype: storeItem.subtype,
      lineage: storeItem.lineage
    };
  }

  const fixtureMap: Record<string, any> = {
    'res_sample_postgres': { name: 'PostgreSQL_ERP', type: 'connection', artifactType: 'postgresql' },
    'res_dash_recruitment': { name: '全球招聘供需看板', type: 'dashboard', artifactType: 'dashboard', version: 'V1.0' },
    'semantic_sales': { name: '销售主题模型', type: 'semantic', artifactType: 'semantic' },
    'dashboard_sales_east': { name: '华东销售经营看板', type: 'dashboard', artifactType: 'dashboard', version: 'V2.1' },
    'kg_sales': { name: '销售业务知识图谱', type: 'knowledge_graph', artifactType: 'knowledge_graph' },
    'kb_sales': { name: '销售话术知识库', type: 'knowledge_base', artifactType: 'knowledge_base', version: 'V1.0' },
    'dataset_excel': { name: 'Q3 销售数据', type: 'dataset', artifactType: 'excel' },
    'dataset_postgresql': { name: 'PostgreSQL_Orders', type: 'dataset', artifactType: 'postgresql' },
    'dataset_view': { name: '计算视图_营收明细', type: 'dataset', artifactType: 'view' },
    'dataset_etl': { name: '数据加工_宽表', type: 'dataset', artifactType: 'etl' },
    'dataset_sales': { name: '销售数据集', type: 'dataset', artifactType: 'dataset' },
    'chart_conversion': { name: '渠道转化趋势', type: 'chart', artifactType: 'chart' },
    'team_dashboard_monthly': { name: '月度经营复盘', type: 'dashboard', artifactType: 'dashboard', space: 'team' },
    'res_dash_finance': { name: '金融行情监控看板', type: 'dashboard', artifactType: 'dashboard', version: 'V1.0' },
  };

  if (fixtureMap[fileId]) {
    const fix = fixtureMap[fileId];
    return {
      identity: fileId,
      id: fileId,
      name: searchParams.get('custom_name') || fix.name,
      type: fix.type,
      artifactType: fix.artifactType,
      version: searchParams.get('version') || fix.version || 'V1.0',
      space: fix.space || 'personal',
      isResourceLevel: true
    };
  }

  if (fileId && !['welcome', 'data_overview', 'add_data', 'add_kb', 'upload_doc', 'skill_builder', 'connector_catalog', 'workspace_empty'].includes(fileId)) {
    return {
      identity: fileId,
      id: fileId,
      name: searchParams.get('custom_name') || fileId,
      type: 'resource',
      artifactType: 'resource',
      version: searchParams.get('version') || 'V1.0',
      space: 'personal',
      isResourceLevel: true
    };
  }
  
  return null;
}