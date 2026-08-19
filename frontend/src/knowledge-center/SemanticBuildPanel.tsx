import "@xyflow/react/dist/style.css";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Database,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  createSemanticInstruction,
  createSemanticQuestionSqlPair,
  deleteSemanticInstruction,
  deleteSemanticQuestionSqlPair,
  getKnowledgeAssetBuildJob,
  getSemanticPackDetail,
  listKnowledgeAssetEvalSuites,
  listKnowledgeAssetSnapshots,
  listSemanticBuildEvents,
  listSemanticInstructions,
  listSemanticQuestionSqlPairs,
  runKnowledgeAssetEvaluation,
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
import {
  createWrenSemanticSourcePortViewModel,
} from "../features/knowledge-assets/adapters/wrenSemanticAdapter";
import {
  WrenModelingSourcePort,
  type WrenSourcePortSelection,
} from "../features/knowledge-assets/source-ports/wren/WrenModelingSourcePort";
import {
  arrayValue,
  objectValue,
} from "./knowledgeWorkbenchUtils";

type InspectorTab = "metadata" | "mdl" | "evidence" | "evals";
type TrainingTab = "training" | "governance";
type RunStageKey =
  | "inspect_schema"
  | "read_context_docs"
  | "propose_ontology"
  | "generate_mdl"
  | "validate_sql"
  | "link_evidence"
  | "publish_skill";

const runStages: Array<{ key: RunStageKey; label: string }> = [
  { key: "inspect_schema", label: "Inspect schema" },
  { key: "read_context_docs", label: "Read context docs" },
  { key: "propose_ontology", label: "Propose ontology" },
  { key: "generate_mdl", label: "Generate MDL" },
  { key: "validate_sql", label: "Validate SQL" },
  { key: "link_evidence", label: "Link evidence" },
  { key: "publish_skill", label: "Publish Skill" },
];

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
  if (typeof payload.stage === "string") return payload.stage;
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

