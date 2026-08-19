import { AlertCircle } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  buildDashboardSkill,
  queryAskData,
  type AskDataQueryResult,
  type DashboardSkillBuildResult,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSpace,
} from "../adk/knowledgeAssets";
import {
  byaanBlockedStatus,
  createByaanAskTableSourcePortViewModel,
} from "../features/knowledge-assets/adapters/byaanAskTableAdapter";
import {
  ByaanBlockedNotebookShell,
  ByaanNotebookDashboardSourcePort,
  type ByaanDashboardTab,
} from "../features/knowledge-assets/source-ports/byaan/ByaanNotebookDashboardSourcePort";

export function AskDashboardWorkbench({
  activeSpace,
  semanticSkills,
  dashboardSkills,
  buildJobs,
  onRefresh,
}: {
  activeSpace: KnowledgeAssetSpace | null;
  semanticSkills: KnowledgeAssetMetadata[];
  dashboardSkills: KnowledgeAssetMetadata[];
  buildJobs: KnowledgeAssetBuildJob[];
  onRefresh: () => void | Promise<void>;
}) {
  const [assetId, setAssetId] = useState(semanticSkills[0]?.asset_id || "");
  const [metric, setMetric] = useState("");
  const [dimension, setDimension] = useState("");
  const [question, setQuestion] = useState("按门店查看最近销售票数");
  const [dashboardName, setDashboardName] = useState("语义指标看板");
  const [dashboardIntent, setDashboardIntent] = useState("展示核心指标、维度拆解和策略证据");
  const [versionAssetId, setVersionAssetId] = useState(dashboardSkills[0]?.asset_id || "");
  const [activeTab, setActiveTab] = useState<ByaanDashboardTab>("dashboard");
  const [fullscreen, setFullscreen] = useState(false);
  const [busyQuery, setBusyQuery] = useState(false);
  const [busyBuild, setBusyBuild] = useState(false);
  const [error, setError] = useState("");
  const [queryResult, setQueryResult] = useState<AskDataQueryResult | null>(null);
  const [buildResult, setBuildResult] = useState<DashboardSkillBuildResult | null>(null);

  const viewModel = useMemo(
    () =>
      createByaanAskTableSourcePortViewModel({
        semanticSkills,
        dashboardSkills,
        buildJobs,
        selectedSemanticAssetId: assetId,
        selectedDashboardAssetId: versionAssetId,
        question,
        busyQuery,
        queryResult,
        buildResult,
      }),
    [
      assetId,
      buildJobs,
      buildResult,
      busyQuery,
      dashboardSkills,
      queryResult,
      question,
      semanticSkills,
      versionAssetId,
    ],
  );

  useEffect(() => {
    setAssetId((current) => current || semanticSkills[0]?.asset_id || "");
  }, [semanticSkills]);

  useEffect(() => {
    setVersionAssetId((current) => current || dashboardSkills[0]?.asset_id || "");
  }, [dashboardSkills]);

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!viewModel.selectedSkill) {
      setError("需要先发布 Semantic Skill。");
      return;
    }
    setBusyQuery(true);
    setError("");
    try {
      const payload = await queryAskData({
        semantic_asset_id: viewModel.selectedSkill.asset_id,
        metric: metric || undefined,
        dimensions: dimension ? [dimension] : [],
        question: question || undefined,
        limit: 100,
      });
      setQueryResult(payload);
      setActiveTab("data");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AskTable 查询失败。");
    } finally {
      setBusyQuery(false);
    }
  }

  async function submitDashboard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!viewModel.selectedSkill) {
      setError("需要先发布 Semantic Skill。");
      return;
    }
    setBusyBuild(true);
    setError("");
    try {
      const payload = await buildDashboardSkill({
        space_id: activeSpace?.id,
        semantic_asset_id: viewModel.selectedSkill.asset_id,
        name: dashboardName,
        intent: dashboardIntent || question,
        metric: metric || undefined,
        dimensions: dimension ? [dimension] : [],
        publish: true,
      });
      setBuildResult(payload);
      setVersionAssetId(payload.dashboard_asset_id);
      setQueryResult(payload.askdata ?? queryResult);
      setActiveTab("dashboard");
      await onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成 Dashboard Skill 失败。");
    } finally {
      setBusyBuild(false);
    }
  }

  if (!semanticSkills.length) {
    return (
      <section className="kc-askdash-workbench is-blocked">
        <ByaanBlockedNotebookShell status={byaanBlockedStatus()} onRefresh={() => void onRefresh()} />
      </section>
    );
  }

  return (
    <section className={`kc-askdash-workbench${fullscreen ? " is-fullscreen" : ""}`} data-testid="ask-dashboard-workbench">
      {error ? (
        <div className="kc-workbench-alert" role="alert">
          <AlertCircle className="kc-native-icon" />
          <span>{error}</span>
        </div>
      ) : null}
      <ByaanNotebookDashboardSourcePort
        viewModel={viewModel}
        semanticSkills={semanticSkills}
        selectedSemanticAssetId={assetId}
        onSemanticAssetChange={setAssetId}
        dashboardAssetId={versionAssetId}
        onDashboardAssetChange={setVersionAssetId}
        dashboardSkills={dashboardSkills}
        metric={metric}
        dimension={dimension}
        question={question}
        onMetricChange={setMetric}
        onDimensionChange={setDimension}
        onQuestionChange={setQuestion}
        onQuery={submitQuery}
        busyQuery={busyQuery}
        busyBuild={busyBuild}
        queryResult={queryResult}
        buildResult={buildResult}
        dashboardName={dashboardName}
        dashboardIntent={dashboardIntent}
        onDashboardNameChange={setDashboardName}
        onDashboardIntentChange={setDashboardIntent}
        onBuildDashboard={submitDashboard}
        activeTab={activeTab}
        onActiveTabChange={setActiveTab}
        onRefresh={() => void onRefresh()}
        onFullscreen={() => setFullscreen((value) => !value)}
      />
    </section>
  );
}
