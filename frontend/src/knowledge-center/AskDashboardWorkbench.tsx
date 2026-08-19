import {
  AlertCircle,
  ArrowUp,
  BarChart3,
  Bot,
  CheckCircle2,
  Code2,
  Database,
  GripVertical,
  LayoutDashboard,
  Loader2,
  Maximize2,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Table2,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import {
  streamAskData,
  type AskDataQueryResult,
  type DashboardSkillBuildResult,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSpace,
} from "../adk/knowledgeAssets";
import { parseSSE } from "../adk/sse";
import { applyEvent, emptyAcc, type Acc, type Block } from "../blocks";
import { Blocks } from "../ui/Blocks";
import {
  askDataToNotebookViewModel,
  capabilityValues,
  dashboardSpec,
  dashboardSpecToByaanViewModel,
  formatJson,
  objectValue,
  rowsFromSpec,
} from "./knowledgeWorkbenchUtils";

type PreviewTab = "preview" | "queries" | "lineage" | "code";
type MobilePane = "answer" | "preview";

type QueryRound = {
  id: string;
  question: string;
  status: "running" | "completed" | "blocked" | "error";
  result: AskDataQueryResult | null;
  acc: Acc;
  blocks: Block[];
  conversationId?: string;
  sessionId?: string;
  error?: string;
};

type NotebookStatus = {
  jobStatus: string;
  agentStatus: string;
  runnerBackend: string;
  generationMode: string;
  blockedReason: string;
};

const fallbackExamples = [
  "按门店查看最近销售票数",
  "过去 30 天核心指标趋势如何？",
  "哪些区域的转化率下降最明显？",
  "列出异常波动，并给出 SQL 和口径证据",
];

export function AskDashboardWorkbench({
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
  const [question, setQuestion] = useState("");
  const [dashboardName, setDashboardName] = useState("语义指标看板");
  const [dashboardIntent, setDashboardIntent] = useState("");
  const [versionAssetId, setVersionAssetId] = useState(dashboardSkills[0]?.asset_id || "");
  const [previewTab, setPreviewTab] = useState<PreviewTab>("preview");
  const [mobilePane, setMobilePane] = useState<MobilePane>("answer");
  const [splitPercent, setSplitPercent] = useState(58);
  const [isDragging, setIsDragging] = useState(false);
  const splitRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [busyQuery, setBusyQuery] = useState(false);
  const [busyBuild, setBusyBuild] = useState(false);
  const [error, setError] = useState("");
  const [queryResult, setQueryResult] = useState<AskDataQueryResult | null>(null);
  const [buildResult, setBuildResult] = useState<DashboardSkillBuildResult | null>(null);
  const [rounds, setRounds] = useState<QueryRound[]>([]);

  const selectedSkill =
    semanticSkills.find((asset) => asset.asset_id === assetId) ??
    semanticSkills[0] ??
    null;
  const dashboardOptions = useMemo(() => {
    const items = [...dashboardSkills];
    if (buildResult?.dashboard && !items.some((asset) => asset.asset_id === buildResult.dashboard.asset_id)) {
      items.unshift(buildResult.dashboard);
    }
    return items;
  }, [buildResult, dashboardSkills]);
  const selectedDashboard =
    buildResult?.dashboard ??
    dashboardOptions.find((asset) => asset.asset_id === versionAssetId) ??
    dashboardOptions[0] ??
    null;
  const spec = dashboardSpec(selectedDashboard);
  const previewRows = queryResult?.data.rows?.length ? queryResult.data.rows : rowsFromSpec(spec);
  const notebook = askDataToNotebookViewModel(queryResult, rounds.at(-1)?.question || question, busyQuery);
  const dashboard = dashboardSpecToByaanViewModel(spec, selectedDashboard);
  const metrics = capabilityValues(selectedSkill, "metrics");
  const dimensions = capabilityValues(selectedSkill, "dimensions");
  const status = statusModel({
    selectedSkill,
    selectedDashboard,
    latestDashboardJob: latestDashboardJob(buildJobs, selectedDashboard, buildResult),
    queryResult,
    buildResult,
  });
  const examples = useMemo(() => exampleQuestions(metrics, dimensions), [metrics, dimensions]);
  const hasConversation = rounds.length > 0 || busyQuery || Boolean(queryResult);
  const canAsk = Boolean(selectedSkill) && !busyQuery;

  useEffect(() => {
    setAssetId((current) => current || semanticSkills[0]?.asset_id || "");
  }, [semanticSkills]);

  useEffect(() => {
    setVersionAssetId((current) => current || dashboardSkills[0]?.asset_id || "");
  }, [dashboardSkills]);

  useEffect(() => {
    if (dashboardIntent || !rounds.length) return;
    setDashboardIntent(rounds.at(-1)?.question || "");
  }, [dashboardIntent, rounds]);

  useEffect(() => {
    if (!isDragging) return;

    function onPointerMove(event: PointerEvent) {
      const bounds = splitRef.current?.getBoundingClientRect();
      if (!bounds || bounds.width <= 0) return;
      const next = ((event.clientX - bounds.left) / bounds.width) * 100;
      setSplitPercent(Math.min(70, Math.max(44, next)));
    }

    function onPointerUp() {
      setIsDragging(false);
    }

    document.addEventListener("pointermove", onPointerMove);
    document.addEventListener("pointerup", onPointerUp, { once: true });
    return () => {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    };
  }, [isDragging]);

  async function submitQuery(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const trimmed = question.trim();
    if (!selectedSkill) {
      setError("需要先发布 Semantic Skill。");
      return;
    }
    if (!trimmed) {
      setError("请输入要分析的业务问题。");
      return;
    }

    const roundId = `query-${Date.now()}`;
    setBusyQuery(true);
    setError("");
    setQuestion("");
    setMobilePane("answer");
    setRounds((current) => [
      ...current,
      {
        id: roundId,
        question: trimmed,
        status: "running",
        result: null,
        acc: emptyAcc(),
        blocks: [],
      },
    ]);

    try {
      const response = await streamAskData({
        semantic_asset_id: selectedSkill.asset_id,
        message: trimmed,
        metric: metric || undefined,
        dimensions: dimension ? [dimension] : [],
        dashboard_intent: dashboardIntent || trimmed,
        mode: "production",
        limit: 100,
      });
      let acc = emptyAcc();
      let payload: AskDataQueryResult | null = null;
      let conversationId = "";
      let sessionId = "";
      for await (const rawEvent of parseSSE(response)) {
        if (!isAdkEvent(rawEvent)) continue;
        const eventPayload = rawEvent as Record<string, unknown>;
        conversationId = typeof eventPayload.conversation_id === "string" ? eventPayload.conversation_id : conversationId;
        sessionId = typeof eventPayload.session_id === "string" ? eventPayload.session_id : sessionId;
        acc = applyEvent(acc, rawEvent);
        const toolResult = queryResultFromEvent(rawEvent);
        if (toolResult) {
          payload = toolResult;
          setQueryResult(toolResult);
          setDashboardIntent((current) => current || trimmed);
          setPreviewTab(toolResult.status === "blocked" ? "lineage" : "queries");
        }
        const finalStatus =
          payload?.status === "completed"
            ? hasFinalText(acc.blocks) ? "completed" : "running"
            : payload?.status === "blocked"
              ? "blocked"
              : "running";
        setRounds((current) =>
          current.map((round) =>
            round.id === roundId
              ? {
                  ...round,
                  acc,
                  blocks: acc.blocks,
                  status: finalStatus,
                  result: payload,
                  conversationId,
                  sessionId,
                }
              : round,
          ),
        );
      }
      setRounds((current) =>
        current.map((round) =>
          round.id === roundId
            ? {
                ...round,
                status: payload?.status === "completed" ? "completed" : payload?.status === "blocked" ? "blocked" : "error",
                result: payload,
                acc,
                blocks: acc.blocks,
                conversationId,
                sessionId,
                error: payload ? undefined : "AskTable stream ended without a governed query result.",
              }
            : round,
        ),
      );
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "AskTable 查询失败。";
      setError(message);
      setRounds((current) =>
        current.map((round) =>
          round.id === roundId ? { ...round, status: "error", error: message } : round,
        ),
      );
    } finally {
      setBusyQuery(false);
    }
  }

  async function buildDashboardFromLatest(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!selectedSkill) {
      setError("需要先发布 Semantic Skill。");
      return;
    }
    const latestQuestion = rounds.at(-1)?.question || question || dashboardIntent || "展示核心指标、维度拆解和策略证据";
    setBusyBuild(true);
    setError("");
    setMobilePane("preview");
    try {
      const response = await streamAskData({
        semantic_asset_id: selectedSkill.asset_id,
        message: `请基于上一轮 AskTable 证据生成 Dashboard Skill：${dashboardIntent || latestQuestion}`,
        dashboard_intent: dashboardIntent || latestQuestion,
        metric: metric || undefined,
        dimensions: dimension ? [dimension] : [],
        mode: "production",
        limit: 100,
      });
      let acc = emptyAcc();
      let payload: DashboardSkillBuildResult | null = null;
      let askdata: AskDataQueryResult | null = null;
      for await (const rawEvent of parseSSE(response)) {
        if (!isAdkEvent(rawEvent)) continue;
        acc = applyEvent(acc, rawEvent);
        const toolResult = queryResultFromEvent(rawEvent);
        if (toolResult) {
          askdata = toolResult;
          setQueryResult(toolResult);
        }
        const dashboardResult = dashboardResultFromEvent(rawEvent);
        if (dashboardResult) {
          payload = dashboardResult;
        }
      }
      if (!payload) {
        throw new Error("AskTable Agent 未返回 Dashboard Skill 结果。");
      }
      setBuildResult(payload);
      setVersionAssetId(payload.dashboard_asset_id);
      if (payload.askdata || askdata) {
        const result = payload.askdata ?? askdata;
        setQueryResult(result ?? null);
        setRounds((current) => {
          if (!current.length) {
            return [{
              id: `query-${Date.now()}`,
              question: latestQuestion,
              status: result?.status === "completed" ? "completed" : "blocked",
              result: result ?? null,
              acc,
              blocks: acc.blocks,
            }];
          }
          return current.map((round, index) =>
            index === current.length - 1 && !round.result
              ? {
                  ...round,
                  status: result?.status === "completed" ? "completed" : "blocked",
                  result: result ?? null,
                }
              : round,
          );
        });
      }
      setPreviewTab("preview");
      await onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成 Dashboard Skill 失败。");
    } finally {
      setBusyBuild(false);
    }
  }

  if (!hasConversation) {
    return (
      <section
        className={`kc-askdash-workbench kc-askdash-native is-portal${!semanticSkills.length ? " is-blocked" : ""}`}
        data-testid="ask-dashboard-workbench"
      >
        {error ? <WorkbenchAlert message={error} /> : null}
        <PortalTopBar
          semanticSkills={semanticSkills}
          selectedSemanticAssetId={assetId}
          onSemanticAssetChange={setAssetId}
          dashboardSkills={dashboardOptions}
          dashboardAssetId={versionAssetId}
          onDashboardAssetChange={setVersionAssetId}
          onRefresh={() => void onRefresh()}
        />
        <AskTablePortal
          question={question}
          onQuestionChange={setQuestion}
          onSubmit={submitQuery}
          semanticSkills={semanticSkills}
          selectedSemanticAssetId={assetId}
          onSemanticAssetChange={setAssetId}
          metric={metric}
          dimension={dimension}
          metrics={metrics}
          dimensions={dimensions}
          onMetricChange={setMetric}
          onDimensionChange={setDimension}
          examples={examples}
          onExampleSelect={setQuestion}
          disabled={!canAsk}
          busy={busyQuery}
          blocked={!semanticSkills.length}
        />
        {!semanticSkills.length ? (
          <ByaanBlockedNotebookShell status={blockedStatus()} onRefresh={() => void onRefresh()} />
        ) : null}
      </section>
    );
  }

  const workspaceStyle = {
    "--kc-askdash-chat": `${splitPercent}%`,
  } as CSSProperties;

  return (
    <section
      className={`kc-askdash-workbench kc-askdash-native is-workspace${fullscreen ? " is-fullscreen" : ""}`}
      data-testid="ask-dashboard-workbench"
    >
      {error ? <WorkbenchAlert message={error} /> : null}
      <PortalTopBar
        semanticSkills={semanticSkills}
        selectedSemanticAssetId={assetId}
        onSemanticAssetChange={setAssetId}
        dashboardSkills={dashboardOptions}
        dashboardAssetId={versionAssetId}
        onDashboardAssetChange={setVersionAssetId}
        onRefresh={() => void onRefresh()}
      />
      <ByaanStatusStrip status={status} />
      <MobilePaneTabs activePane={mobilePane} onPaneChange={setMobilePane} />
      <div
        ref={splitRef}
        className={`kc-askdash-notebook-shell is-mobile-${mobilePane}`}
        style={workspaceStyle}
      >
        <section className="kc-askdash-chat-area">
          <div className="kc-askdash-message-list">
            <AssistantIntro selectedSkill={selectedSkill} />
            {rounds.map((round) => (
              <QueryRoundView
                key={round.id}
                round={round}
                onBuildDashboard={buildDashboardFromLatest}
                busyBuild={busyBuild}
                onOpenPreview={() => {
                  setMobilePane("preview");
                  setPreviewTab("preview");
                }}
              />
            ))}
          </div>
          <AskComposer
            question={question}
            onQuestionChange={setQuestion}
            onSubmit={submitQuery}
            semanticSkills={semanticSkills}
            selectedSemanticAssetId={assetId}
            onSemanticAssetChange={setAssetId}
            metric={metric}
            dimension={dimension}
            metrics={metrics}
            dimensions={dimensions}
            onMetricChange={setMetric}
            onDimensionChange={setDimension}
            disabled={!canAsk}
            busy={busyQuery}
            compact
          />
        </section>
        <button
          type="button"
          className="kc-askdash-resize-handle"
          aria-label="Resize notebook preview"
          onPointerDown={() => setIsDragging(true)}
        >
          <GripVertical className="kc-native-icon" />
        </button>
        <DashboardNotebookPreview
          previewTab={previewTab}
          onPreviewTabChange={setPreviewTab}
          selectedDashboard={selectedDashboard}
          dashboardName={dashboardName}
          onDashboardNameChange={setDashboardName}
          dashboardIntent={dashboardIntent}
          onDashboardIntentChange={setDashboardIntent}
          dashboard={dashboard}
          spec={spec}
          queryResult={queryResult}
          notebook={notebook}
          rows={previewRows}
          busyBuild={busyBuild}
          onBuildDashboard={buildDashboardFromLatest}
          onRefresh={() => void onRefresh()}
          onFullscreen={() => setFullscreen((value) => !value)}
        />
      </div>
    </section>
  );
}

function PortalTopBar({
  semanticSkills,
  selectedSemanticAssetId,
  onSemanticAssetChange,
  dashboardSkills,
  dashboardAssetId,
  onDashboardAssetChange,
  onRefresh,
}: {
  semanticSkills: KnowledgeAssetMetadata[];
  selectedSemanticAssetId: string;
  onSemanticAssetChange: (value: string) => void;
  dashboardSkills: KnowledgeAssetMetadata[];
  dashboardAssetId: string;
  onDashboardAssetChange: (value: string) => void;
  onRefresh: () => void;
}) {
  return (
    <header className="kc-askdash-topbar">
      <div className="kc-askdash-brand">
        <BarChart3 className="kc-native-icon" />
        <span>
          <strong>AskTable / Dashboard</strong>
          <small>AskData notebook workspace</small>
        </span>
      </div>
      <div className="kc-askdash-topbar-actions">
        <select
          aria-label="Semantic Skill"
          value={selectedSemanticAssetId}
          onChange={(event) => onSemanticAssetChange(event.target.value)}
          disabled={!semanticSkills.length}
        >
          {semanticSkills.length ? null : <option value="">No Semantic Skill</option>}
          {semanticSkills.map((asset) => (
            <option key={asset.asset_id} value={asset.asset_id}>
              {asset.name} · {asset.version || "v1"}
            </option>
          ))}
        </select>
        {dashboardSkills.length ? (
          <select
            aria-label="Dashboard Skill"
            value={dashboardAssetId}
            onChange={(event) => onDashboardAssetChange(event.target.value)}
          >
            <option value="">Latest dashboard</option>
            {dashboardSkills.map((asset) => (
              <option key={asset.asset_id} value={asset.asset_id}>
                {asset.name} · {asset.version || "v1"}
              </option>
            ))}
          </select>
        ) : null}
        <button type="button" onClick={onRefresh}>
          <RefreshCw className="kc-native-icon" />
          Refresh
        </button>
      </div>
    </header>
  );
}

function AskTablePortal({
  question,
  onQuestionChange,
  onSubmit,
  semanticSkills,
  selectedSemanticAssetId,
  onSemanticAssetChange,
  metric,
  dimension,
  metrics,
  dimensions,
  onMetricChange,
  onDimensionChange,
  examples,
  onExampleSelect,
  disabled,
  busy,
  blocked,
}: {
  question: string;
  onQuestionChange: (value: string) => void;
  onSubmit: (event?: FormEvent<HTMLFormElement>) => void;
  semanticSkills: KnowledgeAssetMetadata[];
  selectedSemanticAssetId: string;
  onSemanticAssetChange: (value: string) => void;
  metric: string;
  dimension: string;
  metrics: string[];
  dimensions: string[];
  onMetricChange: (value: string) => void;
  onDimensionChange: (value: string) => void;
  examples: string[];
  onExampleSelect: (value: string) => void;
  disabled: boolean;
  busy: boolean;
  blocked: boolean;
}) {
  return (
    <div className="kc-askdash-portal-stage" data-asktable-state="portal">
      <div className="kc-askdash-portal-copy">
        <div className="kc-askdash-portal-kicker">
          <Sparkles className="kc-native-icon" />
          Governed AskData notebook
        </div>
        <h1>What do you need to know?</h1>
        <p>
          Ask questions against published Semantic Skills. SQL, metric definitions,
          freshness, lineage, and permission evidence stay attached to every answer.
        </p>
      </div>
      <AskComposer
        question={question}
        onQuestionChange={onQuestionChange}
        onSubmit={onSubmit}
        semanticSkills={semanticSkills}
        selectedSemanticAssetId={selectedSemanticAssetId}
        onSemanticAssetChange={onSemanticAssetChange}
        metric={metric}
        dimension={dimension}
        metrics={metrics}
        dimensions={dimensions}
        onMetricChange={onMetricChange}
        onDimensionChange={onDimensionChange}
        disabled={disabled}
        busy={busy}
        portal
        placeholder={blocked ? "Publish a Semantic Skill before asking data questions" : "Ask a business question about the published metrics..."}
      />
      <div className="kc-askdash-example-chips" aria-label="Example questions">
        {examples.map((example) => (
          <button key={example} type="button" onClick={() => onExampleSelect(example)} disabled={blocked}>
            {example}
          </button>
        ))}
      </div>
      <div className="kc-askdash-portal-facts">
        <span><ShieldCheck className="kc-native-icon" /> Published metrics only</span>
        <span><Code2 className="kc-native-icon" /> SQL evidence included</span>
        <span><LayoutDashboard className="kc-native-icon" /> Dashboard after first answer</span>
      </div>
    </div>
  );
}

function AskComposer({
  question,
  onQuestionChange,
  onSubmit,
  semanticSkills,
  selectedSemanticAssetId,
  onSemanticAssetChange,
  metric,
  dimension,
  metrics,
  dimensions,
  onMetricChange,
  onDimensionChange,
  disabled,
  busy,
  portal = false,
  compact = false,
  placeholder = "Ask a follow-up...",
}: {
  question: string;
  onQuestionChange: (value: string) => void;
  onSubmit: (event?: FormEvent<HTMLFormElement>) => void;
  semanticSkills: KnowledgeAssetMetadata[];
  selectedSemanticAssetId: string;
  onSemanticAssetChange: (value: string) => void;
  metric: string;
  dimension: string;
  metrics: string[];
  dimensions: string[];
  onMetricChange: (value: string) => void;
  onDimensionChange: (value: string) => void;
  disabled: boolean;
  busy: boolean;
  portal?: boolean;
  compact?: boolean;
  placeholder?: string;
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!disabled && question.trim()) onSubmit();
    }
  }

  return (
    <form
      className={`kc-askdash-composer${portal ? " is-portal" : ""}${compact ? " is-compact" : ""}`}
      onSubmit={onSubmit}
    >
      <textarea
        value={question}
        onChange={(event) => onQuestionChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={portal ? 4 : 2}
        disabled={disabled || busy}
      />
      <div className="kc-askdash-composer-toolbar">
        <div className="kc-askdash-composer-controls">
          <select
            aria-label="Semantic Skill"
            value={selectedSemanticAssetId}
            onChange={(event) => onSemanticAssetChange(event.target.value)}
            disabled={!semanticSkills.length || busy}
          >
            {semanticSkills.length ? null : <option value="">No Semantic Skill</option>}
            {semanticSkills.map((asset) => (
              <option key={asset.asset_id} value={asset.asset_id}>{asset.name}</option>
            ))}
          </select>
          <select
            aria-label="Metric"
            value={metric}
            onChange={(event) => onMetricChange(event.target.value)}
            disabled={busy}
          >
            <option value="">Any metric</option>
            {metrics.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select
            aria-label="Dimension"
            value={dimension}
            onChange={(event) => onDimensionChange(event.target.value)}
            disabled={busy}
          >
            <option value="">Any dimension</option>
            {dimensions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </div>
        <button type="submit" className="kc-askdash-send" disabled={disabled || busy || !question.trim()}>
          {busy ? <Loader2 className="kc-native-icon is-spinning" /> : <ArrowUp className="kc-native-icon" />}
        </button>
      </div>
    </form>
  );
}

function AssistantIntro({ selectedSkill }: { selectedSkill: KnowledgeAssetMetadata | null }) {
  return (
    <article className="kc-askdash-message is-assistant">
      <div className="kc-askdash-avatar"><Bot className="kc-native-icon" /></div>
      <div className="kc-askdash-bubble">
        <span className="kc-askdash-role">Agent</span>
        <p>
          {selectedSkill
            ? `Using ${selectedSkill.name}. Ask a question and I will keep the SQL, metric口径, policy, freshness, and lineage evidence available.`
            : "Publish a Semantic Skill before starting an AskTable notebook."}
        </p>
      </div>
    </article>
  );
}

function QueryRoundView({
  round,
  onBuildDashboard,
  busyBuild,
  onOpenPreview,
}: {
  round: QueryRound;
  onBuildDashboard: (event?: FormEvent<HTMLFormElement>) => void;
  busyBuild: boolean;
  onOpenPreview: () => void;
}) {
  return (
    <>
      <article className="kc-askdash-message is-user">
        <div className="kc-askdash-avatar"><MessageSquare className="kc-native-icon" /></div>
        <div className="kc-askdash-bubble">
          <span className="kc-askdash-role">You</span>
          <p>{round.question}</p>
        </div>
      </article>
      <article className="kc-askdash-message is-assistant">
        <div className="kc-askdash-avatar"><Bot className="kc-native-icon" /></div>
        <div className="kc-askdash-bubble">
          <span className={`kc-askdash-answer-state is-${round.status}`}>
            {round.status === "running" ? <Loader2 className="kc-native-icon is-spinning" /> : <CheckCircle2 className="kc-native-icon" />}
            {round.status === "running" ? "Analyzing" : round.status}
          </span>
          {round.error ? (
            <p>{round.error}</p>
          ) : (
            <AskDataStreamAnswer
              round={round}
              onBuildDashboard={onBuildDashboard}
              busyBuild={busyBuild}
              onOpenPreview={onOpenPreview}
            />
          )}
        </div>
      </article>
    </>
  );
}

function AskDataStreamAnswer({
  round,
  onBuildDashboard,
  busyBuild,
  onOpenPreview,
}: {
  round: QueryRound;
  onBuildDashboard: (event?: FormEvent<HTMLFormElement>) => void;
  busyBuild: boolean;
  onOpenPreview: () => void;
}) {
  const result = round.result;
  const completed = result?.status === "completed";
  return (
    <div className="kc-askdash-answer">
      {round.blocks.length ? (
        <Blocks blocks={round.blocks} onAction={() => {}} />
      ) : (
        <p>Running a governed Semantic Skill query and preparing evidence blocks.</p>
      )}
      <div className="kc-askdash-answer-actions">
        <button type="button" onClick={onOpenPreview}>
          <LayoutDashboard className="kc-native-icon" />
          Preview
        </button>
        <button type="button" onClick={() => onBuildDashboard()} disabled={busyBuild || !completed}>
          {busyBuild ? <Loader2 className="kc-native-icon is-spinning" /> : <BarChart3 className="kc-native-icon" />}
          Generate Dashboard
        </button>
      </div>
      {result ? (
        <>
          <EvidenceGrid result={result} />
          <MiniResultTable rows={result.data.rows} />
        </>
      ) : null}
    </div>
  );
}

function EvidenceGrid({ result }: { result: AskDataQueryResult }) {
  const items = [
    { title: "SQL", value: result.data.sql || "-- no SQL returned" },
    { title: "Metric definition", value: formatJson(result.data.metricDefinition ?? result.data.metric) },
    { title: "Permission policy", value: formatJson(result.data.policyDecision) },
    { title: "Freshness", value: formatJson(result.data.freshness) },
    { title: "Evidence", value: formatJson(result.data.evidence ?? []) },
    { title: "Lineage", value: formatJson(result.data.lineage ?? []) },
  ];
  return (
    <div className="kc-askdash-evidence-grid">
      {items.map((item) => (
        <details key={item.title} open={item.title === "SQL" || item.title === "Metric definition"}>
          <summary>{item.title}</summary>
          <pre><code>{item.value}</code></pre>
        </details>
      ))}
    </div>
  );
}

function DashboardNotebookPreview({
  previewTab,
  onPreviewTabChange,
  selectedDashboard,
  dashboardName,
  onDashboardNameChange,
  dashboardIntent,
  onDashboardIntentChange,
  dashboard,
  spec,
  queryResult,
  notebook,
  rows,
  busyBuild,
  onBuildDashboard,
  onRefresh,
  onFullscreen,
}: {
  previewTab: PreviewTab;
  onPreviewTabChange: (tab: PreviewTab) => void;
  selectedDashboard: KnowledgeAssetMetadata | null;
  dashboardName: string;
  onDashboardNameChange: (value: string) => void;
  dashboardIntent: string;
  onDashboardIntentChange: (value: string) => void;
  dashboard: ReturnType<typeof dashboardSpecToByaanViewModel>;
  spec: Record<string, unknown>;
  queryResult: AskDataQueryResult | null;
  notebook: ReturnType<typeof askDataToNotebookViewModel>;
  rows: Array<Record<string, unknown>>;
  busyBuild: boolean;
  onBuildDashboard: (event?: FormEvent<HTMLFormElement>) => void;
  onRefresh: () => void;
  onFullscreen: () => void;
}) {
  const hasDashboard = Boolean(selectedDashboard || dashboard.tiles.length || rows.length);
  return (
    <aside className="kc-askdash-preview-panel" data-testid="dashboard-preview-pane">
      <header className="kc-askdash-preview-toolbar">
        <div className="kc-askdash-preview-tabs">
          <PreviewTabButton active={previewTab === "preview"} onClick={() => onPreviewTabChange("preview")} icon={<LayoutDashboard className="kc-native-icon" />}>Preview</PreviewTabButton>
          <PreviewTabButton active={previewTab === "queries"} onClick={() => onPreviewTabChange("queries")} icon={<Database className="kc-native-icon" />}>Queries</PreviewTabButton>
          <PreviewTabButton active={previewTab === "lineage"} onClick={() => onPreviewTabChange("lineage")} icon={<ShieldCheck className="kc-native-icon" />}>Lineage</PreviewTabButton>
          <PreviewTabButton active={previewTab === "code"} onClick={() => onPreviewTabChange("code")} icon={<Code2 className="kc-native-icon" />}>Code</PreviewTabButton>
        </div>
        <div className="kc-askdash-preview-actions">
          <button type="button" onClick={onRefresh} title="Refresh"><RefreshCw className="kc-native-icon" /></button>
          <button type="button" onClick={onFullscreen} title="Fullscreen"><Maximize2 className="kc-native-icon" /></button>
        </div>
      </header>
      <div className="kc-askdash-dashboard-controls">
        <input
          aria-label="Dashboard name"
          value={dashboardName}
          onChange={(event) => onDashboardNameChange(event.target.value)}
        />
        <input
          aria-label="Dashboard intent"
          value={dashboardIntent}
          onChange={(event) => onDashboardIntentChange(event.target.value)}
          placeholder="Dashboard intent"
        />
        <button type="button" onClick={() => onBuildDashboard()} disabled={busyBuild || !queryResult}>
          {busyBuild ? <Loader2 className="kc-native-icon is-spinning" /> : <BarChart3 className="kc-native-icon" />}
          Build
        </button>
      </div>
      <div className="kc-askdash-preview-body">
        {previewTab === "preview" ? (
          <DashboardCanvas dashboard={dashboard} selectedDashboard={selectedDashboard} rows={rows} hasDashboard={hasDashboard} onBuildDashboard={onBuildDashboard} busyBuild={busyBuild} canBuild={Boolean(queryResult)} />
        ) : previewTab === "queries" ? (
          <QueriesPanel queryResult={queryResult} notebook={notebook} rows={rows} />
        ) : previewTab === "lineage" ? (
          <LineagePanel queryResult={queryResult} dashboardQueries={dashboard.queries} />
        ) : (
          <CodePanel spec={spec} queryResult={queryResult} />
        )}
      </div>
    </aside>
  );
}

function PreviewTabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} className={active ? "is-active" : ""}>
      {icon}
      {children}
    </button>
  );
}