function uniqueSemanticAssets(assets: KnowledgeAssetMetadata[]): KnowledgeAssetMetadata[] {
  const seen = new Set<string>();
  return assets.filter((asset) => {
    if (asset.capability_kind !== "semantic_skill" && asset.asset_type !== "semantic_model") return false;
    const key = `${asset.name.trim().toLowerCase()}:${asset.version || "v1"}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function semanticMdlFromDetail(detail: SemanticPackDetail | null): Record<string, unknown> {
  if (!detail) return {};
  const structured = objectValue(detail.structured_mdl);
  const docGraph = objectValue(detail.doc_graph);
  return {
    ...structured,
    evidence: [
      ...arrayValue(structured.evidence),
      ...arrayValue(docGraph.evidence_fragments),
    ],
  };
}

function assetWithDetail(asset: KnowledgeAssetMetadata | undefined, detail: SemanticPackDetail | null): KnowledgeAssetMetadata | undefined {
  if (!asset && !detail) return undefined;
  const base = detail?.asset ?? asset;
  if (!base) return undefined;
  const capabilityPackage = objectValue(base.capability_package);
  return {
    ...base,
    capability_package: {
      ...capabilityPackage,
      mdl: Object.keys(semanticMdlFromDetail(detail)).length
        ? semanticMdlFromDetail(detail)
        : capabilityPackage.mdl,
      doc_graph: detail?.doc_graph ?? capabilityPackage.doc_graph,
      alignments: detail?.alignments ?? capabilityPackage.alignments,
      few_shot: detail?.few_shot ?? capabilityPackage.few_shot,
      instructions: detail?.instructions ?? capabilityPackage.instructions,
    },
    provenance: {
      ...objectValue(base.provenance),
      ...objectValue(detail?.provenance),
    },
    sample_evidence: detail
      ? arrayValue(detail.doc_graph?.evidence_fragments).filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
      : base.sample_evidence,
  };
}

function stageState(stage: RunStageKey, events: SemanticBuildEvent[], latestJob: KnowledgeAssetBuildJob | null): "idle" | "running" | "done" | "blocked" {
  if (latestJob?.status === "failed" || latestJob?.status === "blocked") {
    const hasEvent = events.some((event) => eventMatchesStage(event, stage));
    return hasEvent ? "blocked" : "idle";
  }
  const index = runStages.findIndex((item) => item.key === stage);
  const lastMatchedIndex = Math.max(
    -1,
    ...events.map((event) => runStages.findIndex((item) => eventMatchesStage(event, item.key))).filter((value) => value >= 0),
  );
  if (lastMatchedIndex > index) return "done";
  if (lastMatchedIndex === index) return latestJob?.status === "succeeded" ? "done" : "running";
  if (latestJob?.status === "succeeded" && events.length) return "done";
  return "idle";
}

function eventMatchesStage(event: SemanticBuildEvent, stage: RunStageKey): boolean {
  const text = `${event.event_type} ${JSON.stringify(event.payload || {})}`.toLowerCase();
  const terms: Record<RunStageKey, string[]> = {
    inspect_schema: ["inspect", "schema", "snapshot"],
    read_context_docs: ["context", "doc", "document", "read"],
    propose_ontology: ["ontology", "candidate", "semantic_network"],
    generate_mdl: ["mdl", "model"],
    validate_sql: ["validate", "sql", "gate"],
    link_evidence: ["evidence", "alignment", "provenance"],
    publish_skill: ["publish", "skill"],
  };
  return terms[stage].some((term) => text.includes(term));
}

function buildMode(selectedSourceId: string, selectedDocIds: string[]): string {
  if (selectedSourceId && selectedDocIds.length) return "hybrid";
  if (selectedSourceId) return "structured-only";
  if (selectedDocIds.length) return "doc-only";
  return "unconfigured";
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
  const semanticAssets = useMemo(() => uniqueSemanticAssets(assets), [assets]);
  const [assetId, setAssetId] = useState(semanticAssets[0]?.asset_id || "");
  const [selectedSourceId, setSelectedSourceId] = useState(databaseSources[0]?.id || "");
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>(documentSources[0]?.id ? [documentSources[0].id] : []);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [snapshots, setSnapshots] = useState<KnowledgeAssetSnapshot[]>([]);
  const [dataContextOpen, setDataContextOpen] = useState(false);
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
  const [detail, setDetail] = useState<SemanticPackDetail | null>(null);
  const [selectedItem, setSelectedItem] = useState<WrenSourcePortSelection>(null);
  const [treeQuery, setTreeQuery] = useState("");
  const [inspector, setInspector] = useState<InspectorTab>("metadata");
  const [runDetailsOpen, setRunDetailsOpen] = useState(false);
  const [trainingOpen, setTrainingOpen] = useState(false);
  const [trainingTab, setTrainingTab] = useState<TrainingTab>("training");
  const [pairDraft, setPairDraft] = useState({ question: "", sql: "", dialect: "ansi", notes: "" });
  const [instructionDraft, setInstructionDraft] = useState({ instruction: "", scope: "global", questions: "" });
  const [editingPairId, setEditingPairId] = useState("");
  const [editingInstructionId, setEditingInstructionId] = useState("");
  const [evalMessage, setEvalMessage] = useState("");

  const selectedAsset = semanticAssets.find((asset) => asset.asset_id === assetId) ?? semanticAssets[0];
  const selectedSource = databaseSources.find((source) => source.id === selectedSourceId) ?? null;
  const selectedDocs = selectedDocIds
    .map((id) => documentSources.find((source) => source.id === id))
    .filter((source): source is KnowledgeAssetSource => Boolean(source));
  const latestSemanticJob =
    lastJob ??
    buildJobs.find((job) => job.job_type.includes("semantic") && (job.asset_id === selectedAsset?.asset_id || job.result_skill_id === selectedAsset?.asset_id)) ??
    buildJobs.find((job) => job.job_type.includes("semantic")) ??
    null;
  const effectiveAsset = assetWithDetail(selectedAsset, detail);
  const viewModel = useMemo(
    () =>
      createWrenSemanticSourcePortViewModel({
        sources,
        snapshots,
        assets: effectiveAsset
          ? [effectiveAsset, ...assets.filter((asset) => asset.asset_id !== effectiveAsset.asset_id)]
          : assets,
        buildJobs,
        selectedAssetId: effectiveAsset?.asset_id || assetId,
        lastJob: latestSemanticJob,
      }),
    [assetId, assets, buildJobs, effectiveAsset, latestSemanticJob, snapshots, sources],
  );
  const mode = buildMode(selectedSourceId, selectedDocIds);
  const statusText = submitting ? "running" : latestSemanticJob?.status || "idle";
  const publishState = detail?.asset.publish_state || selectedAsset?.publish_state || latestSemanticJob?.output?.publish_state || "draft";

  useEffect(() => {
    setSelectedSourceId((current) => current || databaseSources[0]?.id || "");
  }, [databaseSources]);

  useEffect(() => {
    setSelectedDocIds((current) => (current.length ? current : documentSources[0]?.id ? [documentSources[0].id] : []));
  }, [documentSources]);

  useEffect(() => {
    setAssetId((current) => current || semanticAssets[0]?.asset_id || "");
  }, [semanticAssets]);

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
        if (!cancelled) setError(userFacingError(caught, "读取 training examples / governance rules 失败。"));
      });
    return () => {
      cancelled = true;
    };
  }, [spaceId]);

  useEffect(() => {
    const detailId =
      assetId ||
      String(latestSemanticJob?.output?.semantic_pack_id || latestSemanticJob?.output?.semantic_skill_asset_id || latestSemanticJob?.result_skill_id || "");
    if (!detailId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    getSemanticPackDetail(detailId)
      .then((nextDetail) => {
        if (cancelled) return;
        setDetail(nextDetail);
        setAssetId((current) => current || nextDetail.semantic_pack_id || nextDetail.asset.asset_id);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [assetId, latestSemanticJob?.updated_at]);

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

  async function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!spaceId) return;
    if (!selectedSourceId && selectedDocIds.length === 0) {
      setError("请选择 structured source 或至少一份 context doc。");
      return;
    }
    setSubmitting(true);
    setRunDetailsOpen(true);
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
      const finalJob = jobId ? await pollBuildJob(jobId) : null;
      if (finalJob) setLastJob(finalJob);
      await onRefresh();
      const packId = String(
        finalJob?.output?.semantic_pack_id ||
        finalJob?.output?.semantic_skill_asset_id ||
        finalJob?.result_skill_id ||
        terminal?.payload?.semantic_pack_id ||
        "",
      );
      if (packId) {
        setAssetId(packId);
        setDetail(await getSemanticPackDetail(packId));
      }
    } catch (caught) {
      setError(userFacingError(caught, "生成语义失败。"));
    } finally {
      setSubmitting(false);
    }
  }

  async function pollBuildJob(jobId: string): Promise<KnowledgeAssetBuildJob> {
    let latest = await getKnowledgeAssetBuildJob(jobId);
    for (let attempt = 0; attempt < 14; attempt += 1) {
      if (!["queued", "running", "pending", "building"].includes(latest.status)) return latest;
      await new Promise((resolve) => window.setTimeout(resolve, attempt === 0 ? 250 : 900));
      latest = await getKnowledgeAssetBuildJob(jobId);
    }
    return latest;
  }

  async function savePair(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceId || !pairDraft.question.trim() || !pairDraft.sql.trim()) return;
    const fromMatch = pairDraft.sql.match(/\bfrom\s+([a-zA-Z0-9_\.]+)/i);
    const tables = fromMatch?.[1] ? [fromMatch[1]] : [];
    const saved = editingPairId
      ? await updateSemanticQuestionSqlPair(editingPairId, { ...pairDraft, tables })
      : await createSemanticQuestionSqlPair({ space_id: spaceId, semantic_pack_id: detail?.semantic_pack_id || null, ...pairDraft, tables });
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
      : await createSemanticInstruction({ space_id: spaceId, semantic_pack_id: detail?.semantic_pack_id || null, ...input });
    setInstructions((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
    setInstructionDraft({ instruction: "", scope: "global", questions: "" });
    setEditingInstructionId("");
  }

  async function removeInstruction(instruction: SemanticInstruction) {
    await deleteSemanticInstruction(instruction.id);
    setInstructions((current) => current.filter((item) => item.id !== instruction.id));
  }

  async function runEval() {
    const targetAssetId = viewModel.selectedAsset?.asset_id;
    if (!targetAssetId) {
      setEvalMessage("Generate or select a Semantic Skill before running eval.");
      setInspector("evals");
      return;
    }
    setEvalMessage("Running eval...");
    setInspector("evals");
    try {
      const suites = await listKnowledgeAssetEvalSuites({ spaceId, targetKind: "semantic_skill" });
      const suite = suites.find((item) => item.targetAssetId === targetAssetId) ?? suites[0];
      if (!suite) {
        setEvalMessage("No eval suite is configured for this Semantic Skill.");
        return;
      }
      const detail = await runKnowledgeAssetEvaluation({ suiteId: suite.id, targetAssetId });
      setEvalMessage(`Eval ${detail.run.status}: score ${detail.run.score}`);
    } catch (caught) {
      setEvalMessage(userFacingError(caught, "运行测评失败。"));
    }
  }

  const openTraining = (tab: TrainingTab) => {
    setTrainingTab(tab);
    setTrainingOpen(true);
  };

  return (
    <section className="kc-semantic-workspace" data-testid="semantic-builder-workspace">
      <form className="kc-semantic-builder-bar" onSubmit={submit}>
        <label className="kc-builder-control">
          <span>Semantic Skill</span>
          <select value={viewModel.selectedAsset?.asset_id || ""} onChange={(event) => setAssetId(event.target.value)}>
            <option value="">New Skill</option>
            {semanticAssets.map((asset) => (
              <option key={asset.asset_id} value={asset.asset_id}>{asset.name} · {asset.version || "v1"}</option>
            ))}
          </select>
        </label>
        <DataContextSelector
          open={dataContextOpen}
          mode={mode}
          selectedSource={selectedSource}
          selectedDocs={selectedDocs}
          databaseSources={databaseSources}
          documentSources={documentSources}
          snapshots={snapshots}
          selectedSourceId={selectedSourceId}
          selectedSnapshotId={selectedSnapshotId}
          selectedDocIds={selectedDocIds}
          onOpenChange={setDataContextOpen}
          onSourceChange={setSelectedSourceId}
          onSnapshotChange={setSelectedSnapshotId}
          onDocIdsChange={setSelectedDocIds}
        />
        <label className="kc-builder-control kc-builder-name">
          <span>Skill name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <button className="is-primary" type="submit" disabled={submitting || mode === "unconfigured"}>
          {submitting ? <Loader2 className="kc-native-icon kc-spin" /> : <Sparkles className="kc-native-icon" />}
          生成语义
        </button>
        <span className={`kc-builder-chip is-${statusText}`}>{statusText}</span>
        <span className="kc-builder-chip">{String(publishState)}</span>
        <button type="button" onClick={() => void onRefresh()} aria-label="Refresh Semantic workspace">
          <RefreshCw className="kc-native-icon" />
        </button>
      </form>

      {error ? (
        <div className="kc-workbench-alert" role="alert">
          <AlertCircle className="kc-native-icon" />
          <span>{error}</span>
        </div>
      ) : null}
      {evalMessage ? (
        <div className="kc-workbench-alert" role="status">
          <ShieldCheck className="kc-native-icon" />
          <span>{evalMessage}</span>
        </div>
      ) : null}

      <WrenModelingSourcePort
        viewModel={viewModel}
        treeMode="semantic"
        onTreeModeChange={() => undefined}
        query={treeQuery}
        onQueryChange={setTreeQuery}
        selectedItem={selectedItem}
        onSelect={setSelectedItem}
        inspector={inspector}
        onInspectorChange={setInspector}
        onSelectAsset={setAssetId}
        onSelectSource={setSelectedSourceId}
        onSelectSnapshot={setSelectedSnapshotId}
        onRefresh={() => void onRefresh()}
        onOpenRunDetails={() => setRunDetailsOpen(true)}
        onOpenTraining={openTraining}
        onRunEval={() => void runEval()}
        intent={intent}
        targetDomain={targetDomain}
        publish={publish}
        onIntentChange={setIntent}
        onTargetDomainChange={setTargetDomain}
        onPublishChange={setPublish}
      />

      {runDetailsOpen ? (
        <RunDetailsDrawer
          events={events}
          latestJob={latestSemanticJob}
          detail={detail}
          onClose={() => setRunDetailsOpen(false)}
        />
      ) : null}

      {trainingOpen ? (
        <TrainingDrawer
          tab={trainingTab}
          pairs={pairs}
          instructions={instructions}
          pairDraft={pairDraft}
          instructionDraft={instructionDraft}
          editingPairId={editingPairId}
          editingInstructionId={editingInstructionId}
          onTabChange={setTrainingTab}
          onClose={() => setTrainingOpen(false)}
          onPairDraftChange={setPairDraft}
          onInstructionDraftChange={setInstructionDraft}
          onPairSubmit={(event) => void savePair(event)}
          onInstructionSubmit={(event) => void saveInstruction(event)}
          onPairEdit={(pair) => {
            setEditingPairId(pair.id);
            setPairDraft({ question: pair.question, sql: pair.sql, dialect: pair.dialect, notes: pair.notes || "" });
          }}
          onInstructionEdit={(instruction) => {
            setEditingInstructionId(instruction.id);
            setInstructionDraft({ instruction: instruction.instruction, scope: instruction.scope, questions: instruction.questions.join("\n") });
          }}
          onPairDelete={(pair) => void removePair(pair)}
          onInstructionDelete={(instruction) => void removeInstruction(instruction)}
        />
      ) : null}
    </section>
  );
}

function DataContextSelector({
  open,
  mode,
  selectedSource,
  selectedDocs,
  databaseSources,
  documentSources,
  snapshots,
  selectedSourceId,
  selectedSnapshotId,
  selectedDocIds,
  onOpenChange,
  onSourceChange,
  onSnapshotChange,
  onDocIdsChange,
}: {
  open: boolean;
  mode: string;
  selectedSource: KnowledgeAssetSource | null;
  selectedDocs: KnowledgeAssetSource[];
  databaseSources: KnowledgeAssetSource[];
  documentSources: KnowledgeAssetSource[];
  snapshots: KnowledgeAssetSnapshot[];
  selectedSourceId: string;
  selectedSnapshotId: string;
  selectedDocIds: string[];
  onOpenChange: (value: boolean) => void;
  onSourceChange: (value: string) => void;
  onSnapshotChange: (value: string) => void;
  onDocIdsChange: (value: string[]) => void;
}) {
  return (
    <div className="kc-data-context-selector">
      <button type="button" className="kc-data-context-trigger" onClick={() => onOpenChange(!open)}>
        <Database className="kc-native-icon" />
        <span>
          <strong>{selectedSource?.name || "No structured source"}</strong>
          <em>{selectedDocs.length ? `${selectedDocs.length} context docs` : "No context docs"} · {mode}</em>
        </span>
        <ChevronDown className="kc-native-icon" />
      </button>
      {open ? (
        <div className="kc-data-context-popover" data-testid="semantic-data-context-selector">
          <label>
            <span>Structured source</span>
            <select value={selectedSourceId} onChange={(event) => onSourceChange(event.target.value)}>
              <option value="">Doc-only</option>
              {databaseSources.map((source) => (
                <option key={source.id} value={source.id}>{source.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Schema snapshot</span>
            <select value={selectedSnapshotId} onChange={(event) => onSnapshotChange(event.target.value)} disabled={!selectedSourceId}>
              <option value="">Latest snapshot</option>
              {snapshots.map((snapshot) => (
                <option key={snapshot.id} value={snapshot.id}>{snapshot.metadata?.name || snapshot.id}</option>
              ))}
            </select>
          </label>
          <section>
            <span>Context docs</span>
            <div className="kc-doc-source-list">
              {documentSources.length ? documentSources.map((source) => (
                <label key={source.id}>
                  <input
                    type="checkbox"
                    checked={selectedDocIds.includes(source.id)}
                    onChange={(event) => {
                      onDocIdsChange(
                        event.target.checked
                          ? [...selectedDocIds, source.id]
                          : selectedDocIds.filter((id) => id !== source.id),
                      );
                    }}
                  />
                  <span>{source.name}</span>
                </label>
              )) : <em>No document sources</em>}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function RunDetailsDrawer({
  events,
  latestJob,
  detail,
  onClose,
}: {
  events: SemanticBuildEvent[];
  latestJob: KnowledgeAssetBuildJob | null;
  detail: SemanticPackDetail | null;
  onClose: () => void;
}) {
  return (
    <div className="kc-semantic-drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside className="kc-semantic-side-drawer" role="dialog" aria-modal="true" aria-label="Semantic run details" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>运行详情</strong>
            <span>{latestJob?.id || "No build job yet"}</span>
          </div>
          <button type="button" onClick={onClose} aria-label="Close run details"><X className="kc-native-icon" /></button>
        </header>
        <ol className="kc-semantic-stage-list">
          {runStages.map((stage) => (
            <li key={stage.key} className={`is-${stageState(stage.key, events, latestJob)}`}>
              <span>{stage.label}</span>
              {stageState(stage.key, events, latestJob) === "done" ? <CheckCircle2 className="kc-native-icon" /> : null}
            </li>
          ))}
        </ol>
        <section className="kc-run-detail-summary">
          <h3>Persisted artifacts</h3>
          <dl>
            <div><dt>Job</dt><dd>{latestJob?.status || "idle"}</dd></div>
            <div><dt>Semantic pack</dt><dd>{detail?.semantic_pack_id || "pending"}</dd></div>
            <div><dt>MDL</dt><dd>{Object.keys(objectValue(detail?.structured_mdl)).length ? "persisted" : "pending"}</dd></div>
            <div><dt>Evidence</dt><dd>{arrayValue(detail?.doc_graph?.evidence_fragments).length}</dd></div>
            <div><dt>Alignments</dt><dd>{detail?.alignments.length || 0}</dd></div>
          </dl>
        </section>
        <section>
          <h3>Transcript / tool calls</h3>
          <ol className="kc-agent-timeline" data-testid="semantic-agent-timeline">
            {events.length ? events.map((event, index) => (
              <li key={`${event.sequence || index}-${event.event_type}`} className={`is-${event.event_type}`}>
                <span>{event.event_type}</span>
                <strong>{eventLabel(event)}</strong>
                <small>{eventDetail(event)}</small>
              </li>
            )) : <li><span>idle</span><strong>等待生成</strong><small>点击生成语义后显示 stream events</small></li>}
          </ol>
        </section>
      </aside>
    </div>
  );
}

function TrainingDrawer({
  tab,
  pairs,
  instructions,
  pairDraft,
  instructionDraft,
  editingPairId,
  editingInstructionId,
  onTabChange,
  onClose,
  onPairDraftChange,
  onInstructionDraftChange,
  onPairSubmit,
  onInstructionSubmit,
  onPairEdit,
  onInstructionEdit,
  onPairDelete,
  onInstructionDelete,
}: {
  tab: TrainingTab;
  pairs: SemanticQuestionSqlPair[];
  instructions: SemanticInstruction[];
  pairDraft: { question: string; sql: string; dialect: string; notes: string };
  instructionDraft: { instruction: string; scope: string; questions: string };
  editingPairId: string;
  editingInstructionId: string;
  onTabChange: (tab: TrainingTab) => void;
  onClose: () => void;
  onPairDraftChange: (draft: { question: string; sql: string; dialect: string; notes: string }) => void;
  onInstructionDraftChange: (draft: { instruction: string; scope: string; questions: string }) => void;
  onPairSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onInstructionSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onPairEdit: (pair: SemanticQuestionSqlPair) => void;
  onInstructionEdit: (instruction: SemanticInstruction) => void;
  onPairDelete: (pair: SemanticQuestionSqlPair) => void;
  onInstructionDelete: (instruction: SemanticInstruction) => void;
}) {
  return (
    <div className="kc-semantic-drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside className="kc-semantic-side-drawer" role="dialog" aria-modal="true" aria-label="Semantic training examples" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>Training & Governance</strong>
            <span>Persisted examples and rules for Semantic Builder.</span>
          </div>
          <button type="button" onClick={onClose} aria-label="Close training drawer"><X className="kc-native-icon" /></button>
        </header>
        <div className="adm-metadata-tabs" role="tablist">
          <button type="button" className={tab === "training" ? "is-active" : ""} onClick={() => onTabChange("training")}>Training Examples</button>
          <button type="button" className={tab === "governance" ? "is-active" : ""} onClick={() => onTabChange("governance")}>Governance Rules</button>
        </div>
        {tab === "training" ? (
          <section className="kc-training-panel" data-testid="semantic-few-shot-panel">
            <form className="kc-compact-form" onSubmit={onPairSubmit}>
              <input aria-label="Question" placeholder="Question" value={pairDraft.question} onChange={(event) => onPairDraftChange({ ...pairDraft, question: event.target.value })} />
              <textarea aria-label="SQL" placeholder="Wren SQL / ANSI SQL" value={pairDraft.sql} onChange={(event) => onPairDraftChange({ ...pairDraft, sql: event.target.value })} />
              <div className="kc-inline-fields">
                <input aria-label="Dialect" value={pairDraft.dialect} onChange={(event) => onPairDraftChange({ ...pairDraft, dialect: event.target.value })} />
                <input aria-label="Notes" placeholder="Notes" value={pairDraft.notes} onChange={(event) => onPairDraftChange({ ...pairDraft, notes: event.target.value })} />
              </div>
              <button type="submit"><Plus className="kc-native-icon" />{editingPairId ? "Save" : "Add question-SQL pair"}</button>
            </form>
            <RowList
              items={pairs}
              empty="No training examples"
              title={(pair) => pair.question}
              detail={(pair) => pair.dialect}
              onEdit={onPairEdit}
              onDelete={onPairDelete}
            />
          </section>
        ) : (
          <section className="kc-training-panel" data-testid="semantic-instructions-panel">
            <form className="kc-compact-form" onSubmit={onInstructionSubmit}>
              <textarea aria-label="Instruction" placeholder="Rule that Semantic Builder should follow" value={instructionDraft.instruction} onChange={(event) => onInstructionDraftChange({ ...instructionDraft, instruction: event.target.value })} />
              <div className="kc-inline-fields">
                <select aria-label="Scope" value={instructionDraft.scope} onChange={(event) => onInstructionDraftChange({ ...instructionDraft, scope: event.target.value })}>
                  <option value="global">global</option>
                  <option value="question_match">question_match</option>
                  <option value="metric">metric</option>
                </select>
                <input aria-label="Questions" placeholder="matching questions, one per line" value={instructionDraft.questions} onChange={(event) => onInstructionDraftChange({ ...instructionDraft, questions: event.target.value })} />
              </div>
              <button type="submit"><Plus className="kc-native-icon" />{editingInstructionId ? "Save" : "Add instruction"}</button>
            </form>
            <RowList
              items={instructions}
              empty="No governance rules"
              title={(instruction) => instruction.instruction}
              detail={(instruction) => instruction.scope}
              onEdit={onInstructionEdit}
              onDelete={onInstructionDelete}
            />
          </section>
        )}
      </aside>
    </div>
  );
}

function RowList<T>({
  items,
  empty,
  title,
  detail,
  onEdit,
  onDelete,
}: {
  items: T[];
  empty: string;
  title: (item: T) => string;
  detail: (item: T) => string;
  onEdit: (item: T) => void;
  onDelete: (item: T) => void;
}) {
  return (
    <div className="kc-semantic-row-list">
      {items.length ? items.map((item, index) => (
        <article key={String((item as { id?: string }).id || index)}>
          <button type="button" onClick={() => onEdit(item)}><strong>{title(item)}</strong><span>{detail(item)}</span></button>
          <button type="button" aria-label="Delete row" onClick={() => onDelete(item)}><Trash2 className="kc-native-icon" /></button>
        </article>
      )) : <em>{empty}</em>}
    </div>
  );
}
