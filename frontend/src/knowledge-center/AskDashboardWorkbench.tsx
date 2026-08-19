import {
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Clock,
  Code2,
  Copy,
  Database,
  Download,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Share2,
  ShieldCheck,
  Square,
  Table2,
  Wand2,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

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
  askDataToNotebookViewModel,
  capabilityValues,
  dashboardSpec,
  dashboardSpecToByaanViewModel,
  formatJson,
  objectValue,
  rowsFromSpec,
  type ByaanDashboardViewModel,
  type ByaanNotebookViewModel,
} from "./knowledgeWorkbenchUtils";

type DashboardTab = "preview" | "code" | "queries";
type QueryResultTab = "results" | "sql" | "metric" | "policy" | "freshness" | "evidence";

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
  const [activeTab, setActiveTab] = useState<DashboardTab>("preview");
  const [fullscreen, setFullscreen] = useState(false);
  const [busyQuery, setBusyQuery] = useState(false);
  const [busyBuild, setBusyBuild] = useState(false);
  const [error, setError] = useState("");
  const [queryResult, setQueryResult] = useState<AskDataQueryResult | null>(null);
  const [buildResult, setBuildResult] = useState<DashboardSkillBuildResult | null>(null);
  const [splitPercent, setSplitPercent] = useState(38);
  const splitRef = useRef<HTMLDivElement | null>(null);
  const selectedSkill =
    semanticSkills.find((asset) => asset.asset_id === assetId) ?? semanticSkills[0] ?? null;
  const selectedDashboard =
    buildResult?.dashboard ??
    dashboardSkills.find((asset) => asset.asset_id === versionAssetId) ??
    dashboardSkills[0] ??
    null;
  const spec = useMemo(
    () =>
      buildResult?.dashboard ? dashboardSpec(buildResult.dashboard) : dashboardSpec(selectedDashboard),
    [buildResult, selectedDashboard],
  );
  const previewRows = queryResult?.data.rows?.length ? queryResult.data.rows : rowsFromSpec(spec);
  const notebookView = useMemo(
    () => askDataToNotebookViewModel(queryResult, question, busyQuery),
    [queryResult, question, busyQuery],
  );
  const dashboardView = useMemo(
    () => dashboardSpecToByaanViewModel(spec, selectedDashboard),
    [spec, selectedDashboard],
  );
  const metrics = capabilityValues(selectedSkill, "metrics");
  const dimensions = capabilityValues(selectedSkill, "dimensions");
  const latestDashboardJob =
    (buildResult?.job_id ? buildJobs.find((job) => job.id === buildResult.job_id) : null) ??
    buildJobs.find((job) => job.job_type.includes("dashboard") && job.asset_id === selectedDashboard?.asset_id) ??
    buildJobs.find((job) => job.job_type.includes("dashboard")) ??
    null;
  const askDashboardStatus = askDashboardStatusModel({
    selectedSkill,
    selectedDashboard,
    latestDashboardJob,
    queryResult,
    buildResult,
  });

  useEffect(() => {
    setAssetId((current) => current || semanticSkills[0]?.asset_id || "");
  }, [semanticSkills]);

  useEffect(() => {
    setVersionAssetId((current) => current || dashboardSkills[0]?.asset_id || "");
  }, [dashboardSkills]);

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSkill) {
      setError("需要先发布 Semantic Skill。");
      return;
    }
    setBusyQuery(true);
    setError("");
    try {
      const payload = await queryAskData({
        semantic_asset_id: selectedSkill.asset_id,
        metric: metric || undefined,
        dimensions: dimension ? [dimension] : [],
        question: question || undefined,
        limit: 100,
      });
      setQueryResult(payload);
      setActiveTab("queries");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AskTable 查询失败。");
    } finally {
      setBusyQuery(false);
    }
  }

  async function submitDashboard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSkill) {
      setError("需要先发布 Semantic Skill。");
      return;
    }
    setBusyBuild(true);
    setError("");
    try {
      const payload = await buildDashboardSkill({
        space_id: activeSpace?.id,
        semantic_asset_id: selectedSkill.asset_id,
        name: dashboardName,
        intent: dashboardIntent || question,
        metric: metric || undefined,
        dimensions: dimension ? [dimension] : [],
        publish: true,
      });
      setBuildResult(payload);
      setVersionAssetId(payload.dashboard_asset_id);
      setQueryResult(payload.askdata ?? queryResult);
      setActiveTab("preview");
      await onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成 Dashboard Skill 失败。");
    } finally {
      setBusyBuild(false);
    }
  }

  function updateSplitFromClientX(clientX: number) {
    const rect = splitRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return;
    const next = ((clientX - rect.left) / rect.width) * 100;
    setSplitPercent(Math.min(58, Math.max(28, next)));
  }

  function beginSplitResize(event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    updateSplitFromClientX(event.clientX);
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const move = (moveEvent: PointerEvent) => updateSplitFromClientX(moveEvent.clientX);
    const stop = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", stop);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", stop, { once: true });
  }

  function nudgeSplit(delta: number) {
    setSplitPercent((current) => Math.min(58, Math.max(28, current + delta)));
  }

  if (!semanticSkills.length) {
    return (
      <section className="kc-askdash-workbench is-blocked" data-testid="ask-dashboard-workbench">
        <header className="kc-workbench-toolbar">
          <div>
            <h2>AskTable / Dashboard</h2>
            <span>自然语言问数、查询证据和 dashboard_spec 预览共用同一治理链路</span>
          </div>
          <div className="kc-workbench-toolbar__controls">
            <button type="button" onClick={() => void onRefresh()}>
              <RefreshCw className="kc-native-icon" />
              刷新
            </button>
          </div>
        </header>
        <AskDashboardStatusStrip
          status={{
            jobStatus: "blocked",
            agentStatus: "blocked_no_semantic_skill",
            runnerBackend: "agentkit_governed_rest",
            generationMode: "not_configured",
            blockedReason: "no published Semantic Skill",
          }}
        />
        <section className="kc-askdash-blocked" data-testid="askdashboard-not-configured-blocked" role="status">
          <div className="kc-byaan-query-editor kc-askdash-blocked__editor">
            <div className="kc-asktable-head">
              <Search className="kc-native-icon" />
              <div>
                <h3>Query Editor</h3>
                <span>Blocked: no published Semantic Skill</span>
              </div>
              <span className="kc-byaan-run-state is-blocked">blocked</span>
            </div>
            <div className="kc-byaan-editor-toolbar">
              <label>
                <span>Semantic Skill</span>
                <select disabled>
                  <option>not configured</option>
                </select>
              </label>
              <label>
                <span>Metric</span>
                <select disabled>
                  <option>blocked</option>
                </select>
              </label>
              <label>
                <span>Dimension</span>
                <select disabled>
                  <option>blocked</option>
                </select>
              </label>
            </div>
            <label className="kc-byaan-editor-shell">
              <span>Natural language governed query</span>
              <textarea value="Select a published Semantic Skill before asking governed data questions." disabled readOnly />
              <em>blocked · no model</em>
            </label>
            <div className="kc-byaan-editor-actions">
              <button type="button" disabled>
                <Play className="kc-native-icon" />
                Execute
              </button>
              <button type="button" disabled>
                <Square className="kc-native-icon" />
                Stop
              </button>
            </div>
          </div>
          <section className="kc-query-notebook-empty">
            <Table2 className="kc-native-icon" />
            <strong>需要已发布 Semantic Skill</strong>
            <span>AskTable 和 Dashboard 只通过受治理语义能力查询；当前状态为 blocked，不会伪造 query 或 dashboard 成功。</span>
          </section>
          <section className="kc-dashboard-builder">
            <div className="kc-asktable-head">
              <BarChart3 className="kc-native-icon" />
              <div>
                <h3>Dashboard builder</h3>
                <span>Blocked until a real AskTable query returns evidence</span>
              </div>
            </div>
            <button type="button" disabled>
              <Wand2 className="kc-native-icon" />
              生成 Dashboard Skill
            </button>
          </section>
        </section>
      </section>
    );
  }

  return (
    <section className={`kc-askdash-workbench${fullscreen ? " is-fullscreen" : ""}`} data-testid="ask-dashboard-workbench">
      <header className="kc-workbench-toolbar">
        <div>
          <h2>AskTable / Dashboard</h2>
          <span>自然语言问数、查询证据和 dashboard_spec 预览共用同一治理链路</span>
        </div>
        <div className="kc-workbench-toolbar__controls">
          <select value={versionAssetId} onChange={(event) => setVersionAssetId(event.target.value)}>
            <option value="">Dashboard version</option>
            {dashboardSkills.map((asset) => (
              <option key={asset.asset_id} value={asset.asset_id}>
                {asset.name} · {asset.version || "v1"}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => void onRefresh()}>
            <RefreshCw className="kc-native-icon" />
            刷新
          </button>
          <button type="button" onClick={() => setFullscreen((value) => !value)}>
            <ExternalLink className="kc-native-icon" />
            全屏预览
          </button>
          <button type="button" disabled title="后端导出能力尚未启用">
            <Download className="kc-native-icon" />
            导出
          </button>
          <button type="button" disabled title="分享链接需要后端签名能力">
            <Share2 className="kc-native-icon" />
            分享
          </button>
        </div>
      </header>
      {error ? (
        <div className="kc-workbench-alert" role="alert">
          <AlertCircle className="kc-native-icon" />
          <span>{error}</span>
        </div>
      ) : null}
      <AskDashboardStatusStrip status={askDashboardStatus} />
      <div
        ref={splitRef}
        className="kc-askdash-split"
        style={{ "--kc-askdash-left": `${splitPercent}%` } as CSSProperties}
      >
        <AskTablePanel
          selectedSkill={selectedSkill}
          semanticSkills={semanticSkills}
          assetId={assetId}
          onAssetIdChange={setAssetId}
          metrics={metrics}
          dimensions={dimensions}
          metric={metric}
          dimension={dimension}
          question={question}
          onMetricChange={setMetric}
          onDimensionChange={setDimension}
          onQuestionChange={setQuestion}
          busyQuery={busyQuery}
          busyBuild={busyBuild}
          queryResult={queryResult}
          notebookView={notebookView}
          onQuery={submitQuery}
          dashboardName={dashboardName}
          dashboardIntent={dashboardIntent}
          onDashboardNameChange={setDashboardName}
          onDashboardIntentChange={setDashboardIntent}
          onBuildDashboard={submitDashboard}
        />
        <button
          type="button"
          className="kc-askdash-resizer"
          aria-label="调整 AskTable 和 Dashboard 面板宽度"
          role="separator"
          aria-orientation="vertical"
          aria-valuemin={28}
          aria-valuemax={58}
          aria-valuenow={Math.round(splitPercent)}
          onPointerDown={beginSplitResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") {
              event.preventDefault();
              nudgeSplit(-3);
            }
            if (event.key === "ArrowRight") {
              event.preventDefault();
              nudgeSplit(3);
            }
          }}
        />
        <DashboardPreviewWorkspace
          tab={activeTab}
          onTabChange={setActiveTab}
          spec={spec}
          dashboardView={dashboardView}
          queryResult={queryResult}
          buildResult={buildResult}
          selectedDashboard={selectedDashboard}
          previewRows={previewRows}
        />
      </div>
    </section>
  );
}

