import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../src/knowledge-workspace/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const layout = read("frozen-ui/components/Layout/WorkspaceLayout.tsx");
const mainArea = read("frozen-ui/components/Layout/MainAreaPane.tsx");
const tree = read("frozen-ui/components/Layout/FileTreePane.tsx");
const nav = read("frozen-ui/components/Layout/TopNav.tsx");
const journey = read("frozen-ui/components/MainArea/JourneyDetailView.tsx");
const drawer = read("frozen-ui/components/Layout/BuildDetailsDrawer.tsx");
const telemetry = read("frozen-ui/components/Layout/shellTelemetry.ts");
const matrix = JSON.parse(
  readFileSync(
    new URL("../../tests/fixtures/knowledge_step3_w4/capability-matrix.json", import.meta.url),
    "utf8",
  ),
);

test("home is a single central Composer and does not persist demo completion state", () => {
  assert.equal(
    layout.match(/<HomeComposer\b/g)?.length,
    2,
    "desktop and mobile home must share the same central Composer",
  );
  assert.doesNotMatch(layout, /demo_(published|reused|chat_chips|workspace_empty)/);
  assert.match(read("frozen-ui/components/Layout/HomeComposer.tsx"), /你想把哪些数据或知识加工成什么能力/);
});

test("personal and team navigation expose exactly the three lifecycle roots", () => {
  for (const source of [tree]) {
    assert.match(source, /数据与知识/);
    assert.match(source, /Skill 草稿/);
    assert.match(source, /已发布 Skill/);
    assert.doesNotMatch(source, /分析与看板|语义与 Skill|知识与图谱/);
  }
});

test("evaluation is only reachable from the More menu", () => {
  assert.match(tree, /workspace_menu_more_click/);
  assert.match(tree, /验收与评测/);
  assert.doesNotMatch(nav, /workspace_menu_more_click|验收与评测/);
  assert.doesNotMatch(nav, /打开验收入口/);
});

test("the review acceptance drawer is reachable as the v212 entry route", () => {
  assert.equal(matrix.newRouteCount, 43);
  assert.match(layout, /modal === ['"]v212_entry['"]/);
  assert.match(layout, /V212EntryDrawer/);
  const entryDrawer = read("frozen-ui/components/Layout/V212EntryDrawer.tsx");
  assert.match(entryDrawer, /aria-label="验收入口"/);
  assert.match(entryDrawer, /进入企业知识旅程/);
});

test("unknown Capability Matrix artifact routes keep a gated deep link instead of falling back to home", () => {
  assert.match(mainArea, /ProductionRouteUnavailable/);
  assert.match(mainArea, /isProductionRouteAvailable\(fileId\)/);
  assert.doesNotMatch(mainArea, /res_dash_east/);
  assert.doesNotMatch(mainArea, /set\('file', 'welcome'\)/);
});

test("journey stages are server-derived and expose one primary CTA", () => {
  assert.match(journey, /stageFromReadModel/);
  assert.match(journey, /telemetryEnabled = true/);
  assert.match(journey, /stageFromReadModel\(operation\) \?\? stageFromReadModel\(serverModel\)/);
  assert.match(journey, /!currentStage/);
  assert.match(journey, /当前状态由服务端 read model 确认/);
  assert.match(journey, /disabled=\{busy \|\| isBlocked\}/);
  assert.match(journey, /构建详情/);
  assert.doesNotMatch(journey, /stageLabels\.map/);
  assert.doesNotMatch(journey, /onClick=\{\(\) => setStep/);
});

test("build details preserves the eight task labels and server statuses", () => {
  for (const label of ["添加数据或知识", "自动检查与清洗", "可信数据版本", "定义 Agent 能力", "预览与调试", "质量检查", "发布门禁", "发布给 Agent"]) {
    assert.match(drawer, new RegExp(label));
  }
  assert.match(drawer, /readModel/);
  assert.match(drawer, /readModelRetryable/);
  assert.match(drawer, /构建任务错误/);
  assert.match(drawer, /重试构建任务/);
  assert.match(drawer, /aria-expanded=\{isOpen\}/);
});

test("auth errors block actions and render errors stay in Artifact", () => {
  assert.match(layout, /searchParams\.get\('error_state'\)/);
  assert.match(mainArea, /errorState=\{errorState\}/);
  assert.match(journey, /errorState === "auth_failed"/);
  assert.match(journey, /errorState === "render_error"/);
  assert.match(journey, /skill_auth_error_shown/);
  assert.match(journey, /修复凭证/);
  assert.match(journey, /skill_debug_render_error_shown/);
  assert.match(journey, /class ArtifactBoundary extends React\.Component/);
  assert.match(journey, /ControlledArtifact/);
  assert.match(journey, /Artifact 渲染错误/);
  assert.match(journey, /skill_schema_drift_warning_shown/);
  assert.match(telemetry, /trackShellEventOnce/);
  assert.match(journey, /error_type: String\(effectiveModel\?\.renderErrorType/);
  assert.match(journey, /error_type: "artifact_boundary"/);
});

test("declares and emits all thirteen required shell events", () => {
  const events = [
    "workspace_home_view",
    "workspace_menu_more_click",
    "skill_draft_view",
    "skill_primary_cta_click",
    "skill_build_detail_drawer_open",
    "skill_auth_error_shown",
    "skill_debug_view",
    "skill_debug_render_error_shown",
    "skill_eval_view",
    "skill_publish_submit",
    "skill_published_view",
    "skill_simulate_call_click",
    "skill_schema_drift_warning_shown",
  ];
  for (const event of events) {
    assert.match(telemetry, new RegExp(event));
  }
  assert.equal(events.length, 13);
});