function DashboardCanvas({
  dashboard,
  selectedDashboard,
  rows,
  hasDashboard,
  onBuildDashboard,
  busyBuild,
  canBuild,
}: {
  dashboard: ReturnType<typeof dashboardSpecToByaanViewModel>;
  selectedDashboard: KnowledgeAssetMetadata | null;
  rows: Array<Record<string, unknown>>;
  hasDashboard: boolean;
  onBuildDashboard: (event?: FormEvent<HTMLFormElement>) => void;
  busyBuild: boolean;
  canBuild: boolean;
}) {
  if (!hasDashboard) {
    return (
      <div className="kc-askdash-preview-empty">
        <LayoutDashboard className="kc-native-state-icon" />
        <strong>Dashboard preview opens after the first answer</strong>
        <span>Query results can be turned into a Dashboard Skill without leaving the notebook.</span>
        <button type="button" onClick={() => onBuildDashboard()} disabled={!canBuild || busyBuild}>
          {busyBuild ? <Loader2 className="kc-native-icon is-spinning" /> : <BarChart3 className="kc-native-icon" />}
          Generate Dashboard
        </button>
      </div>
    );
  }
  return (
    <section className="kc-askdash-dashboard-canvas">
      <header>
        <div>
          <h3>{dashboard.title || selectedDashboard?.name || "Dashboard preview"}</h3>
          <p>{dashboard.description || "Generated from governed AskData evidence."}</p>
        </div>
        <span className="kc-native-badge is-success">governed</span>
      </header>
      <div className="kc-askdash-filter-bar">
        <ShieldCheck className="kc-native-icon" />
        {dashboard.filters.length
          ? dashboard.filters.map((filter, index) => (
              <span key={index}>{String(objectValue(filter).label || objectValue(filter).id || "filter")}</span>
            ))
          : <span>All governed rows</span>}
      </div>
      <div className="kc-askdash-dashboard-tiles">
        {dashboard.tiles.length
          ? dashboard.tiles.map((tile, index) => <DashboardTile key={String(objectValue(tile).id || index)} tile={objectValue(tile)} rows={rows} />)
          : <DashboardTile tile={{ title: "Primary metric", type: "bar", data_view_id: "askdata_result" }} rows={rows} />}
      </div>
      <MiniResultTable rows={rows} dense />
    </section>
  );
}

