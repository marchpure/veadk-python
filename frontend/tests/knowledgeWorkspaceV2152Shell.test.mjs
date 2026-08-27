import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../src/knowledge-workspace/", import.meta.url);
const repoRoot = new URL("../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const fixture = JSON.parse(
  readFileSync(
    new URL("tests/fixtures/knowledge_step3b_w4_v2152/captures.json", repoRoot),
    "utf8",
  ),
);
const visualEvidenceScript = readFileSync(
  new URL("frontend/scripts/knowledge_step3b_w4_v2152_visual_evidence.mjs", repoRoot),
  "utf8",
);

const host = read("WorkspaceHost.tsx");
const mainArea = read("frozen-ui/components/Layout/MainAreaPane.tsx");
const assistant = read("frozen-ui/components/RightPane/ChatAssistant.tsx");
const emptyView = read("frozen-ui/components/MainArea/WorkspaceEmptyView.tsx");
const tree = read("frozen-ui/components/Layout/FileTreePane.tsx");
const dataset = read("frozen-ui/components/MainArea/DatasetView.tsx");
const explore = read("frozen-ui/components/MainArea/ExploreView.tsx");
const layout = read("frozen-ui/components/Layout/WorkspaceLayout.tsx");
const homeComposer = read("frozen-ui/components/Layout/HomeComposer.tsx");
const publishModal = read("frozen-ui/components/Modals/PublishModal.tsx");
const store = read("production/store.ts");
const typedPorts = read("production/typedPorts.ts");
const sop = read("frozen-ui/components/MainArea/SkillSOPView.tsx");
const monitoring = read("frozen-ui/components/MainArea/SkillMonitoringView.tsx");
const dashboard = read("frozen-ui/components/MainArea/DashboardView.tsx");
const artifactHeader = read("frozen-ui/components/MainArea/ArtifactHeader.tsx");
const semantic = read("frozen-ui/components/MainArea/SemanticView.tsx");
const graph = read("frozen-ui/components/MainArea/KnowledgeGraphView.tsx");
const knowledgeBase = read("frozen-ui/components/MainArea/KnowledgeBaseView.tsx");
const addKnowledgeBase = read("frozen-ui/components/MainArea/AddKnowledgeBaseView.tsx");
const skillArtifact = read("frozen-ui/components/MainArea/SkillArtifactView.tsx");
const skillHtmlRevision = read("frozen-ui/components/MainArea/SkillHtmlRevisionView.tsx");
const connectionDetail = read("frozen-ui/components/MainArea/ConnectionDetailView.tsx");
const uploadDoc = read("frozen-ui/components/MainArea/UploadDocView.tsx");
const evaluationCenter = read("frozen-ui/components/MainArea/EvaluationCenterView.tsx");
const actionPolicy = read("frozen-ui/components/Modals/ActionPolicyModal.tsx");
const propertyEditor = read("frozen-ui/components/RightPane/PropertyEditor.tsx");
const frozenStore = read("frozen-ui/lib/store.ts");
const addData = read("frozen-ui/components/MainArea/AddDataView.tsx");
const skillBuilder = read("frozen-ui/components/MainArea/SkillBuilderView.tsx");

test("v2.15.2 capture matrix tracks exactly the frozen 15 states", () => {
  assert.equal(fixture.prototypeSha256, "0a672e34dd8f5cf416a73334b519679ee756f2c50ea8710166dae4b6b6c41b15");
  assert.equal(fixture.states.length, 15);
  assert.deepEqual(
    fixture.states.map((state) => state.stateUrl),
    [
      "/?file=welcome",
      "/?file=welcome&chat=clarify",
      "/?file=draft_sop_bluetooth&pane=open",
      "/?file=draft_sop_bluetooth&edit_step=Step_2&pane=open",
      "/?file=draft_sop_bluetooth&run_state=input&pane=open",
      "/?file=draft_sop_bluetooth&run_state=result&pane=open",
      "/?file=draft_sop_bluetooth&run_state=result&pane=open&modal=publish_agent",
      "/?file=draft_dash_anta&pane=open",
      "/?file=draft_dash_anta&run_state=result&pane=open",
      "/?file=draft_dash_anta&run_state=result&pane=open&modal=publish",
      "/?file=draft_sop_haidilao&pane=open",
      "/?file=draft_sop_haidilao&run_state=input&pane=open",
      "/?file=draft_sop_haidilao&run_state=result&pane=open",
      "/?file=pub_sop_bluetooth",
      "/?file=draft_sop_bluetooth_opt",
    ],
  );
});

