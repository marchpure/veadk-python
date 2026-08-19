import {
  AlertCircle,
  CheckCircle2,
  Database,
  FileText,
  GitBranch,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  createSemanticInstruction,
  createSemanticQuestionSqlPair,
  deleteSemanticInstruction,
  deleteSemanticQuestionSqlPair,
  getKnowledgeAssetBuildJob,
  getSemanticPackDetail,
  listKnowledgeAssetSnapshots,
  listSemanticBuildEvents,
  listSemanticInstructions,
  listSemanticQuestionSqlPairs,
  streamSemanticBuild,
  updateSemanticInstruction,
  updateSemanticQuestionSqlPair,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSnapshot,
  type KnowledgeAssetSource,
  type SemanticBuildEvent,
  type SemanticInstruction,
  type SemanticPackDetail,
  type SemanticQuestionSqlPair,
} from "../adk/knowledgeAssets";
import { formatJson } from "./knowledgeWorkbenchUtils";

function isStructuredSource(source: KnowledgeAssetSource): boolean {
  return ["database", "schema_snapshot", "oracle", "mysql", "postgres"].includes(
    String(source.source_type).toLowerCase(),
  );
}

function isDocumentSource(source: KnowledgeAssetSource): boolean {
  return ["document", "web", "feishu", "feishu_doc", "file", "pdf", "knowledge_resource", "local_web"].includes(
    String(source.source_type).toLowerCase(),
  );
}

function userFacingError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message && error.message !== "Failed to fetch") return error.message;
  return `${fallback} 请检查 Studio 后端是否可用，并刷新后重试。`;
}

function eventLabel(event: SemanticBuildEvent): string {
  const payload = event.payload || {};
  if (typeof payload.tool_name === "string") return payload.tool_name;
  if (typeof payload.artifact === "string") return payload.artifact;
  if (typeof payload.message === "string") return payload.message;
  return event.event_type;
}

