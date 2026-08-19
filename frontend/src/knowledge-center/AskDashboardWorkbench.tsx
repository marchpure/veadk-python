import { AlertCircle } from "lucide-react";
import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";

import {
  buildDashboardSkill,
  streamAskData,
  type AskDataQueryResult,
  type DashboardSkillBuildResult,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSpace,
} from "../adk/knowledgeAssets";
import { parseSSE } from "../adk/sse";
import { applyEvent, emptyAcc, type Acc, type Block } from "../blocks";
import { capabilityValues, objectValue } from "./knowledgeWorkbenchUtils";
import {
  ByaanNotebook,
  askDataToSemanticQueryResultEvent,
  dashboardAssetToByaanOption,
  dashboardPreviewFromAgentKit,
  roundsToByaanMessages,
  semanticAssetToByaanModel,
} from "../features/knowledge-assets/byaan-notebook";

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

const fallbackExamples = [
  "按门店查看最近销售票数",
  "过去 30 天核心指标趋势如何？",
  "哪些区域的转化率下降最明显？",
  "列出异常波动，并给出 SQL 和口径证据",
];

export function AskDashboardWorkbench({
  activeSpace,
  semanticSkills,
  dashboardSkills,
  onRefresh,
}: {
  activeSpace: KnowledgeAssetSpace | null;
  semanticSkills: KnowledgeAssetMetadata[];
  dashboardSkills: KnowledgeAssetMetadata[];
  buildJobs: KnowledgeAssetBuildJob[];
  onRefresh: () => void | Promise<void>;
}) {
  const [assetId, setAssetId] = useState(semanticSkills[0]?.asset_id || "");
  const [question, setQuestion] = useState("");
  const [dashboardIntent, setDashboardIntent] = useState("");
  const [versionAssetId, setVersionAssetId] = useState(dashboardSkills[0]?.asset_id || "");
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
  const metrics = capabilityValues(selectedSkill, "metrics");
  const dimensions = capabilityValues(selectedSkill, "dimensions");
  const examples = useMemo(() => exampleQuestions(metrics, dimensions), [metrics, dimensions]);
  const canAsk = Boolean(selectedSkill) && !busyQuery;
  const byaanModels = useMemo(
    () => semanticSkills.map(semanticAssetToByaanModel),
    [semanticSkills],
  );
  const byaanDashboards = useMemo(
    () => dashboardOptions.map(dashboardAssetToByaanOption),
    [dashboardOptions],
  );
  const byaanMessages = useMemo(() => roundsToByaanMessages(rounds), [rounds]);
  const byaanSemanticResult = useMemo(
    () => askDataToSemanticQueryResultEvent(queryResult),
    [queryResult],
  );
  const byaanDashboardPreview = useMemo(
    () => dashboardPreviewFromAgentKit({
      selectedDashboard,
      buildResult,
      queryResult,
      busyBuild,
    }),
    [buildResult, busyBuild, queryResult, selectedDashboard],
  );
  const latestCompletedQuery = useMemo(
    () => [...rounds].reverse().find((round) => round.result?.status === "completed")?.result ?? queryResult,
    [queryResult, rounds],
  );
  const dashboardBuildGate = useMemo(
    () => dashboardBuildReadiness(latestCompletedQuery),
    [latestCompletedQuery],
  );

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
                status: payload?.status === "completed"
                  ? "completed"
                  : payload?.status === "blocked"
                    ? "blocked"
                    : hasFinalText(acc.blocks)
                      ? "completed"
                      : "error",
                result: payload,
                acc,
                blocks: acc.blocks,
                conversationId,
                sessionId,
                error: payload || hasFinalText(acc.blocks)
                  ? undefined
                  : "AskTable stream ended without a governed query result.",
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
    if (!dashboardBuildGate.ready) {
      setError(dashboardBuildGate.reason);
      return;
    }
    const latestQuestion = rounds.at(-1)?.question || question || dashboardIntent || "展示核心指标、维度拆解和策略证据";
    setBusyBuild(true);
    setError("");
    try {
      const result = await buildDashboardSkill({
        space_id: activeSpace?.id,
        semantic_asset_id: selectedSkill.asset_id,
        name: `${selectedSkill.name || "AskTable"} Dashboard`,
        intent: dashboardIntent || latestQuestion,
        metric: selectedMetricId(latestCompletedQuery),
        dimensions: selectedDimensionIds(latestCompletedQuery),
        publish: true,
      });
      if (result.status !== "succeeded" || !result.dashboard) {
        throw new Error(result.status ? `Dashboard Skill 生成失败：${result.status}` : "Dashboard Skill 生成失败。");
      }
      setBuildResult(result);
      setVersionAssetId(result.dashboard_asset_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成 Dashboard Skill 失败。");
    } finally {
      setBusyBuild(false);
    }
  }

  return (
    <div className={fullscreen ? "byaan-notebook-fullscreen" : undefined}>
      {error ? <WorkbenchAlert message={error} /> : null}
      <ByaanNotebook
        models={byaanModels}
        selectedModelId={assetId}
        onModelChange={setAssetId}
        dashboards={byaanDashboards}
        selectedDashboardId={versionAssetId}
        onDashboardChange={setVersionAssetId}
        messages={byaanMessages}
        input={question}
        onInputChange={setQuestion}
        onSubmit={() => void submitQuery()}
        examples={examples}
        onExampleSelect={setQuestion}
        semanticQueryResult={byaanSemanticResult}
        dashboardPreview={byaanDashboardPreview}
        busyQuery={busyQuery}
        busyBuild={busyBuild}
        onCreateDashboard={() => void buildDashboardFromLatest()}
        createDashboardDisabled={!dashboardBuildGate.ready}
        createDashboardDisabledReason={dashboardBuildGate.reason}
        onRefresh={() => void onRefresh()}
        onFullscreen={() => setFullscreen((value) => !value)}
        blocked={!canAsk}
      />
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

function exampleQuestions(metrics: string[], dimensions: string[]) {
  const firstMetric = metrics[0] || "核心指标";
  const firstDimension = dimensions[0] || "门店";
  return [
    `按${firstDimension}查看${firstMetric}`,
    ...fallbackExamples,
  ].slice(0, 5);
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

function dashboardBuildReadiness(result: AskDataQueryResult | null): { ready: boolean; reason: string } {
  if (!result) {
    return { ready: false, reason: "请先完成一次生产 AskTable 查询，再生成 Dashboard。" };
  }
  if (result.status !== "completed") {
    return { ready: false, reason: "最近一次 AskTable 查询未完成，不能生成 Dashboard。" };
  }
  if (!result.data.rows?.length) {
    return { ready: false, reason: "最近一次 AskTable 查询没有返回数据，不能生成 Dashboard。" };
  }
  if (result.data.execution?.production_completed !== true) {
    return { ready: false, reason: "最近一次 AskTable 查询不是生产完成结果，不能生成 Dashboard。" };
  }
  return { ready: true, reason: "" };
}

function selectedMetricId(result: AskDataQueryResult | null): string | undefined {
  const metric = result?.data.metric;
  const id = metric?.id;
  return typeof id === "string" && id ? id : undefined;
}

function selectedDimensionIds(result: AskDataQueryResult | null): string[] {
  return (result?.data.dimensions ?? [])
    .map((dimension) => dimension.id)
    .filter((id): id is string => typeof id === "string" && id.length > 0);
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