test("v2.15.2 browser evidence gate captures prototype and W4 across required viewports", () => {
  assert.match(visualEvidenceScript, /desktop-1920/);
  assert.match(visualEvidenceScript, /studio-1440/);
  assert.match(visualEvidenceScript, /mobile-390/);
  assert.match(visualEvidenceScript, /capturePrototypeReference/);
  assert.match(visualEvidenceScript, /captureW4Actual/);
  assert.match(visualEvidenceScript, /createDiffArtifacts/);
  assert.match(visualEvidenceScript, /collectDomAndLayoutSummary/);
  assert.match(visualEvidenceScript, /collectKeyboardEvidence/);
  assert.match(visualEvidenceScript, /collectAgentPaneWidthEvidence/);
  assert.match(visualEvidenceScript, /consoleErrors/);
  assert.match(visualEvidenceScript, /failedRequests/);
  assert.match(visualEvidenceScript, /horizontalOverflowPx/);
  assert.match(visualEvidenceScript, /skill-authoring\.start/);
  assert.match(visualEvidenceScript, /Trusted HTML artifact/);
});

test("legacy skill deep links normalize into the shared workspace shell", () => {
  assert.match(host, /normalizeLegacySkillDeepLink/);
  assert.match(host, /url\.searchParams\.set\("file", skillId\)/);
  assert.match(host, /<FrozenWorkspaceApp \/>/);
  assert.doesNotMatch(host, /get\("view"\) === "skill"/);
  assert.doesNotMatch(host, /<SkillViewShell/);
});

test("v2.15.2 route ids are available and routed inside MainAreaPane", () => {
  assert.match(store, /SERVER_FEATURE_ROUTES/);
  assert.match(store, /resourceStore\s*\.getState\(\)\s*\.some/);
  assert.match(mainArea, /SkillSOPView/);
  assert.match(mainArea, /SkillMonitoringView/);
  assert.doesNotMatch(mainArea, /draft_sop_bluetooth|draft_sop_haidilao|draft_dash_anta|pub_sop_bluetooth/);
  assert.match(mainArea, /resource\?\.resourceKind === 'skill_draft'/);
  assert.match(mainArea, /resource\?\.resourceKind === 'skill'/);
  assert.match(mainArea, /resource\?\.subtype === 'sop'/);
  assert.match(mainArea, /resource\?\.subtype === 'monitoring'/);
  assert.match(mainArea, /activeRevisionMatchesRoute/);
  assert.match(mainArea, /view_revision_id/);
});

test("right assistant no longer exposes editable artifact stage plan controls", () => {
  assert.doesNotMatch(assistant, /多阶段产物生成计划|Artifact Plan|添加 Stage|outputType|publishPolicy|handleAddStage|handleRemoveStage|handleStageChange/);
  assert.doesNotMatch(assistant, /setTimeout|setInterval/);
  assert.match(assistant, /BuildPlan 由服务端 Agent 返回/);
  assert.match(assistant, /aria-expanded=\{planExpanded\}/);
  assert.match(assistant, /执行并渲染/);
});