function eventDetail(event: SemanticBuildEvent): string {
  const payload = event.payload || {};
  const summary = payload.summary;
  if (summary && typeof summary === "object") return JSON.stringify(summary);
  if (typeof payload.status === "string") return payload.status;
  if (Array.isArray(payload.blockers) && payload.blockers.length) return payload.blockers.map(String).join("; ");
  return "";
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function SemanticBuildPanel({
  spaceId,
  sources,
  assets,
  buildJobs,
  onRefresh,
}: {
  spaceId: string;
  sources: KnowledgeAssetSource[];
  assets: KnowledgeAssetMetadata[];
  buildJobs: KnowledgeAssetBuildJob[];
  onRefresh: () => void | Promise<void>;
}) {
  const databaseSources = useMemo(() => sources.filter(isStructuredSource), [sources]);
  const documentSources = useMemo(() => sources.filter(isDocumentSource), [sources]);
  const semanticAssets = assets.filter(
    (asset) => asset.capability_kind === "semantic_skill" || asset.asset_type === "semantic_model",
  );
  const [selectedSourceId, setSelectedSourceId] = useState(databaseSources[0]?.id || "");
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>(documentSources[0]?.id ? [documentSources[0].id] : []);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [snapshots, setSnapshots] = useState<KnowledgeAssetSnapshot[]>([]);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [name, setName] = useState("销售语义问数 Skill");
  const [intent, setIntent] = useState("围绕销售票数、销售额、门店、时间趋势生成聚合问数能力");
  const [targetDomain, setTargetDomain] = useState("sales");
  const [publish, setPublish] = useState(true);
  const [events, setEvents] = useState<SemanticBuildEvent[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [lastJob, setLastJob] = useState<KnowledgeAssetBuildJob | null>(null);
  const [error, setError] = useState("");
  const [pairs, setPairs] = useState<SemanticQuestionSqlPair[]>([]);
  const [instructions, setInstructions] = useState<SemanticInstruction[]>([]);
  const [pairDraft, setPairDraft] = useState({ question: "", sql: "", dialect: "ansi", notes: "" });
  const [instructionDraft, setInstructionDraft] = useState({ instruction: "", scope: "global", questions: "" });
  const [editingPairId, setEditingPairId] = useState("");
  const [editingInstructionId, setEditingInstructionId] = useState("");
  const [detail, setDetail] = useState<SemanticPackDetail | null>(null);
  const [detailTab, setDetailTab] = useState<"graph" | "evidence" | "alignments">("graph");

  const latestSemanticJob =
    lastJob ?? buildJobs.find((job) => job.job_type === "semantic_skill") ?? null;
  const selectedSource = databaseSources.find((source) => source.id === selectedSourceId) ?? null;
  const selectedDocs = selectedDocIds
    .map((id) => documentSources.find((source) => source.id === id))
    .filter((source): source is KnowledgeAssetSource => Boolean(source));
  const generatedAssetId =
    String(latestSemanticJob?.output?.semantic_pack_id || latestSemanticJob?.output?.semantic_skill_asset_id || latestSemanticJob?.result_skill_id || "") ||
    semanticAssets[0]?.asset_id ||
    "";
  const blockers = [
    ...arrayValue(latestSemanticJob?.output?.gate && objectValue(latestSemanticJob.output.gate).blockers).map(String),
    ...arrayValue(detail?.asset?.gate?.blockers).map(String),
  ].filter(Boolean);
  const modelConfigured = latestSemanticJob?.output?.agent_status !== "not_configured" && latestSemanticJob?.output?.validation_result !== false;

  useEffect(() => {
    setSelectedSourceId((current) => current || databaseSources[0]?.id || "");
  }, [databaseSources]);

  useEffect(() => {
    setSelectedDocIds((current) => (current.length ? current : documentSources[0]?.id ? [documentSources[0].id] : []));
  }, [documentSources]);

  useEffect(() => {
    if (!selectedSourceId) {
      setSnapshots([]);
      setSelectedSnapshotId("");
      return;
    }
    let cancelled = false;
    listKnowledgeAssetSnapshots({ sourceId: selectedSourceId })
      .then((items) => {
        if (cancelled) return;
        setSnapshots(items);
        setSelectedSnapshotId((current) => current || items[0]?.id || "");
      })
      .catch(() => {
        if (!cancelled) setSnapshots([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSourceId]);

  useEffect(() => {
    if (!spaceId) return;
    let cancelled = false;
    Promise.all([
      listSemanticQuestionSqlPairs({ spaceId }),
      listSemanticInstructions({ spaceId }),
    ])
      .then(([nextPairs, nextInstructions]) => {
        if (cancelled) return;
        setPairs(nextPairs);
        setInstructions(nextInstructions);
      })
      .catch((caught) => {
        if (!cancelled) setError(userFacingError(caught, "读取 few-shot / instruction 失败。"));
      });
    return () => {
      cancelled = true;
    };
  }, [spaceId]);

  useEffect(() => {
    if (!generatedAssetId) return;
    let cancelled = false;
    getSemanticPackDetail(generatedAssetId)
      .then((nextDetail) => {
        if (!cancelled) setDetail(nextDetail);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [generatedAssetId, latestSemanticJob?.updated_at]);

  useEffect(() => {
    const jobId = latestSemanticJob?.id;
    if (!jobId || submitting) return;
    let cancelled = false;
    listSemanticBuildEvents(jobId)
      .then((items) => {
        if (!cancelled) setEvents(items);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [latestSemanticJob?.id, latestSemanticJob?.updated_at, submitting]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceId) return;
    if (!selectedSourceId && selectedDocIds.length === 0) {
      setError("请选择数据库 source 或至少一份文档 source。");
      return;
    }
    setSubmitting(true);
    setError("");
    setEvents([]);
    setDetail(null);
    try {
      const streamEvents = await streamSemanticBuild(
        {
          space_id: spaceId,
          source_ids: [selectedSourceId, ...selectedDocIds].filter(Boolean),
          snapshot_ids: selectedSnapshotId ? [selectedSnapshotId] : [],
          name,
          intent,
          target_domain: targetDomain,
          publish,
        },
        (nextEvent) => setEvents((current) => [...current, nextEvent]),
      );
      const terminal = [...streamEvents].reverse().find((item) => item.event_type === "job_status");
      const jobId = String(terminal?.payload?.job_id || "");
      if (jobId) setLastJob(await getKnowledgeAssetBuildJob(jobId));
      await onRefresh();
      const packId = String(terminal?.payload?.semantic_pack_id || "");
      if (packId) setDetail(await getSemanticPackDetail(packId));
    } catch (caught) {
      setError(userFacingError(caught, "生成语义失败。"));
    } finally {
      setSubmitting(false);
    }
  }

  async function savePair(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceId || !pairDraft.question.trim() || !pairDraft.sql.trim()) return;
    const tables = pairDraft.sql.match(/\bfrom\s+([a-zA-Z0-9_\.]+)/i)?.[1]
      ? [pairDraft.sql.match(/\bfrom\s+([a-zA-Z0-9_\.]+)/i)![1]]
      : [];
    const saved = editingPairId
      ? await updateSemanticQuestionSqlPair(editingPairId, { ...pairDraft, tables })
      : await createSemanticQuestionSqlPair({ space_id: spaceId, ...pairDraft, tables });
    setPairs((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
    setPairDraft({ question: "", sql: "", dialect: "ansi", notes: "" });
    setEditingPairId("");
  }

  async function removePair(pair: SemanticQuestionSqlPair) {
    await deleteSemanticQuestionSqlPair(pair.id);
    setPairs((current) => current.filter((item) => item.id !== pair.id));
  }

  async function saveInstruction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceId || !instructionDraft.instruction.trim()) return;
    const input = {
      instruction: instructionDraft.instruction,
      scope: instructionDraft.scope,
      questions: instructionDraft.questions.split("\n").map((item) => item.trim()).filter(Boolean),
      is_default: instructionDraft.scope === "global",
    };
    const saved = editingInstructionId
      ? await updateSemanticInstruction(editingInstructionId, input)
      : await createSemanticInstruction({ space_id: spaceId, ...input });
    setInstructions((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
    setInstructionDraft({ instruction: "", scope: "global", questions: "" });
    setEditingInstructionId("");
  }

  async function removeInstruction(instruction: SemanticInstruction) {
    await deleteSemanticInstruction(instruction.id);
    setInstructions((current) => current.filter((item) => item.id !== instruction.id));
  }

  return (
    <section className="kc-semantic-agent-workbench" data-testid="semantic-builder-workbench">
      <header className="kc-semantic-agent-head">
        <div>
          <h2>Semantic Builder Workbench</h2>
          <p>从结构化 schema 与上下文文档生成可审计 Semantic Pack。</p>
        </div>
        <button type="button" onClick={() => void onRefresh()}>
          <RefreshCw className="kc-native-icon" />
          刷新
        </button>
      </header>

      <div className="kc-semantic-agent-layout">
        <aside className="kc-semantic-scope-panel">
          <section>
            <header>
              <Database className="kc-native-icon" />
              <strong>Data Scope</strong>
            </header>
            <button type="button" className="kc-scope-card" onClick={() => setScopeOpen((value) => !value)}>
              <span>结构化源</span>
              <strong>{selectedSource?.name || "未选择"}</strong>
              <small>{selectedSnapshotId ? "已锁定 snapshot" : selectedSourceId ? "使用最新 snapshot" : "文档-only 路径"}</small>
            </button>
            <div className="kc-scope-card is-static">
              <span>上下文材料</span>
              <strong>{selectedDocs.length ? `${selectedDocs.length} 份文档` : "未选择"}</strong>
              <small>{selectedDocs.map((item) => item.name).join("、") || "可用于 doc graph / 对齐"}</small>
            </div>
            {scopeOpen ? (
              <div className="kc-scope-picker" data-testid="semantic-scope-picker">
                <label>
                  <span>Structured source</span>
                  <select value={selectedSourceId} onChange={(event) => setSelectedSourceId(event.target.value)}>
                    <option value="">文档-only</option>
                    {databaseSources.map((source) => (
                      <option key={source.id} value={source.id}>{source.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Schema snapshot</span>
                  <select value={selectedSnapshotId} onChange={(event) => setSelectedSnapshotId(event.target.value)} disabled={!selectedSourceId}>
                    <option value="">使用最新 snapshot</option>
                    {snapshots.map((snapshot) => (
                      <option key={snapshot.id} value={snapshot.id}>{snapshot.metadata?.name || snapshot.id}</option>
                    ))}
                  </select>
                </label>
                <div className="kc-doc-source-list">
                  {documentSources.map((source) => (
                    <label key={source.id}>
                      <input
                        type="checkbox"
                        checked={selectedDocIds.includes(source.id)}
                        onChange={(event) => {
                          setSelectedDocIds((current) =>
                            event.target.checked ? [...current, source.id] : current.filter((id) => id !== source.id),
                          );
                        }}
                      />
                      <span>{source.name}</span>
                    </label>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          <FewShotPanel
            pairs={pairs}
            draft={pairDraft}
            editingId={editingPairId}
            onDraftChange={setPairDraft}
            onEdit={(pair) => {
              setEditingPairId(pair.id);
              setPairDraft({ question: pair.question, sql: pair.sql, dialect: pair.dialect, notes: pair.notes || "" });
            }}
            onDelete={(pair) => void removePair(pair)}
            onSubmit={(event) => void savePair(event)}
          />

          <InstructionPanel
            instructions={instructions}
            draft={instructionDraft}
            editingId={editingInstructionId}
            onDraftChange={setInstructionDraft}
            onEdit={(instruction) => {
              setEditingInstructionId(instruction.id);
              setInstructionDraft({ instruction: instruction.instruction, scope: instruction.scope, questions: instruction.questions.join("\n") });
            }}
            onDelete={(instruction) => void removeInstruction(instruction)}
            onSubmit={(event) => void saveInstruction(event)}
          />
        </aside>

        <main className="kc-semantic-agent-main">
          <form className="kc-semantic-agent-card" onSubmit={submit}>
            <header>
              <Sparkles className="kc-native-icon" />
              <strong>Semantic Builder Agent</strong>
            </header>
            <div className="kc-semantic-agent-form-grid">
              <label>
                <span>能力名称</span>
                <input value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label>
                <span>业务域</span>
                <input value={targetDomain} onChange={(event) => setTargetDomain(event.target.value)} />
              </label>
            </div>
            <label>
              <span>生成意图</span>
              <textarea value={intent} onChange={(event) => setIntent(event.target.value)} />
            </label>
            <label className="kc-native-checkbox">
              <input type="checkbox" checked={publish} onChange={(event) => setPublish(event.target.checked)} />
              <span>通过 gate 后发布到 Agent 能力选择器</span>
            </label>
            <button className="is-primary" type="submit" disabled={submitting || (!selectedSourceId && selectedDocIds.length === 0)}>
              {submitting ? <Loader2 className="kc-native-icon kc-spin" /> : <Sparkles className="kc-native-icon" />}
              生成语义
            </button>
            {error ? <div className="kc-semantic-error" role="alert"><AlertCircle className="kc-native-icon" />{error}</div> : null}
          </form>

          <section className="kc-semantic-agent-card">
            <header>
              <GitBranch className="kc-native-icon" />
              <strong>Agent transcript</strong>
            </header>
            <ol className="kc-agent-timeline" data-testid="semantic-agent-timeline">
              {events.length ? events.map((event, index) => (
                <li key={`${event.sequence || index}-${event.event_type}`} className={`is-${event.event_type}`}>
                  <span>{event.event_type}</span>
                  <strong>{eventLabel(event)}</strong>
                  <small>{eventDetail(event)}</small>
                </li>
              )) : <li><span>idle</span><strong>等待生成</strong><small>点击生成语义后显示 tool calls streaming</small></li>}
            </ol>
          </section>

          <SemanticArtifacts detail={detail} detailTab={detailTab} onDetailTabChange={setDetailTab} />
        </main>

        <aside className="kc-semantic-readiness-panel">
          <section className="kc-semantic-agent-card">
            <header>
              {blockers.length ? <AlertCircle className="kc-native-icon" /> : <CheckCircle2 className="kc-native-icon" />}
              <strong>Build Readiness</strong>
            </header>
            <dl className="kc-readiness-list">
              <div><dt>模型配置</dt><dd>{modelConfigured ? "configured" : "not_configured"}</dd></div>
              <div><dt>结构化源</dt><dd>{selectedSourceId ? "ready" : "doc-only"}</dd></div>
              <div><dt>文档</dt><dd>{selectedDocs.length}</dd></div>
              <div><dt>Few-shot</dt><dd>{pairs.length}</dd></div>
              <div><dt>Instructions</dt><dd>{instructions.length}</dd></div>
              <div><dt>发布</dt><dd>{String(detail?.asset.publish_state || latestSemanticJob?.output?.publish_state || "draft")}</dd></div>
            </dl>
            {blockers.length ? (
              <div className="kc-semantic-blocked" role="alert">
                <Wrench className="kc-native-icon" />
                <div>
                  <strong>Blocked</strong>
                  {blockers.slice(0, 5).map((reason) => <span key={reason}>{reason}</span>)}
                </div>
              </div>
            ) : null}
          </section>
        </aside>
      </div>
    </section>
  );
}

function FewShotPanel({
  pairs,
  draft,
  editingId,
  onDraftChange,
  onEdit,
  onDelete,
  onSubmit,
}: {
  pairs: SemanticQuestionSqlPair[];
  draft: { question: string; sql: string; dialect: string; notes: string };
  editingId: string;
  onDraftChange: (draft: { question: string; sql: string; dialect: string; notes: string }) => void;
  onEdit: (pair: SemanticQuestionSqlPair) => void;
  onDelete: (pair: SemanticQuestionSqlPair) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section className="kc-semantic-agent-card" data-testid="semantic-few-shot-panel">
      <header><FileText className="kc-native-icon" /><strong>Few-shot QA</strong></header>
      <form className="kc-compact-form" onSubmit={onSubmit}>
        <input aria-label="Question" placeholder="Question" value={draft.question} onChange={(event) => onDraftChange({ ...draft, question: event.target.value })} />
        <textarea aria-label="SQL" placeholder="SQL" value={draft.sql} onChange={(event) => onDraftChange({ ...draft, sql: event.target.value })} />
        <div className="kc-inline-fields">
          <input aria-label="Dialect" value={draft.dialect} onChange={(event) => onDraftChange({ ...draft, dialect: event.target.value })} />
          <input aria-label="Notes" placeholder="Notes" value={draft.notes} onChange={(event) => onDraftChange({ ...draft, notes: event.target.value })} />
        </div>
        <button type="submit"><Plus className="kc-native-icon" />{editingId ? "保存" : "添加"}</button>
      </form>
      <div className="kc-semantic-row-list">
        {pairs.map((pair) => (
          <article key={pair.id}>
            <button type="button" onClick={() => onEdit(pair)}><strong>{pair.question}</strong><span>{pair.dialect}</span></button>
            <button type="button" aria-label="Delete question SQL pair" onClick={() => onDelete(pair)}><Trash2 className="kc-native-icon" /></button>
          </article>
        ))}
      </div>
    </section>
  );
}

function InstructionPanel({
  instructions,
  draft,
  editingId,
  onDraftChange,
  onEdit,
  onDelete,
  onSubmit,
}: {
  instructions: SemanticInstruction[];
  draft: { instruction: string; scope: string; questions: string };
  editingId: string;
  onDraftChange: (draft: { instruction: string; scope: string; questions: string }) => void;
  onEdit: (instruction: SemanticInstruction) => void;
  onDelete: (instruction: SemanticInstruction) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section className="kc-semantic-agent-card" data-testid="semantic-instructions-panel">
      <header><FileText className="kc-native-icon" /><strong>Instructions</strong></header>
      <form className="kc-compact-form" onSubmit={onSubmit}>
        <textarea aria-label="Instruction" placeholder="Instruction" value={draft.instruction} onChange={(event) => onDraftChange({ ...draft, instruction: event.target.value })} />
        <div className="kc-inline-fields">
          <select aria-label="Scope" value={draft.scope} onChange={(event) => onDraftChange({ ...draft, scope: event.target.value })}>
            <option value="global">global</option>
            <option value="question_match">question_match</option>
            <option value="metric">metric</option>
          </select>
          <input aria-label="Questions" placeholder="matching questions" value={draft.questions} onChange={(event) => onDraftChange({ ...draft, questions: event.target.value })} />
        </div>
        <button type="submit"><Plus className="kc-native-icon" />{editingId ? "保存" : "添加"}</button>
      </form>
      <div className="kc-semantic-row-list">
        {instructions.map((instruction) => (
          <article key={instruction.id}>
            <button type="button" onClick={() => onEdit(instruction)}><strong>{instruction.instruction}</strong><span>{instruction.scope}</span></button>
            <button type="button" aria-label="Delete instruction" onClick={() => onDelete(instruction)}><Trash2 className="kc-native-icon" /></button>
          </article>
        ))}
      </div>
    </section>
  );
}

function SemanticArtifacts({
  detail,
  detailTab,
  onDetailTabChange,
}: {
  detail: SemanticPackDetail | null;
  detailTab: "graph" | "evidence" | "alignments";
  onDetailTabChange: (tab: "graph" | "evidence" | "alignments") => void;
}) {
  const docGraph = objectValue(detail?.doc_graph);
  const entities = arrayValue(docGraph.entities).filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  const relations = arrayValue(docGraph.relations).filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  const evidence = arrayValue(docGraph.evidence_fragments).filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
  const alignments = detail?.alignments || [];
  return (
    <section className="kc-semantic-agent-card kc-semantic-artifacts" data-testid="semantic-artifacts-panel">
      <header>
        <GitBranch className="kc-native-icon" />
        <strong>Graph / Evidence / Alignments</strong>
      </header>
      <div className="kc-artifact-tabs" role="tablist" aria-label="Semantic artifact views">
        {(["graph", "evidence", "alignments"] as const).map((tab) => (
          <button key={tab} type="button" className={detailTab === tab ? "is-active" : ""} onClick={() => onDetailTabChange(tab)}>{tab}</button>
        ))}
      </div>
      {detailTab === "graph" ? (
        <div className="kc-artifact-grid">
          <PreviewList title="Entities" items={entities.map((item) => String(item.name || item.id))} empty="暂无实体" />
          <PreviewList title="Relations" items={relations.map((item) => `${item.source_object_id || item.source} -> ${item.target_object_id || item.target}`)} empty="暂无关系" />
          <pre><code>{formatJson({ summary: docGraph.summary, ontology_candidates: docGraph.ontology_candidates })}</code></pre>
        </div>
      ) : detailTab === "evidence" ? (
        <div className="kc-artifact-grid">
          {evidence.length ? evidence.map((item) => <article key={String(item.id)}><strong>{String(item.title || item.source_id)}</strong><span>{String(item.text || "")}</span><small>{String(item.confidence || "")}</small></article>) : <em>暂无 evidence fragments</em>}
        </div>
      ) : (
        <div className="kc-artifact-grid">
          {alignments.length ? alignments.map((item) => <article key={String(item.id)}><strong>{`${String(item.doc_object_id)} -> ${String(item.mdl_object_ref)}`}</strong><span>{String(item.status)} · {String(item.alignment_type)}</span></article>) : <em>暂无 alignments</em>}
        </div>
      )}
    </section>
  );
}

function PreviewList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="kc-semantic-preview-list">
      <strong>{title}</strong>
      {items.length ? <div>{items.slice(0, 10).map((item) => <span key={item}>{item}</span>)}</div> : <em>{empty}</em>}
    </div>
  );
}
