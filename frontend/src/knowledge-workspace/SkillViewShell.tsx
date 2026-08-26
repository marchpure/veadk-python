import { useMemo, useState } from "react";
import {
  createRequestContext,
  type KnowledgeCommandResult,
} from "./production/ports";
import {
  getWorkspaceAdapter,
} from "./production/store";
import { activeSkillViewRevision } from "./production/data";
import { TrustedHtmlArtifactRenderer } from "./frozen-ui/components/MainArea/TrustedHtmlArtifactRenderer";
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

function projectionFromViewRevision(
  view: unknown,
  value: Record<string, unknown> = {},
): ViewProjection | null {
  if (!view || typeof view !== "object") return null;
  const viewRecord = view as Record<string, unknown>;
  const model = viewRecord.viewModel;
  const intent = viewRecord.intent;
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
    skillName:
      typeof modelRecord.title === "string" ? modelRecord.title : "Skill View",
    kind: typeof intentRecord.template === "string" ? intentRecord.template : "skill",
    template,
    skillVersion: String(
      value.draftRevision ?? intentRecord.skillRevision ?? "DRAFT",
    ),
    dataVersion:
      typeof goldenAsset?.id === "string"
        ? goldenAsset.id
        : (
            modelRecord.dataRef &&
            typeof modelRecord.dataRef === "object" &&
            typeof (modelRecord.dataRef as Record<string, unknown>).sha256 === "string"
          )
          ? (modelRecord.dataRef as Record<string, unknown>).sha256 as string
          : String(value.goldenAssetRevision ?? "revision"),
    dataTime:
      typeof viewRecord.createdAt === "string"
        ? viewRecord.createdAt
        : new Date().toISOString(),
    renderTime:
      typeof viewRecord.createdAt === "string"
        ? viewRecord.createdAt
        : new Date().toISOString(),
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

function viewRevisionFromResult(
  result: KnowledgeCommandResult,
): Record<string, unknown> | null {
  const value = result.result;
  if (!value || typeof value !== "object") return null;
  const direct = value.skillViewRevision;
  if (direct && typeof direct === "object") {
    return direct as Record<string, unknown>;
  }
  const operation = value.operation;
  const execution =
    operation && typeof operation === "object"
      ? (operation as Record<string, unknown>).execution_result
      : null;
  const nested =
    execution && typeof execution === "object"
      ? (execution as Record<string, unknown>).skillViewRevision
      : null;
  return nested && typeof nested === "object"
    ? nested as Record<string, unknown>
    : null;
}

function projectionFromResult(result: KnowledgeCommandResult): ViewProjection | null {
  const value = result.result;
  if (!value || typeof value !== "object") return null;
  return projectionFromViewRevision(viewRevisionFromResult(result), value);
}

export function SkillViewShell({
  draftId = "current-skill",
  revision = 1,
}: {
  draftId?: string;
  revision?: number;
}) {
  const restoredView =
    activeSkillViewRevision &&
    typeof activeSkillViewRevision.intent === "object" &&
    (activeSkillViewRevision.intent as Record<string, unknown>).skillId === draftId
      ? activeSkillViewRevision
      : null;
  const [viewRevision, setViewRevision] = useState<Record<string, unknown> | null>(
    restoredView,
  );
  const [projection, setProjection] = useState<ViewProjection | null>(() =>
    projectionFromViewRevision(restoredView),
  );
  const [message, setMessage] = useState(
    restoredView ? "已恢复最近一次执行结果。" : "选择一个 Skill 操作开始构建视图。",
  );
  const [running, setRunning] = useState(false);
  const [currentRevision, setCurrentRevision] = useState(revision);
  const [retryOperationId, setRetryOperationId] = useState<string | null>(null);
  const [assistantText, setAssistantText] = useState("");
  const [pendingDiff, setPendingDiff] = useState<{
    baseRevision: number;
    nextRevision: number;
    before: string;
    after: string;
  } | null>(null);
  const adapter = useMemo(() => getWorkspaceAdapter(), []);

  function applyExecutionResult(result: KnowledgeCommandResult, nextRevision: number) {
    const next = projectionFromResult(result);
    const nextView = viewRevisionFromResult(result);
    if (!next || !nextView) {
      throw new Error("执行结果缺少 immutable SkillViewRevision。");
    }
    setProjection(next);
    setViewRevision(nextView);
    setCurrentRevision(nextRevision);
  }

  async function executeAuthoringRevision(
    targetDraftId: string,
    targetRevision: number,
  ): Promise<void> {
    const result = await adapter.command(
      {
        command: "skill-authoring.execute",
        payload: { draftId: targetDraftId, revision: targetRevision },
      },
      createRequestContext(),
    );
    const value = result.result;
    const status =
      value && typeof value === "object" &&
      typeof (value as Record<string, unknown>).status === "string"
        ? (value as Record<string, unknown>).status
        : undefined;
    if (!result.accepted || status !== "succeeded") {
      throw new Error("Skill revision 执行失败。");
    }
    applyExecutionResult(result, targetRevision);
  }

  async function runEvaluation() {
    setRunning(true);
    setMessage("正在运行评测与策略门禁…");
    try {
      const result = await adapter.command(
        {
          command: "evaluation.run",
          payload: {
            targetId: draftId,
            suiteId: "default-step3",
            environment: "test",
            caseIds: [],
          },
        },
        createRequestContext(),
      );
      const next = projectionFromResult(result);
      if (next) setProjection(next);
      const nextView = viewRevisionFromResult(result);
      if (nextView) setViewRevision(nextView);
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

  async function runCurrentRevision() {
    if (running) return;
    setRunning(true);
    setMessage("正在执行 Skill…");
    try {
      await executeAuthoringRevision(draftId, currentRevision);
      setMessage("操作已完成。");
    } catch {
      setMessage("操作失败，请检查服务端返回的错误信息。");
    } finally {
      setRunning(false);
    }
  }

  async function proposeTitlePatch() {
    if (!assistantText.trim() || running) return;
    setRunning(true);
    setMessage("正在校验修改并重新执行 Skill…");
    try {
      const title = assistantText.trim().slice(0, 160);
      const before = projection?.skillName ?? "";
      const patched = await adapter.command(
        {
          command: "skill-authoring.patch",
          payload: {
            draftId,
            baseRevision: currentRevision,
            patch: { patch_type: "set_title", title },
          },
        },
        createRequestContext(),
      );
      const patchValue = patched.result;
      const draft =
        patchValue && typeof patchValue === "object" &&
        (patchValue as Record<string, unknown>).draft &&
        typeof (patchValue as Record<string, unknown>).draft === "object"
          ? (patchValue as Record<string, unknown>).draft as Record<string, unknown>
          : null;
      const nextDraftId = draft?.draftId ?? draft?.draft_id;
      const nextRevision = draft?.revision;
      if (!patched.accepted || typeof nextDraftId !== "string" || typeof nextRevision !== "number") {
        throw new Error("修改结果缺少新的 immutable Skill revision。");
      }
      await executeAuthoringRevision(nextDraftId, nextRevision);
      setPendingDiff({ baseRevision: currentRevision, nextRevision, before, after: title });
      setMessage("修改已应用并重新执行。");
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
      const patched = await adapter.command(
        {
          command: "skill-authoring.patch",
          payload: {
            draftId,
            baseRevision: currentRevision,
            patch: { patch_type: "set_title", title: pendingDiff.before },
          },
        },
        createRequestContext(),
      );
      const patchValue = patched.result;
      const draft =
        patchValue && typeof patchValue === "object" &&
        (patchValue as Record<string, unknown>).draft &&
        typeof (patchValue as Record<string, unknown>).draft === "object"
          ? (patchValue as Record<string, unknown>).draft as Record<string, unknown>
          : null;
      const nextDraftId = draft?.draftId ?? draft?.draft_id;
      const nextRevision = draft?.revision;
      if (!patched.accepted || typeof nextDraftId !== "string" || typeof nextRevision !== "number") {
        throw new Error("撤销结果缺少新的 immutable Skill revision。");
      }
      await executeAuthoringRevision(nextDraftId, nextRevision);
      setPendingDiff(null);
      setMessage("修改已撤销并重新执行。");
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
          <button type="button" onClick={() => void runCurrentRevision()} disabled={running}>
            {running ? "运行中…" : "执行 Skill"}
          </button>
          {retryOperationId ? (
            <button type="button" onClick={() => void retryBuilder()} disabled={running}>
              Retry Builder
            </button>
          ) : null}
          <button type="button" onClick={() => void runEvaluation()} disabled={running}>
            Evaluate
          </button>
          <button type="button" onClick={exportView} disabled={!projection || running}>
            Export
          </button>
          <button type="button" onClick={() => void shareView()} disabled={running}>
            Share to human
          </button>
          <button type="button" onClick={() => void runEvaluation()} disabled={running}>
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
          {viewRevision ? (
            <TrustedHtmlArtifactRenderer revision={viewRevision as any} />
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
          <label htmlFor="skill-assistant-input">修改标题</label>
          <textarea
            id="skill-assistant-input"
            value={assistantText}
            onChange={(event) => setAssistantText(event.target.value)}
            placeholder="输入要应用的新标题"
            rows={4}
          />
          <button type="button" onClick={() => void proposeTitlePatch()} disabled={running || !assistantText.trim()}>
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