test("home composer restores the v2.15.2 core journey without URL-only handoff", () => {
  for (const label of [
    "今天想解决什么业务问题",
    "上传文件",
    "拖入",
    "@",
    "上下文",
    "来源",
    "revision",
    "模板库",
    "Dashboard",
    "Semantic",
    "SOP",
    "Knowledge",
    "Graph",
    "Ontology",
    "Monitoring",
    "Agent 推荐模板",
    "重试",
    "取消",
  ]) {
    assert.match(homeComposer, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(homeComposer, /getFullCatalog/);
  assert.match(homeComposer, /getWorkspaceAdapter\(\)\.command/);
  assert.match(homeComposer, /command:\s*['"]skill-authoring\.start['"]/);
  assert.match(homeComposer, /resourceRefs/);
  assert.match(homeComposer, /requestedKind/);
  assert.match(homeComposer, /templateRef:\s*selectedTemplateRef/);
  assert.match(homeComposer, /templateSpecStore/);
  assert.match(homeComposer, /selectedTemplateRef/);
  assert.match(homeComposer, /模板库/);
  assert.doesNotMatch(homeComposer, /Template Registry|typed seam|production adapter|spec\.md/);
  assert.match(homeComposer, /templateSpecStore/);
  assert.doesNotMatch(emptyView, /spec\.md/);
  assert.match(emptyView, /选择模板/);
  assert.doesNotMatch(homeComposer, /id:\s*["']html["']/);
  assert.match(homeComposer, /draft_id|draftId/);
  assert.match(homeComposer, /operation_id|operationId/);
  assert.doesNotMatch(homeComposer, /from ['"]lucide-react['"]/);
  assert.doesNotMatch(homeComposer, /params\.set\(["']request["'], request\.trim\(\)\);\s*setSearchParams\(params\)/);
  assert.doesNotMatch(homeComposer, /localStorage|setTimeout|setInterval|蓝牙|海底捞|LS6|LS7|经营分析看板/);
});

test("new Skill data-source picker supports multiple real Golden assets", () => {
  assert.match(homeComposer, /接入数据源/);
  assert.match(homeComposer, /sourcePickerOpen/);
  assert.match(homeComposer, /selectedSourceIds/);
  assert.match(homeComposer, /type="checkbox"/);
  assert.match(homeComposer, /resourceKind === ["']golden_asset["']/);
  assert.match(homeComposer, /goldenRevisionId/);
  assert.match(homeComposer, /加入上下文/);
  assert.match(homeComposer, /selected\.forEach\(\(item: any\) => addChip\(item\)\)/);
  assert.match(homeComposer, /resourceRefs = contextChips/);
  assert.match(homeComposer, /fixedRevisions: resourceRefs\.map/);
});

test("skill builder preserves home prompt, context, template, and hides legacy wizard", () => {
  assert.match(skillBuilder, /searchParams\.get\(['"]request['"]\)/);
  assert.match(skillBuilder, /searchParams\.get\(['"]template['"]\)/);
  assert.match(skillBuilder, /searchParams\.get\(['"]context_refs['"]\)/);
  assert.match(skillBuilder, /searchParams\.get\(['"]workspace_scope['"]\)/);
  assert.match(skillBuilder, /resourceStore\.getState\(\)/);
  assert.match(skillBuilder, /authoringSession|authoring_session/);
  assert.match(skillBuilder, /serverPrompt/);
  assert.match(skillBuilder, /serverTemplate/);
  assert.match(skillBuilder, /serverContextRefs/);
  assert.match(skillBuilder, /SkillAuthoringStartPayload/);
  assert.match(skillBuilder, /templateRef:\s*selectedTemplateRef/);
  assert.match(skillBuilder, /templateSpecStore/);
  assert.match(skillBuilder, /TrustedHtmlArtifactRenderer/);
  assert.match(skillBuilder, /高级详情|审计/);
  assert.match(skillBuilder, /Manifest/);
  assert.match(skillBuilder, /BuildPlan/);
  assert.doesNotMatch(skillBuilder, /const steps = \['选择输入', '发现\/解析', '编辑 Manifest', '测试', '保存版本', '发布'\]/);
  assert.doesNotMatch(skillBuilder, />上一步<|>下一步</);
  assert.doesNotMatch(skillBuilder, /textarea[^>]+value=\{manifest\}[^>]+onChange=\{e=>setManifest/);
  assert.doesNotMatch(skillBuilder, /setPrompt\(''\)/);
  assert.doesNotMatch(skillBuilder, /localStorage|setTimeout|setInterval|测试成功|返回 200 OK/);
});

test("right assistant consumes the typed streaming/timeline seam instead of one-shot replies", () => {
  assert.match(typedPorts, /command:\s*"skill-authoring\.start"/);
  assert.match(typedPorts, /command:\s*"skill-authoring\.answer"/);
  assert.match(assistant, /useAgentRuntime/);
  assert.match(assistant, /<AgentTimeline/);
  assert.match(assistant, /agentRuntime\.followOperation/);
  assert.match(assistant, /agentRuntime\.stop/);
  assert.match(assistant, /agentRuntime\.retry/);
  assert.match(assistant, /agentRuntime\.resume/);
  assert.doesNotMatch(assistant, /getWorkspaceAdapter\(\)\.stream/);
  assert.doesNotMatch(assistant, /appendTimelineItem|KnowledgeStream/);
  assert.match(assistant, /nearBottomRef|userScrolledAway|scrollTop/);
  assert.doesNotMatch(assistant, /setAgentReply\(result\.draft\.manifest\?\.description \|\| result\.operation\?\.summary \|\| ['"]已收到真实上下文/);
  assert.doesNotMatch(assistant, /setAgentReply\(result\.operation\?\.summary \|\| ['"]Runner 已完成执行/);
  assert.doesNotMatch(assistant, /chain-of-thought|system prompt|系统提示词|密钥|secret/i);
});

test("dashboard and header visible actions are command-backed or explicitly gated", () => {
  assert.match(dashboard, /command:\s*['"]refresh\.run['"]/);
  assert.match(dashboard, /command:\s*['"]artifact\.export['"]/);
  assert.match(dashboard, /bootstrapWorkspace/);
  assert.match(dashboard, /缺少.*command seam|尚未集成|等待服务端/);
  assert.doesNotMatch(dashboard, /showToast\?\(`筛选请求|showToast\?\(`钻取请求|showToast\?\(['"]导出请求已交给|showToast\?\(['"]刷新请求已交给/);

  assert.match(artifactHeader, /command:\s*['"]refresh\.run['"]/);
  assert.match(artifactHeader, /bootstrapWorkspace/);
  assert.match(artifactHeader, /disabled=\{[^}]*!canRefresh/);
  assert.doesNotMatch(artifactHeader, /showToast\?\(['"]刷新中\.\.\.['"]\)/);
});

test("SOP and monitoring states use backend command seams instead of local fake success", () => {
  assert.match(sop, /command: 'skill-draft\.run'/);
  assert.match(sop, /command: 'skill-authoring\.patch'/);
  assert.match(sop, /bootstrapWorkspace/);
  assert.match(sop, /add_context_item/);
  assert.doesNotMatch(sop, /setTimeout/);
  assert.match(monitoring, /command: 'skill-authoring\.patch'/);
  assert.doesNotMatch(monitoring, /已为您创建个人优化草稿|setTimeout/);
  assert.match(sop, /skillViewRevision/);
  assert.match(sop, /operationId/);
  assert.doesNotMatch(sop, /setRunState\(['"]result['"]\)/);
});

test("workspace production shell does not expose query-driven mock sample data", () => {
  for (const source of [emptyView, tree, dataset, explore]) {
    assert.doesNotMatch(source, /localStorage\.(?:setItem|getItem)\(\s*['"]demo_/);
    assert.doesNotMatch(source, /sample_data_added|isSampleAdded|dataset_mock_upload|使用示例数据|演示数据/);
  }
  assert.doesNotMatch(emptyView, /setTimeout/);
});

test("right assistant suggestions do not infer business facts from ids or names", () => {
  assert.doesNotMatch(assistant, /res_dash_recruitment|招聘|越南|金融|行情|华东区|销售数据周报|Oracle|飞书文档|话术/);
  assert.doesNotMatch(assistant, /name\?\.\s*includes|activeChip\.id ===/);
  assert.doesNotMatch(assistant, /p\.set\('file', 'res_dash_recruitment'\)/);
});

test("dataset and explore surfaces fail closed instead of rendering fixed business data", () => {
  for (const source of [dataset, explore]) {
    assert.doesNotMatch(source, /Q3 销售数据|销售数据集|华东区|电子产品|经营分析|销售趋势|质量 92|4,521|2\.4 MB|Math\.random/);
    assert.match(source, /DatasetViewModel|等待服务端数据|activeSkillViewRevision|getResourceDescriptor/);
  }
});

test("semantic, knowledge base, graph, and command seams avoid default sales facts", () => {
  for (const source of [semantic, knowledgeBase, addKnowledgeBase, graph, store, tree, frozenStore, evaluationCenter, actionPolicy]) {
    assert.doesNotMatch(source, /销售制度知识库|销售主题模型|销售业务知识图谱|销售分析目录|销售分析 Agent|授权成功|聚合各渠道的销售制度|回答销售制度/);
    assert.doesNotMatch(source, /华东区|越南|招聘需求|国家=越南|岗位=销售|华东销售|金融行情|全球招聘/);
  }
});

test("touched production actions do not use toast-only success or local persisted fixture stores", () => {
  for (const source of [skillArtifact, connectionDetail, uploadDoc, addKnowledgeBase, knowledgeBase, propertyEditor]) {
    assert.doesNotMatch(source, /测试执行成功|触发同步成功|修改已成功应用|知识文档解析并入库成功|索引成功|成功！/);
  }
  assert.doesNotMatch(propertyEditor, /chartTitle|chartType|按周销售与利润趋势|setSearchParams\(p\).*chart/i);
  assert.match(propertyEditor, /等待服务端属性面板|action', 'ai_edit_element'|add_context_item/);
  assert.doesNotMatch(frozenStore, /localStorage|fixtureMap|defaultResourcesV3|res_sample_postgres|res_dash_east|skill_finance_monitor/);
  assert.doesNotMatch(layout, /setTimeout\(\(\) => showToast\(`(?:该上下文已加入|已加入对话上下文)`\), 100\)/);
  assert.match(layout, /<ExportModal onClose=\{closeModal\} showToast=\{showToast\} searchParams=\{searchParams\} \/>/);
});

test("new v2.15.2 production views do not hardcode business facts or fake metrics", () => {
  const forbiddenBusinessFacts = [
    "蓝牙诊断信号 API",
    "蓝牙异常排查手册",
    "蓝牙断连排查 SOP",
    "海底捞卫生巡检 SOP",
    "门店卫生巡检与处置 SOP",
    "LS6",
    "LS7",
    "OS-2.1.0",
    "V1.2.4",
    "-85dBm",
    "-92dBm",
    "12 条",
    "1,245",
    "98.2%",
    "1.4s",
    "tr_89112",
    "成功断言",
    "服务端执行完成",
  ];
  for (const fact of forbiddenBusinessFacts) {
    assert.doesNotMatch(sop, new RegExp(fact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.doesNotMatch(monitoring, new RegExp(fact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("publish and shell controls do not fake successful production state", () => {
  for (const source of [layout, publishModal, tree]) {
    assert.doesNotMatch(source, /已成功发布|新发布|new_publish|dragStore\.setState\(\{ status: 'success'|88 分|数据正确性通过|安全扫描通过|2 项未解决风险|演示环境|onResetDemo|handleResetDemo/);
  }
  assert.match(publishModal, /command: 'publication\.publish'/);
  assert.match(publishModal, /getWorkspaceAdapter/);
  assert.match(publishModal, /disabled=\{!canPublish \|\| busy\}/);
});

test("connector setup does not render hardcoded discovery success", () => {
  assert.doesNotMatch(addData, /Schema \/ 目录结构发现成功|解析了 12 个有效数据表\/文档|数据类型探断完成，均支持自动同步/);
  assert.match(addData, /source-golden\.connection\.create/);
  assert.match(addData, /source-golden\.ingest/);
});

test("new v2.15.2 views are typed ViewModel gated and use repository-owned icons", () => {
  assert.doesNotMatch(sop, /from ['"]lucide-react['"]/);
  assert.doesNotMatch(monitoring, /from ['"]lucide-react['"]/);
  assert.match(sop, /SopViewModel/);
  assert.match(sop, /activeSkillViewRevision/);
  assert.match(sop, /SOP_VIEW_MODEL_TEMPLATE/);
  assert.match(monitoring, /MonitoringViewModel/);
  assert.match(monitoring, /activeSkillViewRevision/);
  assert.match(monitoring, /MONITORING_VIEW_MODEL_TEMPLATE/);
});

test("typed Skill visual forms stay ViewModel-driven", () => {
  assert.match(dashboard, /activeSkillViewRevision/);
  assert.match(dashboard, /TrustedHtmlArtifactRenderer/);
  assert.match(semantic, /getSemanticModel|SemanticViewModel/);
  assert.match(graph, /getGraphProjection|GraphOntologyViewModel/);
  assert.doesNotMatch(fixture.states.map((state) => state.serverObject).join("\n"), /蓝牙|海底捞|LS6|1,245|tr_89112/);
});

test("generated Skill templates use trusted HTML revision as the main view", () => {
  assert.match(mainArea, /SkillHtmlRevisionView/);
  assert.match(mainArea, /HTML_PRIMARY_TEMPLATES/);
  for (const template of [
    "dashboard",
    "chart",
    "semantic",
    "sop",
    "knowledge",
    "graph_ontology",
    "monitoring",
    "html",
  ]) {
    assert.match(mainArea, new RegExp(template.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(skillHtmlRevision, /TrustedHtmlArtifactRenderer/);
  assert.match(skillHtmlRevision, /artifact\.export/);
  assert.match(skillHtmlRevision, /refresh\.run/);
  assert.match(skillHtmlRevision, /高级详情|审计/);
  assert.match(skillHtmlRevision, /等待服务端返回 HTML ViewRevision/);
  assert.doesNotMatch(skillHtmlRevision, /from ['"]lucide-react['"]/);
  assert.doesNotMatch(skillHtmlRevision, /蓝牙|海底捞|LS6|LS7|1,245|98\.2%|1\.4s|setTimeout|setInterval|localStorage/);
});

test("15-state fixture route ids do not leak into production routing or state", () => {
  const productionSources = [
    host,
    mainArea,
    store,
    tree,
    frozenStore,
    assistant,
    sop,
    monitoring,
    dashboard,
    semantic,
    graph,
    knowledgeBase,
    dataset,
    explore,
    layout,
  ].join("\n");
  for (const routeId of new Set(fixture.states.map((state) => state.routeId))) {
    if (routeId === "welcome") continue;
    assert.doesNotMatch(
      productionSources,
      new RegExp(routeId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
      `${routeId} must remain fixture-only`,
    );
  }
  assert.match(mainArea, /ProductionRouteUnavailable/);
  assert.match(mainArea, /isProductionRouteAvailable\(fileId\)/);
  assert.doesNotMatch(mainArea, /InvalidRouteHandler/);
});