type AskDashboardStatusModel = {
  jobStatus: string;
  agentStatus: string;
  runnerBackend: string;
  generationMode: string;
  blockedReason: string;
};

function askDashboardStatusModel({
  selectedSkill,
  selectedDashboard,
  latestDashboardJob,
  queryResult,
  buildResult,
}: {
  selectedSkill: KnowledgeAssetMetadata | null;
  selectedDashboard: KnowledgeAssetMetadata | null;
  latestDashboardJob: KnowledgeAssetBuildJob | null;
  queryResult: AskDataQueryResult | null;
  buildResult: DashboardSkillBuildResult | null;
}): AskDashboardStatusModel {
  const dashboardRuntime = objectValue(selectedDashboard?.capability_package?.runtime);
  const queryExecution = objectValue((queryResult?.data as unknown as Record<string, unknown> | undefined)?.execution);
  const buildOutput = objectValue(latestDashboardJob?.output);
  const blockedReasons = latestDashboardJob?.output?.blocked_reasons;
  const gateBlockers = selectedDashboard?.gate?.blockers;
  return {
    jobStatus: buildResult?.status || latestDashboardJob?.status || queryResult?.status || "idle",
    agentStatus: String(
      buildOutput.agent_status ||
        selectedDashboard?.provenance?.agent_status ||
        selectedSkill?.provenance?.agent_status ||
        "agentkit_native_asktable_dashboard",
    ),
    runnerBackend: String(
      buildOutput.runner_backend ||
        selectedDashboard?.provenance?.runner_backend ||
        dashboardRuntime.transport ||
        (queryExecution.governed_rest ? "agentkit_governed_rest" : "") ||
        "agentkit_governed_rest",
    ),
    generationMode: String(
      buildOutput.generation_mode ||
        buildOutput.askdata_status ||
        queryExecution.mode ||
        selectedDashboard?.capabilities?.generation_mode ||
        selectedSkill?.capabilities?.generation_mode ||
        "governed_semantic_query",
    ),
    blockedReason: String(
      latestDashboardJob?.error?.message ||
        (Array.isArray(blockedReasons) && blockedReasons.length ? blockedReasons.map(String).join(", ") : "") ||
        (Array.isArray(gateBlockers) && gateBlockers.length ? gateBlockers.join(", ") : "") ||
        (queryResult?.status === "blocked" ? queryResult.data.policyDecision?.reason : "") ||
        "none",
    ),
  };
}