function DashboardTile({ tile, rows }: { tile: Record<string, unknown>; rows: Array<Record<string, unknown>> }) {
  const type = String(tile.type || "tile").toLowerCase();
  const values = numericValues(rows).slice(0, 8);
  const value = values.length ? values.reduce((sum, item) => sum + item, 0) : rows.length;
  return (
    <article className={`is-${type}`}>
      <span>{type}</span>
      <strong>{String(tile.title || tile.id || "KPI")}</strong>
      <em>{String(tile.data_view_id || "askdata_result")}</em>
      <b>{formatNumber(value)}</b>
      <Sparkline values={values} />
    </article>
  );
}

function QueriesPanel({
  queryResult,
  notebook,
  rows,
}: {
  queryResult: AskDataQueryResult | null;
  notebook: ReturnType<typeof askDataToNotebookViewModel>;
  rows: Array<Record<string, unknown>>;
}) {
  return (
    <section className="kc-askdash-query-panel" data-testid="dashboard-query-debug-panel">
      <div className="kc-askdash-query-editor-lite">
        <header>
          <Table2 className="kc-native-icon" />
          <strong>Queries</strong>
          <span>{notebook.status}</span>
        </header>
        <pre><code>{queryResult?.data.sql || notebook.sql || "-- Ask a question to produce SQL"}</code></pre>
      </div>
      <MiniResultTable rows={rows} />
    </section>
  );
}

