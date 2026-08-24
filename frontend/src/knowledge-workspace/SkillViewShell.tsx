import { useMemo, useState } from "react";
import {
  createRequestContext,
  type KnowledgeCommandResult,
} from "./production/ports";
import {
  getWorkspaceAdapter,
} from "./production/store";
import "./SkillViewShell.css";

type ViewProjection = {
  skillName: string;
  kind: string;
  skillVersion: string;
  dataVersion: string;
  dataTime: string;
  renderTime: string;
  traceId: string;
  template: string;
  answer?: string;
  rows?: Array<Array<{ field: string; value: string | number | boolean | null }>>;
  metrics?: string[];
  dimensions?: string[];
  relationships?: string[];
  chart?: { title: string; xField: string; yField: string; points: Array<[string, number]> };
  nodes?: Array<GraphNodeProjection>;
  edges?: Array<GraphEdgeProjection>;
  values?: Array<[string, number]>;
  alerts?: string[];
};
type GraphNodeProjection = { id: string; label: string; entityType: string };
type GraphEdgeProjection = { source: string; target: string; relation: string };

function projectionFromResult(result: KnowledgeCommandResult): ViewProjection | null {
  const value = result.result;
  if (!value || typeof value !== "object") return null;
  const view = value.skillViewRevision;
  if (!view || typeof view !== "object") return null;
  const model = (view as Record<string, unknown>).viewModel;
  const intent = (view as Record<string, unknown>).intent;
  if (!model || typeof model !== "object" || !intent || typeof intent !== "object") {
    return null;
  }
  const modelRecord = model as Record<string, unknown>;
  const intentRecord = intent as Record<string, unknown>;
  const template = typeof intentRecord.template === "string" ? intentRecord.template : "skill";
  const asStrings = (value: unknown): string[] =>
    Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  const asPoints = (value: unknown): Array<[string, number]> =>
    Array.isArray(value)
      ? value.flatMap((item) =>
          Array.isArray(item) && typeof item[0] === "string" && typeof item[1] === "number"
            ? [[item[0], item[1]] as [string, number]]
            : [],
        )
      : [];
  const skillResult = value.skillResult;
  const goldenAsset =
    value.goldenAssetRevision && typeof value.goldenAssetRevision === "object"
      ? (value.goldenAssetRevision as Record<string, unknown>)
      : null;
  const traceId =
    skillResult && typeof skillResult === "object" &&
    typeof (skillResult as Record<string, unknown>).traceId === "string"
      ? (skillResult as Record<string, unknown>).traceId as string
      : "trace-unavailable";
  return {
    skillName: "Skill View",
    kind: typeof intentRecord.template === "string" ? intentRecord.template : "skill",
    template,
    skillVersion: String(value.draftRevision ?? "DRAFT"),
    dataVersion:
      typeof goldenAsset?.id === "string"
        ? goldenAsset.id
        : String(value.goldenAssetRevision ?? "revision"),
    dataTime: new Date().toISOString(),
    renderTime: new Date().toISOString(),
    traceId,
    answer: typeof modelRecord.answer === "string" ? modelRecord.answer : undefined,
    rows: Array.isArray(modelRecord.rows) ? modelRecord.rows as ViewProjection["rows"] : undefined,
    metrics: asStrings(modelRecord.metricRefs),
    dimensions: asStrings(modelRecord.dimensionRefs),
    relationships: asStrings(modelRecord.relationshipRefs),
    chart: template === "chart"
      ? {
          title: typeof modelRecord.title === "string" ? modelRecord.title : "Chart",
          xField: typeof modelRecord.xField === "string" ? modelRecord.xField : "x",
          yField: typeof modelRecord.yField === "string" ? modelRecord.yField : "y",
          points: asPoints(
            Array.isArray(modelRecord.series) && modelRecord.series[0] &&
              typeof modelRecord.series[0] === "object"
              ? (modelRecord.series[0] as Record<string, unknown>).points
              : [],
          ),
        }
      : undefined,
    nodes: Array.isArray(modelRecord.nodes)
      ? modelRecord.nodes.filter((item): item is GraphNodeProjection =>
          Boolean(item && typeof item === "object" &&
            typeof (item as Record<string, unknown>).id === "string" &&
            typeof (item as Record<string, unknown>).label === "string" &&
            typeof (item as Record<string, unknown>).entityType === "string"),
        ).map((item) => ({
          id: item.id,
          label: item.label,
          entityType: item.entityType,
        }))
      : undefined,
    edges: Array.isArray(modelRecord.edges)
      ? modelRecord.edges.filter((item): item is GraphEdgeProjection =>
          Boolean(item && typeof item === "object" &&
            typeof (item as Record<string, unknown>).source === "string" &&
            typeof (item as Record<string, unknown>).target === "string" &&
            typeof (item as Record<string, unknown>).relation === "string"),
        ).map((item) => ({
          source: item.source,
          target: item.target,
          relation: item.relation,
        }))
      : undefined,
    values: asPoints(modelRecord.values),
    alerts: asStrings(modelRecord.alerts),
  };
}