function AskDashboardStatusStrip({ status }: { status: AskDashboardStatusModel }) {
  return (
    <div className="kc-agent-status-strip" data-testid="askdashboard-agent-status-strip">
      <StatusChip label="Job" value={status.jobStatus} />
      <StatusChip label="Agent" value={status.agentStatus} />
      <StatusChip label="Runner" value={status.runnerBackend} />
      <StatusChip label="Mode" value={status.generationMode} />
      <StatusChip label="Blocked" value={status.blockedReason} />
    </div>
  );
}

function StatusChip({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <strong>{label}</strong>
      <em>{value}</em>
    </span>
  );
}

export function AskTablePanel({
  selectedSkill,
  semanticSkills,
  assetId,
  onAssetIdChange,
  metrics,
  dimensions,
  metric,
  dimension,
  question,
  onMetricChange,
  onDimensionChange,
  onQuestionChange,
  busyQuery,
  busyBuild,
  queryResult,
  notebookView,
  onQuery,
  dashboardName,
  dashboardIntent,
  onDashboardNameChange,
  onDashboardIntentChange,
  onBuildDashboard,
}: {
  selectedSkill: KnowledgeAssetMetadata | null;
  semanticSkills: KnowledgeAssetMetadata[];
  assetId: string;
  onAssetIdChange: (value: string) => void;
  metrics: string[];
  dimensions: string[];
  metric: string;
  dimension: string;
  question: string;
  onMetricChange: (value: string) => void;
  onDimensionChange: (value: string) => void;
  onQuestionChange: (value: string) => void;
  busyQuery: boolean;
  busyBuild: boolean;
  queryResult: AskDataQueryResult | null;
  notebookView: ByaanNotebookViewModel;
  onQuery: (event: FormEvent<HTMLFormElement>) => void;
  dashboardName: string;
  dashboardIntent: string;
  onDashboardNameChange: (value: string) => void;
  onDashboardIntentChange: (value: string) => void;
  onBuildDashboard: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const [resultTab, setResultTab] = useState<QueryResultTab>("results");
  const queryExecution = objectValue((queryResult?.data as unknown as Record<string, unknown> | undefined)?.execution);
  return (
    <aside className="kc-asktable-panel">
      <form className="kc-asktable-query kc-byaan-query-editor" onSubmit={onQuery}>
        <div className="kc-asktable-head">
          <Search className="kc-native-icon" />
          <div>
            <h3>Query Editor</h3>
            <span>{selectedSkill?.name || "Blocked: no published Semantic Skill"}</span>
          </div>
          <span className={`kc-byaan-run-state is-${notebookView.status}`}>{notebookView.status}</span>
        </div>
        <div className="kc-byaan-editor-toolbar">
          <label>
            <span>Semantic Skill</span>
            <select value={assetId} onChange={(event) => onAssetIdChange(event.target.value)}>
              {semanticSkills.map((asset) => (
                <option key={asset.asset_id} value={asset.asset_id}>
                  {asset.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Metric</span>
            <select value={metric} onChange={(event) => onMetricChange(event.target.value)}>
              <option value="">Agent 选择</option>
              {metrics.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Dimension</span>
            <select value={dimension} onChange={(event) => onDimensionChange(event.target.value)}>
              <option value="">不拆解</option>
              {dimensions.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>
        <label className="kc-byaan-editor-shell">
          <span>Natural language governed query</span>
          <textarea value={question} onChange={(event) => onQuestionChange(event.target.value)} />
          <em>{question.split(/\n/).length} lines · {question.length} chars</em>
        </label>
        <div className="kc-byaan-editor-actions">
          <button type="submit" disabled={busyQuery || !selectedSkill}>
            {busyQuery ? <Loader2 className="kc-native-icon kc-spin" /> : <Play className="kc-native-icon" />}
            Execute
          </button>
          <button type="button" disabled={!busyQuery}>
            <Square className="kc-native-icon" />
            Stop
          </button>
        </div>
      </form>
      {queryResult ? (
        <AskTableNotebookResult result={queryResult} notebookView={notebookView} tab={resultTab} onTabChange={setResultTab} />
      ) : (
        <section className="kc-query-notebook-empty">
          <Database className="kc-native-icon" />
          <strong>Query notebook</strong>
          <span>运行 governed query 后，这里展示结果表、SQL、指标口径、策略、新鲜度和证据。</span>
        </section>
      )}
      <form className="kc-dashboard-builder" onSubmit={onBuildDashboard}>
        <div className="kc-asktable-head">
          <BarChart3 className="kc-native-icon" />
          <div>
            <h3>Dashboard builder</h3>
            <span>基于真实 AskTable 查询证据生成 Skill</span>
          </div>
        </div>
        <label>
          <span>Dashboard 名称</span>
          <input value={dashboardName} onChange={(event) => onDashboardNameChange(event.target.value)} />
        </label>
        <label>
          <span>Dashboard intent</span>
          <textarea value={dashboardIntent} onChange={(event) => onDashboardIntentChange(event.target.value)} />
        </label>
        <button type="submit" disabled={busyBuild || !queryResult}>
          {busyBuild ? <Loader2 className="kc-native-icon kc-spin" /> : <Wand2 className="kc-native-icon" />}
          生成 Dashboard Skill
        </button>
        {queryResult ? (
          <dl className="kc-dashboard-build-evidence">
            <div><dt>Rows</dt><dd>{String(queryResult.data.returnedCount ?? queryResult.data.rows.length)}</dd></div>
            <div><dt>Policy</dt><dd>{String(queryResult.data.policyDecision?.decision || "unknown")}</dd></div>
            <div><dt>Execution</dt><dd>{String(queryExecution.mode || "governed")}</dd></div>
          </dl>
        ) : null}
      </form>
    </aside>
  );
}

function AskTableStatusBar({
  result,
  notebookView,
}: {
  result: AskDataQueryResult;
  notebookView: ByaanNotebookViewModel;
}) {
  return (
    <section className={`kc-query-status-bar is-${result.status}`}>
      <div>
        <span className={`kc-native-badge ${result.status === "completed" ? "is-success" : "is-danger"}`}>
          {result.status}
        </span>
        <strong>{String(notebookView.returnedCount)} rows</strong>
        <em><Clock className="kc-native-icon" /> {notebookView.executionTime} ms</em>
      </div>
      <dl>
        <div><dt>Policy</dt><dd>{String(notebookView.policyDecision.decision || "unknown")}</dd></div>
        <div><dt>Freshness</dt><dd>{String(notebookView.freshness.status || "unknown")}</dd></div>
        <div><dt>Agent</dt><dd>{String((result as { agent_status?: string }).agent_status || "unknown")}</dd></div>
      </dl>
    </section>
  );
}

function AskTableNotebookResult({
  result,
  notebookView,
  tab,
  onTabChange,
}: {
  result: AskDataQueryResult;
  notebookView: ByaanNotebookViewModel;
  tab: QueryResultTab;
  onTabChange: (value: QueryResultTab) => void;
}) {
  const tabs: Array<{ id: QueryResultTab; label: string }> = [
    { id: "results", label: "Results" },
    { id: "sql", label: "SQL" },
    { id: "metric", label: "Metric" },
    { id: "policy", label: "Policy" },
    { id: "freshness", label: "Freshness" },
    { id: "evidence", label: "Evidence" },
  ];
  return (
    <section className="kc-query-notebook" data-testid="asktable-query-notebook">
      <AskTableStatusBar result={result} notebookView={notebookView} />
      <div className="kc-query-tabs" role="tablist" aria-label="AskTable query results">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? "is-active" : ""}
            onClick={() => onTabChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="kc-query-tabpanel">
        {tab === "results" ? (
          <ResultTable rows={notebookView.rows} dense />
        ) : tab === "sql" ? (
          <pre><code>{notebookView.sql || "-- no SQL executed"}</code></pre>
        ) : tab === "metric" ? (
          <pre><code>{formatJson(notebookView.metricDefinition)}</code></pre>
        ) : tab === "policy" ? (
          <pre><code>{formatJson(notebookView.policyDecision)}</code></pre>
        ) : tab === "freshness" ? (
          <pre><code>{formatJson(notebookView.freshness)}</code></pre>
        ) : (
          <pre><code>{formatJson({ evidence: notebookView.evidence, lineage: notebookView.lineage })}</code></pre>
        )}
      </div>
    </section>
  );
}

export function DashboardPreviewWorkspace({
  tab,
  onTabChange,
  spec,
  dashboardView,
  queryResult,
  buildResult,
  selectedDashboard,
  previewRows,
}: {
  tab: DashboardTab;
  onTabChange: (value: DashboardTab) => void;
  spec: Record<string, unknown>;
  dashboardView: ByaanDashboardViewModel;
  queryResult: AskDataQueryResult | null;
  buildResult: DashboardSkillBuildResult | null;
  selectedDashboard: KnowledgeAssetMetadata | null;
  previewRows: Array<Record<string, unknown>>;
}) {
  return (
    <section className="kc-dashboard-workspace">
      <div className="kc-dashboard-tabs" role="tablist" aria-label="Dashboard preview tabs">
        {(["preview", "code", "queries"] as const).map((item) => (
          <button key={item} type="button" className={tab === item ? "is-active" : ""} onClick={() => onTabChange(item)}>
            {item === "preview" ? <BarChart3 className="kc-native-icon" /> : item === "code" ? <Code2 className="kc-native-icon" /> : <ShieldCheck className="kc-native-icon" />}
            {item === "preview" ? "Preview" : item === "code" ? "Code" : "Queries"}
          </button>
        ))}
      </div>
      {tab === "preview" ? (
        <DashboardPreview spec={spec} dashboardView={dashboardView} rows={previewRows} selectedDashboard={selectedDashboard} />
      ) : tab === "code" ? (
        <DashboardCodePanel spec={spec} buildResult={buildResult} selectedDashboard={selectedDashboard} />
      ) : (
        <DashboardQueryEvidencePanel queryResult={queryResult} spec={spec} />
      )}
    </section>
  );
}

function DashboardPreview({
  spec,
  dashboardView,
  rows,
  selectedDashboard,
}: {
  spec: Record<string, unknown>;
  dashboardView: ByaanDashboardViewModel;
  rows: Array<Record<string, unknown>>;
  selectedDashboard: KnowledgeAssetMetadata | null;
}) {
  const tiles = dashboardView.tiles;
  const filters = dashboardView.filters;
  const dataViews = dashboardView.dataViews;
  return (
    <div className="kc-dashboard-preview-pane" data-testid="dashboard-preview-pane">
      <header>
        <div>
          <h3>{dashboardView.title || String(spec.title || selectedDashboard?.name || "Dashboard preview")}</h3>
          <span>{dashboardView.description}</span>
        </div>
        <span className="kc-native-badge is-success">
          <CheckCircle2 className="kc-native-icon" />
          governed
        </span>
      </header>
      <div className="kc-dashboard-filterbar">
        {filters.length ? filters.map((filter, index) => (
          <span key={index}>{String(objectValue(filter).label || objectValue(filter).id || "filter")}</span>
        )) : <span>All filters</span>}
      </div>
      <div className="kc-dashboard-tiles">
        {tiles.length ? tiles.map((tile, index) => {
          const record = objectValue(tile);
          const tileType = String(record.type || "tile").toLowerCase();
          return (
            <article key={String(record.id || index)} className={`is-${tileType}`}>
              <span>{tileType}</span>
              <strong>{String(record.title || record.id || "KPI")}</strong>
              <small>{String(record.data_view_id || "primary_metric")}</small>
              {tileType.includes("chart") || tileType.includes("bar") || tileType.includes("line") ? <DashboardSparkline rows={rows} /> : null}
            </article>
          );
        }) : (
          <article>
            <span>kpi</span>
            <strong>{rows[0] ? Object.values(rows[0]).join(" · ") : "等待查询结果"}</strong>
            <small>primary_metric</small>
          </article>
        )}
      </div>
      <div className="kc-dashboard-data-views">
        {dataViews.slice(0, 4).map((view, index) => {
          const record = objectValue(view);
          return (
            <section key={String(record.id || index)}>
              <strong>{String(record.title || record.name || record.id || `view_${index + 1}`)}</strong>
              <span>{String(record.metric || record.metric_id || record.kind || "governed data view")}</span>
            </section>
          );
        })}
      </div>
      <ResultTable rows={rows} />
    </div>
  );
}

function DashboardSparkline({ rows }: { rows: Array<Record<string, unknown>> }) {
  const values = rows
    .slice(0, 8)
    .map((row) => Object.values(row).find((value) => typeof value === "number"))
    .filter((value): value is number => typeof value === "number");
  const bars = values.length ? values : [8, 14, 11, 18, 16, 22];
  const max = Math.max(...bars, 1);
  return (
    <div className="kc-dashboard-sparkline" aria-hidden="true">
      {bars.map((value, index) => (
        <span key={index} style={{ height: `${Math.max(14, (value / max) * 100)}%` }} />
      ))}
    </div>
  );
}

function DashboardCodePanel({
  spec,
  buildResult,
  selectedDashboard,
}: {
  spec: Record<string, unknown>;
  buildResult: DashboardSkillBuildResult | null;
  selectedDashboard: KnowledgeAssetMetadata | null;
}) {
  const artifacts = objectValue(selectedDashboard?.capability_package?.artifacts);
  return (
    <div className="kc-dashboard-code-pane">
      <header>
        <strong>dashboard_spec.json</strong>
        <button type="button" disabled title="复制需要浏览器剪贴板权限">
          <Copy className="kc-native-icon" />
          Copy
        </button>
      </header>
      <pre><code>{formatJson(spec)}</code></pre>
      <section>
        <h3>Artifacts</h3>
        <ul>
          {Object.keys(artifacts).slice(0, 8).map((key) => (
            <li key={key}>{key}</li>
          ))}
          {buildResult ? <li>job_id: {buildResult.job_id}</li> : null}
        </ul>
      </section>
    </div>
  );
}

export function DashboardQueryEvidencePanel({
  queryResult,
  spec,
}: {
  queryResult: AskDataQueryResult | null;
  spec: Record<string, unknown>;
}) {
  const data = queryResult?.data;
  const views = Array.isArray(spec.data_views) ? spec.data_views : [];
  return (
    <div className="kc-dashboard-query-pane" data-testid="dashboard-query-evidence-panel">
      <EvidenceBlock title="SQL" value={data?.sql || String(objectValue(views[0]).sql || "") || "-- run AskTable query"} />
      <EvidenceBlock title="metricDefinition" value={formatJson(data?.metricDefinition ?? objectValue(views[0]).metricDefinition)} />
      <EvidenceBlock title="policyDecision" value={formatJson(data?.policyDecision ?? objectValue(views[0]).policyDecision)} />
      <EvidenceBlock title="freshness" value={formatJson(data?.freshness ?? objectValue(views[0]).freshness)} />
      <EvidenceBlock title="lineage" value={formatJson(data?.lineage ?? objectValue(views[0]).lineage)} />
      <EvidenceBlock title="evidence" value={formatJson(data?.evidence ?? objectValue(views[0]).evidence)} />
      <EvidenceBlock title="rows / elapsed / errors" value={formatJson({
        rows: data?.returnedCount ?? queryResult?.data.rows.length ?? 0,
        execution: objectValue((data as unknown as Record<string, unknown> | undefined)?.execution),
        error: queryResult?.status === "blocked" ? data?.policyDecision?.reason : "",
      })} />
    </div>
  );
}

function EvidenceBlock({ title, value }: { title: string; value: string }) {
  return (
    <section>
      <h3>{title}</h3>
      <pre><code>{value}</code></pre>
    </section>
  );
}

function ResultTable({ rows, dense = false }: { rows: Array<Record<string, unknown>>; dense?: boolean }) {
  const columns = Object.keys(rows[0] ?? {}).slice(0, 8);
  if (!rows.length || !columns.length) {
    return (
      <div className="kc-result-empty">
        <Table2 className="kc-native-icon" />
        <span>暂无数据行</span>
      </div>
    );
  }
  return (
    <div className={`kc-result-table${dense ? " is-dense" : ""}`}>
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 20).map((row, index) => (
            <tr key={index}>
              {columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