function LineagePanel({
  queryResult,
  dashboardQueries,
}: {
  queryResult: AskDataQueryResult | null;
  dashboardQueries: Array<Record<string, unknown>>;
}) {
  const firstQuery = objectValue(dashboardQueries[0]);
  return (
    <section className="kc-askdash-lineage-panel" data-testid="dashboard-query-evidence-panel">
      <EvidenceBlock title="metricDefinition" value={formatJson(queryResult?.data.metricDefinition ?? firstQuery.metricDefinition)} />
      <EvidenceBlock title="policyDecision" value={formatJson(queryResult?.data.policyDecision ?? firstQuery.policyDecision)} />
      <EvidenceBlock title="freshness" value={formatJson(queryResult?.data.freshness ?? firstQuery.freshness)} />
      <EvidenceBlock title="lineage" value={formatJson(queryResult?.data.lineage ?? firstQuery.lineage ?? [])} />
      <EvidenceBlock title="evidence" value={formatJson(queryResult?.data.evidence ?? firstQuery.evidence ?? [])} />
    </section>
  );
}

function CodePanel({
  spec,
  queryResult,
}: {
  spec: Record<string, unknown>;
  queryResult: AskDataQueryResult | null;
}) {
  const payload = Object.keys(spec).length ? spec : { askdata_seed: queryResult ?? null };
  return (
    <section className="kc-askdash-code-panel">
      <header>
        <Code2 className="kc-native-icon" />
        <strong>dashboard_spec.json</strong>
      </header>
      <pre><code>{formatJson(payload)}</code></pre>
    </section>
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

function MiniResultTable({ rows, dense = false }: { rows: Array<Record<string, unknown>>; dense?: boolean }) {
  const columns = Object.keys(rows[0] ?? {}).slice(0, 8);
  if (!rows.length || !columns.length) {
    return (
      <div className="kc-askdash-result-empty">
        <Database className="kc-native-icon" />
        <span>No rows yet</span>
      </div>
    );
  }
  return (
    <div className={`kc-askdash-result-table${dense ? " is-dense" : ""}`}>
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, dense ? 8 : 20).map((row, index) => (
            <tr key={index}>
              {columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ByaanBlockedNotebookShell({
  status,
  onRefresh,
}: {
  status: NotebookStatus;
  onRefresh: () => void;
}) {
  return (
    <section className="kc-askdash-blocked-notebook" data-testid="askdashboard-not-configured-blocked" role="status">
      <ByaanStatusStrip status={status} />
      <div>
        <ShieldCheck className="kc-native-state-icon" />
        <strong>需要已发布 Semantic Skill</strong>
        <span>AskTable 和 Dashboard 只通过受治理语义能力查询；当前状态为 blocked，不会伪造 query 或 dashboard 成功。</span>
        <button type="button" onClick={onRefresh}><RefreshCw className="kc-native-icon" />Refresh</button>
      </div>
    </section>
  );
}

function ByaanStatusStrip({ status }: { status: NotebookStatus }) {
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
  return <span><strong>{label}</strong><em>{value}</em></span>;
}

function MobilePaneTabs({
  activePane,
  onPaneChange,
}: {
  activePane: MobilePane;
  onPaneChange: (pane: MobilePane) => void;
}) {
  return (
    <div className="kc-askdash-mobile-tabs">
      <button type="button" className={activePane === "answer" ? "is-active" : ""} onClick={() => onPaneChange("answer")}>Answer</button>
      <button type="button" className={activePane === "preview" ? "is-active" : ""} onClick={() => onPaneChange("preview")}>Preview</button>
    </div>
  );
}

function WorkbenchAlert({ message }: { message: string }) {
  return (
    <div className="kc-workbench-alert" role="alert">
      <AlertCircle className="kc-native-icon" />
      <span>{message}</span>
    </div>
  );
}

function latestDashboardJob(
  buildJobs: KnowledgeAssetBuildJob[],
  selectedDashboard: KnowledgeAssetMetadata | null,
  buildResult: DashboardSkillBuildResult | null,
) {
  return (
    (buildResult?.job_id ? buildJobs.find((job) => job.id === buildResult.job_id) : null) ??
    buildJobs.find((job) => job.job_type.includes("dashboard") && job.asset_id === selectedDashboard?.asset_id) ??
    buildJobs.find((job) => job.job_type.includes("dashboard")) ??
    null
  );
}

function statusModel({
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
}): NotebookStatus {
  const dashboardRuntime = objectValue(selectedDashboard?.capability_package?.runtime);
  const queryExecution = objectValue((queryResult?.data as unknown as Record<string, unknown> | undefined)?.execution);
  const buildOutput = objectValue(latestDashboardJob?.output);
  const blockedReasons = latestDashboardJob?.output?.blocked_reasons;
  const gateBlockers = selectedDashboard?.gate?.blockers;
  const policyReason = objectValue(queryResult?.data.policyDecision).reason;
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
        (queryResult?.status === "blocked" ? policyReason || "policy denied" : "") ||
        "none",
    ),
  };
}

function blockedStatus(): NotebookStatus {
  return {
    jobStatus: "blocked",
    agentStatus: "blocked_no_semantic_skill",
    runnerBackend: "agentkit_governed_rest",
    generationMode: "not_configured",
    blockedReason: "no published Semantic Skill",
  };
}

function exampleQuestions(metrics: string[], dimensions: string[]) {
  const firstMetric = metrics[0] || "核心指标";
  const firstDimension = dimensions[0] || "门店";
  return [
    `按${firstDimension}查看${firstMetric}`,
    ...fallbackExamples,
  ].slice(0, 5);
}

function numericValues(rows: Array<Record<string, unknown>>) {
  return rows
    .flatMap((row) => Object.values(row))
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function Sparkline({ values }: { values: number[] }) {
  const bars = values.length ? values.slice(0, 8) : [8, 14, 11, 18, 16, 22];
  const max = Math.max(...bars, 1);
  return (
    <div className="kc-askdash-sparkline">
      {bars.map((value, index) => (
        <span key={index} style={{ height: `${Math.max(14, (value / max) * 100)}%` }} />
      ))}
    </div>
  );
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

function isAdkEvent(value: unknown): value is {
  content?: { parts?: Array<Record<string, unknown>> };
} {
  return Boolean(value && typeof value === "object" && "content" in value);
}

function queryResultFromEvent(event: unknown): AskDataQueryResult | null {
  const response = functionResponse(event, "query_semantic_skill");
  if (!response) return null;
  const direct = isAskDataQueryResult(response.askdata) ? response.askdata : null;
  const rows = arrayRecords(response.rows ?? response.result ?? direct?.data.rows);
  return {
    schema: "agentkit.askdata.result.v1",
    status: String(response.status || direct?.status || (response.success === false ? "blocked" : "completed")),
    asset: direct?.asset ?? {
      type: "semantic_model",
      id: String(response.semantic_asset_id || ""),
      name: String(response.semantic_asset_id || "Semantic Skill"),
    },
    data: {
      rows,
      returnedCount: Number(response.returnedCount ?? direct?.data.returnedCount ?? rows.length),
      sql: String(response.sql || direct?.data.sql || ""),
      metricDefinition: (response.metricDefinition ?? direct?.data.metricDefinition ?? "") as string | Record<string, unknown>,
      policyDecision: objectValue(response.policyDecision ?? direct?.data.policyDecision),
      freshness: objectValue(response.freshness ?? direct?.data.freshness),
      evidence: arrayValue(response.evidence ?? direct?.data.evidence).filter(isRecord),
      lineage: arrayValue(response.lineage ?? direct?.data.lineage).filter(isRecord),
      metric: objectValue(response.metric ?? direct?.data.metric),
      dimensions: arrayValue(response.dimensions ?? direct?.data.dimensions).filter(isRecord),
      execution: objectValue(response.execution ?? direct?.data.execution),
    },
    mock: direct?.mock ?? false,
  };
}

function dashboardResultFromEvent(event: unknown): DashboardSkillBuildResult | null {
  const response = functionResponse(event, "build_dashboard_skill");
  if (!response) return null;
  const dashboard = response.dashboard;
  if (!dashboard || typeof dashboard !== "object") return null;
  return {
    schema: "agentkit.dashboard_skill_build.v1",
    job_id: String(response.job_id || ""),
    status: String(response.status || (response.success ? "succeeded" : "blocked")),
    dashboard_asset_id: String(response.dashboard_asset_id || (dashboard as Record<string, unknown>).asset_id || ""),
    dashboard: dashboard as KnowledgeAssetMetadata,
    preview: objectValue(response.preview),
    mock: false,
  };
}

function functionResponse(event: unknown, name: string): Record<string, unknown> | null {
  if (!event || typeof event !== "object") return null;
  const content = (event as Record<string, unknown>).content;
  if (!content || typeof content !== "object") return null;
  const parts = (content as Record<string, unknown>).parts;
  if (!Array.isArray(parts)) return null;
  for (const part of parts) {
    if (!part || typeof part !== "object") continue;
    const record = part as Record<string, unknown>;
    const response = record.functionResponse ?? record.function_response;
    if (!response || typeof response !== "object") continue;
    const payload = response as Record<string, unknown>;
    if (payload.name !== name) continue;
    const body = payload.response;
    return body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  }
  return null;
}

function isAskDataQueryResult(value: unknown): value is AskDataQueryResult {
  return Boolean(
    value &&
      typeof value === "object" &&
      (value as Record<string, unknown>).schema === "agentkit.askdata.result.v1" &&
      typeof (value as Record<string, unknown>).data === "object",
  );
}

function hasFinalText(blocks: Block[]): boolean {
  return blocks.some((block) => block.kind === "text" && block.text.trim().length > 0);
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function arrayRecords(value: unknown): Array<Record<string, unknown>> {
  return arrayValue(value).filter(isRecord);
}