export function SkillViewShell({
  draftId = "current-skill",
  revision = 1,
}: {
  draftId?: string;
  revision?: number;
}) {
  const [projection, setProjection] = useState<ViewProjection | null>(null);
  const [message, setMessage] = useState("选择一个 Skill 操作开始构建视图。");
  const [running, setRunning] = useState(false);
  const [currentRevision, setCurrentRevision] = useState(revision);
  const [retryOperationId, setRetryOperationId] = useState<string | null>(null);
  const [assistantText, setAssistantText] = useState("");
  const [pendingDiff, setPendingDiff] = useState<{
    token: string;
    baseRevision: number;
    nextRevision: number;
    before: string;
    after: string;
  } | null>(null);
  const adapter = useMemo(() => getWorkspaceAdapter(), []);

  async function run(command: "skill-draft.run" | "evaluation.run") {
    setRunning(true);
    setMessage(command === "evaluation.run" ? "正在运行评测与策略门禁…" : "正在执行 Skill…");
    try {
      const result = await adapter.command(
        command === "evaluation.run"
          ? {
              command,
              payload: {
                targetId: draftId,
                suiteId: "default-step3",
                environment: "test",
                caseIds: [],
              },
            }
          : {
              command,
              payload: {
                draftId,
                revision: currentRevision,
                traceId: `trace-${Date.now()}`,
                maxSteps: 10,
                budget: 10_000,
              },
            },
        createRequestContext(),
      );
      const next = projectionFromResult(result);
      if (next) setProjection(next);
      const resultValue = result.result;
      const resultStatus =
        resultValue && typeof resultValue === "object" &&
        typeof (resultValue as Record<string, unknown>).status === "string"
          ? (resultValue as Record<string, unknown>).status
          : undefined;
      if (resultStatus === "partially_succeeded" || resultStatus === "failed") {
        setRetryOperationId(result.operationId ?? null);
      } else if (resultStatus === "ready_for_evaluation") {
        setRetryOperationId(null);
      }
      setMessage(result.accepted ? "操作已完成。" : "操作未通过服务端确认。");
    } catch {
      setMessage("操作失败，请检查服务端返回的错误信息。");
    } finally {
      setRunning(false);
    }
  }

  async function retryBuilder() {
    if (!retryOperationId || running) return;
    setRunning(true);
    setMessage("正在重试 Builder…");
    try {
      const result = await adapter.command(
        {
          command: "skill-draft.retry",
          payload: {
            draftId,
            revision: currentRevision,
            traceId: `retry-${Date.now()}`,
            maxSteps: 10,
            budget: 10_000,
            retryOfOperationId: retryOperationId,
          },
        },
        createRequestContext(),
      );
      const next = projectionFromResult(result);
      if (next) setProjection(next);
      const value = result.result;
      const status =
        value && typeof value === "object" &&
        typeof (value as Record<string, unknown>).status === "string"
          ? (value as Record<string, unknown>).status
          : undefined;
      if (status === "ready_for_evaluation") setRetryOperationId(null);
      else if (result.operationId) setRetryOperationId(result.operationId);
      setMessage(result.accepted ? "Builder 重试完成。" : "Builder 重试未通过服务端确认。");
    } catch {
      setMessage("Builder 重试失败，请检查服务端返回的错误信息。");
    } finally {
      setRunning(false);
    }
  }

  async function proposeDescriptionPatch() {
    if (!assistantText.trim() || running) return;
    setRunning(true);
    setMessage("正在校验修改并重新执行 Skill…");
    try {
      const result = await adapter.command(
        {
          command: "assistant.turn",
          payload: {
            text: assistantText.trim(),
            contextIds: [],
            context: {
              skillId: draftId,
              viewRevisionId: "current",
              selectedIds: [],
              schemaRef: "local://schema/skill-view",
              permissionScope: "permission://workspace/current",
            },
            patch: {
              patchId: `patch-${Date.now()}`,
              skillId: draftId,
              baseRevision: currentRevision,
              operation: "set_description",
              value: assistantText.trim(),
            },
          },
        },
        createRequestContext(),
      );
      const value = result.result;
      if (value && typeof value === "object" && "diff" in value) {
        const diff = (value as Record<string, unknown>).diff;
        if (diff && typeof diff === "object") {
          const record = diff as Record<string, unknown>;
          setPendingDiff({
            token: String(record.undoToken),
            baseRevision: Number(record.baseRevision),
            nextRevision: Number(record.nextRevision),
            before: String(record.before),
            after: String(record.after),
          });
          setCurrentRevision(Number(record.nextRevision));
        }
      }
      setMessage(result.accepted ? "修改已应用并重新执行。" : "修改未通过服务端确认。");
      setAssistantText("");
    } catch {
      setMessage("修改失败，请检查服务端返回的错误信息。");
    } finally {
      setRunning(false);
    }
  }

  async function undoPatch() {
    if (!pendingDiff || running) return;
    setRunning(true);
    setMessage("正在撤销修改并重新执行 Skill…");
    try {
      const result = await adapter.command(
        {
          command: "assistant.turn",
          payload: {
            text: "撤销上一次修改",
            contextIds: [],
            context: {
              skillId: draftId,
              viewRevisionId: "current",
              selectedIds: [],
              schemaRef: "local://schema/skill-view",
              permissionScope: "permission://workspace/current",
            },
            patch: {
              patchId: `undo-${Date.now()}`,
              skillId: draftId,
              baseRevision: currentRevision,
              operation: "set_description",
              value: "",
              undoToken: pendingDiff.token,
            },
          },
        },
        createRequestContext(),
      );
      const value = result.result;
      if (value && typeof value === "object" && "diff" in value) {
        const diff = (value as Record<string, unknown>).diff;
        if (diff && typeof diff === "object") {
          setCurrentRevision(Number((diff as Record<string, unknown>).nextRevision));
        }
      }
      setPendingDiff(null);
      setMessage(result.accepted ? "修改已撤销并重新执行。" : "撤销未通过服务端确认。");
    } catch {
      setMessage("撤销失败，请检查服务端返回的错误信息。");
    } finally {
      setRunning(false);
    }
  }

  async function exportView() {
    if (!projection || running) return;
    setRunning(true);
    setMessage("正在请求服务端导出…");
    try {
      const result = await adapter.command(
        { command: "artifact.export", payload: { resourceId: draftId, format: "json" } },
        createRequestContext(),
      );
      setMessage(
        result.accepted
          ? "导出已由服务端创建。"
          : "导出当前被服务端门禁阻断，未在浏览器生成本地文件。",
      );
    } catch {
      setMessage("导出请求失败，请检查服务端返回的错误信息。");
    } finally {
      setRunning(false);
    }
  }

  async function shareView() {
    if (running) return;
    setRunning(true);
    setMessage("正在请求服务端分享…");
    try {
      const result = await adapter.command(
        { command: "resource.share", payload: { resourceId: draftId } },
        createRequestContext(),
      );
      setMessage(
        result.accepted
          ? "分享已由服务端创建。"
          : "分享当前被服务端门禁阻断，未使用浏览器剪贴板。",
      );
    } catch {
      setMessage("分享请求失败，请检查服务端返回的错误信息。");
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="skill-view-shell" aria-label="Skill View">
      <header className="skill-view-header">
        <div>
          <p className="skill-view-eyebrow">Skill View · 调试视图</p>
          <h1>{projection?.skillName ?? "Knowledge Asset Skill"}</h1>
          <span>{projection?.kind ?? "未执行"} · Skill revision {projection?.skillVersion ?? "DRAFT"}</span>
        </div>
        <div className="skill-view-actions">
          <button type="button" onClick={() => void run("skill-draft.run")} disabled={running}>
            {running ? "运行中…" : "执行 Skill"}
          </button>
          {retryOperationId ? (
            <button type="button" onClick={() => void retryBuilder()} disabled={running}>
              Retry Builder
            </button>
          ) : null}
          <button type="button" onClick={() => void run("evaluation.run")} disabled={running}>
            Evaluate
          </button>
          <button type="button" onClick={exportView} disabled={!projection || running}>
            Export
          </button>
          <button type="button" onClick={() => void shareView()} disabled={running}>
            Share to human
          </button>
          <button type="button" onClick={() => void run("evaluation.run")} disabled={running}>
            Evaluate &amp; publish
          </button>
        </div>
      </header>
      <section className="skill-view-meta" aria-label="Skill metadata">
        <span>Data version: {projection?.dataVersion ?? "—"}</span>
        <span>Data time: {projection?.dataTime ?? "—"}</span>
        <span>Rendered: {projection?.renderTime ?? "—"}</span>
        <span>Trace: {projection?.traceId ?? "—"}</span>
      </section>
      <section className="skill-view-body">
        <article className="skill-view-content">
          {projection?.template === "semantic" ? (
            <section aria-label="Semantic schema" className="skill-view-typed-section">
              <h2>Schema &amp; MDL</h2>
              <p>Metrics: {projection.metrics?.join(", ") || "未声明"}</p>
              <p>Dimensions: {projection.dimensions?.join(", ") || "未声明"}</p>
              <p>Relationships: {projection.relationships?.join(", ") || "未声明"}</p>
            </section>
          ) : null}
          {projection?.template === "chart" && projection.chart ? (
            <section aria-label="Chart view" className="skill-view-typed-section">
              <h2>{projection.chart.title}</h2>
              <p>{projection.chart.xField} → {projection.chart.yField}</p>
              <div className="skill-view-bars" role="img" aria-label="Chart data summary">
                {projection.chart.points.map(([label, value]) => (
                  <div className="skill-view-bar" key={label}>
                    <span>{label}</span><strong style={{ width: `${Math.max(4, Math.min(100, value))}%` }}>{value}</strong>
                  </div>
                ))}
              </div>
              <p className="skill-view-status">数据表</p>
            </section>
          ) : null}
          {projection?.template === "knowledge" && projection.answer ? (
            <section aria-label="Knowledge answer" className="skill-view-typed-section">
              <h2>Answer &amp; citations</h2>
              <p className="skill-view-answer">{projection.answer}</p>
            </section>
          ) : null}
          {projection?.template === "graph_ontology" ? (
            <section aria-label="Graph ontology view" className="skill-view-typed-section">
              <h2>Entities &amp; relationships</h2>
              <p>{projection.nodes?.length ?? 0} entities · {projection.edges?.length ?? 0} relationships</p>
              <div className="skill-view-node-list">
                {projection.nodes?.slice(0, 100).map((node) => <span key={node.id}>{node.label} <small>{node.entityType}</small></span>)}
              </div>
            </section>
          ) : null}
          {projection?.template === "monitoring" ? (
            <section aria-label="Monitoring view" className="skill-view-typed-section">
              <h2>Monitoring &amp; alerts</h2>
              <div className="skill-view-bars">
                {projection.values?.map(([label, value]) => (
                  <div className="skill-view-bar" key={label}><span>{label}</span><strong>{value}</strong></div>
                ))}
              </div>
              <p>Alerts: {projection.alerts?.join(", ") || "暂无告警"}</p>
            </section>
          ) : null}
          {projection?.template !== "semantic" &&
            projection?.template !== "chart" &&
            projection?.template !== "knowledge" &&
            projection?.template !== "graph_ontology" &&
            projection?.template !== "monitoring" &&
            projection?.answer ? <p className="skill-view-answer">{projection.answer}</p> : null}
          {projection?.rows ? (
            <div className="skill-view-table" role="table" aria-label="Skill result data">
              {projection.rows.map((row, rowIndex) => (
                <div className="skill-view-row" role="row" key={`row-${rowIndex}`}>
                  {row.map((cell) => <span role="cell" key={`${rowIndex}-${cell.field}`}>{String(cell.value ?? "")}</span>)}
                </div>
              ))}
            </div>
          ) : null}
          {!projection && <p className="skill-view-empty">{message}</p>}
          {projection && <p className="skill-view-status" role="status">{message}</p>}
        </article>
        <aside className="skill-view-chat" aria-label="Skill assistant">
          <h2>Skill assistant</h2>
          <p>只使用当前 Skill、View、Schema 与权限上下文。</p>
          <label htmlFor="skill-assistant-input">修改描述</label>
          <textarea
            id="skill-assistant-input"
            value={assistantText}
            onChange={(event) => setAssistantText(event.target.value)}
            placeholder="输入要应用的描述修改"
            rows={4}
          />
          <button type="button" onClick={() => void proposeDescriptionPatch()} disabled={running || !assistantText.trim()}>
            提议修改并重跑
          </button>
          {pendingDiff ? (
            <div className="skill-view-diff" role="status">
              <strong>已应用修改</strong>
              <span>{pendingDiff.before} → {pendingDiff.after}</span>
              <small>revision {pendingDiff.nextRevision}</small>
              <button type="button" onClick={() => void undoPatch()} disabled={running}>
                Undo
              </button>
            </div>
          ) : null}
        </aside>
      </section>
    </main>
  );
}
