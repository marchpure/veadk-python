import dagre from "@dagrejs/dagre";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertCircle,
  Braces,
  CheckCircle2,
  CircleDot,
  Database,
  FileJson,
  GitBranch,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Table2,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  buildSemanticSkill,
  getKnowledgeAssetBuildJob,
  listKnowledgeAssetSnapshots,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSnapshot,
  type KnowledgeAssetSource,
} from "../adk/knowledgeAssets";
import {
  arrayValue,
  formatJson,
  labelFrom,
  mdlToModelingViewModel,
  objectValue,
  semanticMdl,
  type WrenModelingField,
  type WrenModelingMetric,
  type WrenModelingModel,
  type WrenModelingRelationship,
  type WrenModelingViewModel,
} from "./knowledgeWorkbenchUtils";

type SemanticNodeData = {
  label: string;
  kind: "model" | "table" | "view";
  table?: string;
  fields: Array<Record<string, unknown>>;
  metrics: Array<Record<string, unknown>>;
  dimensions: Array<Record<string, unknown>>;
  description?: string;
  source?: Record<string, unknown>;
  edgeHoverRole?: "source" | "target";
  highlightedFieldNames?: string[];
};
type SemanticGraphNodeType = Node<SemanticNodeData, "semanticNode">;
type SemanticGraphEdgeType = Edge<Record<string, unknown>>;

type SelectedGraphItem =
  | { type: "node"; id: string; data: SemanticNodeData }
  | { type: "edge"; id: string; data: Record<string, unknown> }
  | { type: "field"; id: string; data: WrenModelingField; model: WrenModelingModel }
  | { type: "metric"; id: string; data: WrenModelingMetric }
  | { type: "relationship"; id: string; data: WrenModelingRelationship };

export function SemanticModelingWorkbench({
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
  const semanticAssets = assets.filter(
    (asset) => asset.asset_type === "semantic_model" && asset.capability_kind === "semantic_skill",
  );
  const [assetId, setAssetId] = useState(semanticAssets[0]?.asset_id || "");
  const selectedAsset =
    semanticAssets.find((asset) => asset.asset_id === assetId) ?? semanticAssets[0] ?? null;
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [snapshots, setSnapshots] = useState<KnowledgeAssetSnapshot[]>([]);
  const [snapshotState, setSnapshotState] = useState<"idle" | "loading" | "error">("idle");
  const [treeMode, setTreeMode] = useState<"source" | "snapshot" | "semantic">("semantic");
  const [treeQuery, setTreeQuery] = useState("");
  const [selectedItem, setSelectedItem] = useState<SelectedGraphItem | null>(null);
  const [name, setName] = useState("销售语义问数 Skill");
  const [intent, setIntent] = useState("围绕销售票数、销售额、门店、时间趋势生成聚合问数能力");
  const [targetDomain, setTargetDomain] = useState("sales");
  const [publish, setPublish] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastJob, setLastJob] = useState<KnowledgeAssetBuildJob | null>(null);
  const [inspector, setInspector] = useState<"metadata" | "mdl" | "evals">("metadata");
  const [mobilePane, setMobilePane] = useState<"tree" | "canvas" | "metadata">("canvas");
  const [treeCollapsed, setTreeCollapsed] = useState(false);

  const databaseSources = useMemo(
    () =>
      sources.filter((source) =>
        ["database", "schema_snapshot"].includes(String(source.source_type).toLowerCase()),
      ),
    [sources],
  );
  const mdl = useMemo(() => semanticMdl(selectedAsset), [selectedAsset]);
  const modelingView = useMemo(() => mdlToModelingViewModel(mdl), [mdl]);
  const graph = useMemo(() => buildSemanticGraph(mdl), [mdl]);
  const hasMdl = Boolean(Object.keys(mdl).length);
  const latestJob =
    lastJob ??
    buildJobs.find((job) => job.job_type.includes("semantic") && job.asset_id === selectedAsset?.asset_id) ??
    buildJobs.find((job) => job.job_type.includes("semantic")) ??
    null;

  useEffect(() => {
    setSelectedSourceId((current) => {
      if (current && databaseSources.some((source) => source.id === current)) return current;
      return databaseSources[0]?.id || "";
    });
  }, [databaseSources]);

  useEffect(() => {
    if (!selectedSourceId) {
      setSnapshots([]);
      setSelectedSnapshotId("");
      setSnapshotState("idle");
      return;
    }
    let cancelled = false;
    setSnapshotState("loading");
    listKnowledgeAssetSnapshots({ sourceId: selectedSourceId })
      .then((items) => {
        if (cancelled) return;
        setSnapshots(items);
        setSelectedSnapshotId(items[0]?.id || "");
        setSnapshotState("idle");
      })
      .catch(() => {
        if (cancelled) return;
        setSnapshotState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSourceId]);

  useEffect(() => {
    setAssetId((current) => current || semanticAssets[0]?.asset_id || "");
  }, [semanticAssets]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceId || !selectedSourceId) {
      setError("请选择资产空间和数据库 source。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const job = await buildSemanticSkill({
        space_id: spaceId,
        source_ids: [selectedSourceId],
        snapshot_ids: selectedSnapshotId ? [selectedSnapshotId] : [],
        name,
        intent,
        target_domain: targetDomain,
        publish,
      });
      setLastJob(job);
      const finalJob = await pollBuildJob(job.id);
      setLastJob(finalJob);
      await onRefresh();
      if (finalJob.result_skill_id) setAssetId(finalJob.result_skill_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成语义 Skill 失败。");
    } finally {
      setBusy(false);
    }
  }

  async function pollBuildJob(jobId: string): Promise<KnowledgeAssetBuildJob> {
    let latest = await getKnowledgeAssetBuildJob(jobId);
    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (!["queued", "running", "pending", "building"].includes(latest.status)) {
        return latest;
      }
      await new Promise((resolve) => window.setTimeout(resolve, attempt === 0 ? 250 : 900));
      latest = await getKnowledgeAssetBuildJob(jobId);
    }
    return latest;
  }

  return (
    <section className="kc-semantic-workbench" data-testid="semantic-modeling-workbench">
      <header className="kc-workbench-toolbar">
        <div>
          <h2>语义构建</h2>
          <span>模型树、关系图、MDL 和评测证据在同一原生工作台内联动</span>
        </div>
        <form className="kc-workbench-toolbar__controls" onSubmit={submit}>
          <select
            aria-label="Semantic Skill"
            value={selectedAsset?.asset_id || ""}
            onChange={(event) => setAssetId(event.target.value)}
          >
            <option value="">Semantic Skill</option>
            {semanticAssets.map((asset) => (
              <option key={asset.asset_id} value={asset.asset_id}>
                {asset.name} · {asset.version || "v1"}
              </option>
            ))}
          </select>
          <select value={selectedSourceId} onChange={(event) => setSelectedSourceId(event.target.value)}>
            <option value="">Source</option>
            {databaseSources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
          <select
            value={selectedSnapshotId}
            onChange={(event) => setSelectedSnapshotId(event.target.value)}
            disabled={!selectedSourceId || snapshotState === "loading"}
          >
            <option value="">{snapshotState === "loading" ? "读取 Snapshot" : "Snapshot"}</option>
            {snapshots.map((snapshot) => (
              <option key={snapshot.id} value={snapshot.id}>
                {snapshot.metadata?.name || snapshot.id}
              </option>
            ))}
          </select>
          <input value={name} onChange={(event) => setName(event.target.value)} aria-label="语义 Skill 名称" />
          <button type="submit" disabled={busy}>
            {busy ? <Loader2 className="kc-native-icon kc-spin" /> : <Sparkles className="kc-native-icon" />}
            生成语义
          </button>
          <button type="button" disabled={!selectedAsset}>
            <ShieldCheck className="kc-native-icon" />
            发布
          </button>
          <button type="button" onClick={() => void onRefresh()}>
            <RefreshCw className="kc-native-icon" />
            刷新
          </button>
          <button type="button" onClick={() => setInspector("mdl")}>
            <FileJson className="kc-native-icon" />
            查看 MDL
          </button>
          <button type="button" onClick={() => setInspector("evals")}>
            <CheckCircle2 className="kc-native-icon" />
            查看评测
          </button>
        </form>
      </header>
      <div className="kc-agent-status-strip">
        <StatusChip label="构建状态" value={latestJob ? latestJob.status : "idle"} />
        <StatusChip label="Agent" value={String(latestJob?.output?.agent_status || selectedAsset?.provenance?.agent_status || "unknown")} />
        <StatusChip label="Runner" value={String(latestJob?.output?.runner_backend || selectedAsset?.provenance?.runner_backend || "pending")} />
        <StatusChip label="Mode" value={String(latestJob?.output?.generation_mode || selectedAsset?.capabilities?.generation_mode || "unknown")} />
        <StatusChip label="Blocked" value={blockedReason(latestJob, selectedAsset)} />
      </div>
      {!databaseSources.length ? (
        <SemanticWorkbenchState
          title="需要数据库或 Schema Snapshot"
          text="先在数据源页登记数据库 source 或导入 schema snapshot，之后可在这里生成 Semantic Skill。"
        />
      ) : null}
      {error || latestJob?.status === "blocked" ? (
        <div className="kc-workbench-alert" role="alert">
          <AlertCircle className="kc-native-icon" />
          <span>{error || String(latestJob?.error?.message || "构建被阻塞，请查看 Agent 状态。")}</span>
        </div>
      ) : null}
      <div className="kc-mobile-workbench-tabs" role="tablist" aria-label="语义移动端视图">
        {(["tree", "canvas", "metadata"] as const).map((pane) => (
          <button
            key={pane}
            type="button"
            className={mobilePane === pane ? "is-active" : ""}
            disabled={pane === "tree" && treeCollapsed}
            onClick={() => setMobilePane(pane)}
          >
            {pane === "tree" ? "模型树" : pane === "canvas" ? "画布" : "详情"}
          </button>
        ))}
        <button
          type="button"
          className="kc-mobile-workbench-tabs__toggle"
          onClick={() =>
            setTreeCollapsed((current) => {
              if (!current) setMobilePane("canvas");
              return !current;
            })
          }
        >
          {treeCollapsed ? "展开模型树" : "收起模型树"}
        </button>
      </div>
      <div className={`kc-semantic-layout is-mobile-${mobilePane}${treeCollapsed ? " is-tree-collapsed" : ""}`}>
        <SemanticModelTree
          mode={treeMode}
          onModeChange={setTreeMode}
          query={treeQuery}
          onQueryChange={setTreeQuery}
          sources={databaseSources}
          snapshots={snapshots}
          assets={semanticAssets}
          selectedAssetId={selectedAsset?.asset_id || ""}
          onSelectAsset={setAssetId}
          onSelectGraphNode={(id) => {
            const node = graph.nodes.find((item) => item.id === id);
            if (node) setSelectedItem({ type: "node", id: node.id, data: node.data });
          }}
          onSelectField={(model, field) =>
            setSelectedItem({ type: "field", id: `${model.id}:${field.id}`, data: field, model })
          }
          onSelectMetric={(metric) => setSelectedItem({ type: "metric", id: metric.id, data: metric })}
          onSelectRelationship={(relationship) =>
            setSelectedItem({ type: "relationship", id: relationship.id, data: relationship })
          }
          modelingView={modelingView}
        />
        <SemanticGraphCanvas
          graph={graph}
          onSelect={setSelectedItem}
          emptyState={
            hasMdl
              ? null
              : selectedAsset
                ? "当前 Semantic Skill 还没有可渲染 MDL。查看构建任务或重新生成。"
                : "选择或生成 Semantic Skill 后，模型、表、字段和关系会在画布中渲染。"
          }
        />
        <SemanticMetadataDrawer
          selectedItem={selectedItem}
          asset={selectedAsset}
          mdl={mdl}
          modelingView={modelingView}
          inspector={inspector}
          onInspectorChange={setInspector}
          intent={intent}
          targetDomain={targetDomain}
          publish={publish}
          onIntentChange={setIntent}
          onTargetDomainChange={setTargetDomain}
          onPublishChange={setPublish}
        />
      </div>
    </section>
  );
}

function SemanticGraphCanvas({
  graph,
  onSelect,
  emptyState,
}: {
  graph: { nodes: SemanticGraphNodeType[]; edges: SemanticGraphEdgeType[] };
  onSelect: (item: SelectedGraphItem | null) => void;
  emptyState: string | null;
}) {
  const [hoveredEdgeId, setHoveredEdgeId] = useState("");
  const nodeTypes = useMemo(() => ({ semanticNode: SemanticGraphNode }), []);
  const hoveredEdge = graph.edges.find((edge) => edge.id === hoveredEdgeId);
  const hoveredFields = hoveredEdge ? relationshipFieldHighlights(hoveredEdge.data ?? {}) : null;
  const nodes: SemanticGraphNodeType[] = graph.nodes.map((node) => {
    if (!hoveredEdge || !hoveredFields) return node;
    if (node.id !== hoveredEdge.source && node.id !== hoveredEdge.target) return node;
    const role = node.id === hoveredEdge.source ? "source" : "target";
    return {
      ...node,
      className: `is-edge-${role}`,
      data: {
        ...node.data,
        edgeHoverRole: role,
        highlightedFieldNames: role === "source" ? hoveredFields.source : hoveredFields.target,
      },
    };
  });
  const edges: SemanticGraphEdgeType[] = graph.edges.map((edge) => ({
    ...edge,
    className: edge.id === hoveredEdgeId ? "is-hovered" : "",
    animated: edge.id === hoveredEdgeId,
    label: edge.id === hoveredEdgeId ? relationshipHoverLabel(edge.data ?? {}, edge.label) : edge.label,
  }));
  return (
    <div className="kc-semantic-canvas" data-testid="semantic-graph-canvas">
      {emptyState ? (
        <div className="kc-semantic-canvas-empty">
          <GitBranch className="kc-native-state-icon" />
          <strong>等待 MDL 图谱</strong>
          <span>{emptyState}</span>
        </div>
      ) : null}
      <ReactFlowProvider>
        <SemanticCanvasFitButton />
        <ReactFlow<SemanticGraphNodeType, SemanticGraphEdgeType>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          fitView
          fitViewOptions={{ padding: 0.18, minZoom: 0.35, maxZoom: 1.1 }}
          minZoom={0.18}
          maxZoom={1.8}
          panOnScroll
          onNodeClick={(_, node) => onSelect({ type: "node", id: node.id, data: node.data })}
          onEdgeClick={(_, edge) => onSelect({ type: "edge", id: edge.id, data: edge.data ?? {} })}
          onEdgeMouseEnter={(_, edge) => setHoveredEdgeId(edge.id)}
          onEdgeMouseLeave={() => setHoveredEdgeId("")}
        >
          <Background gap={24} size={1} color="hsl(var(--border))" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="kc-semantic-minimap" />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}

function SemanticCanvasFitButton() {
  const { fitView } = useReactFlow();
  return (
    <button className="kc-canvas-fit" type="button" onClick={() => fitView({ padding: 0.18 })}>
      <Maximize2 className="kc-native-icon" />
      Fit
    </button>
  );
}

function SemanticGraphNode({ data }: NodeProps<Node<SemanticNodeData>>) {
  const highlightedFields = new Set((data.highlightedFieldNames ?? []).map(normalizeFieldName));
  return (
    <article className={`kc-semantic-node is-${data.kind}${data.edgeHoverRole ? ` is-edge-${data.edgeHoverRole}` : ""}`}>
      <Handle type="target" position={Position.Left} />
      <header>
        {data.kind === "model" ? <Database className="kc-native-icon" /> : <Table2 className="kc-native-icon" />}
        <strong>{data.label}</strong>
      </header>
      <p>{data.description || data.table || "Semantic model entity"}</p>
      <div className="kc-semantic-node__section">
        {data.fields.slice(0, 5).map((field) => {
          const fieldName = labelFrom(field);
          const highlighted = highlightedFields.has(normalizeFieldName(fieldName));
          return (
            <span key={fieldName} className={highlighted ? "is-join-field" : ""}>
              {field.primary_key ? <CircleDot className="kc-native-icon" /> : null}
              {fieldName} <em>{String(field.type ?? field.data_type ?? "")}</em>
            </span>
          );
        })}
      </div>
      {data.metrics.length ? (
        <div className="kc-semantic-node__facts">
          <strong>Metrics</strong>
          {data.metrics.slice(0, 3).map((metric) => (
            <span key={labelFrom(metric)} className="kc-node-metric-chip">{labelFrom(metric)}</span>
          ))}
        </div>
      ) : null}
      {data.dimensions.length ? (
        <div className="kc-semantic-node__facts">
          <strong>Dimensions</strong>
          {data.dimensions.slice(0, 3).map((dimension) => (
            <span key={labelFrom(dimension)}>{labelFrom(dimension)}</span>
          ))}
        </div>
      ) : null}
      <footer>
        <small>{data.metrics.length} metrics</small>
        <small>{data.dimensions.length} dimensions</small>
      </footer>
      <Handle type="source" position={Position.Right} />
    </article>
  );
}

function SemanticModelTree({
  mode,
  onModeChange,
  query,
  onQueryChange,
  sources,
  snapshots,
  assets,
  selectedAssetId,
  onSelectAsset,
  onSelectGraphNode,
  onSelectField,
  onSelectMetric,
  onSelectRelationship,
  modelingView,
}: {
  mode: "source" | "snapshot" | "semantic";
  onModeChange: (mode: "source" | "snapshot" | "semantic") => void;
  query: string;
  onQueryChange: (value: string) => void;
  sources: KnowledgeAssetSource[];
  snapshots: KnowledgeAssetSnapshot[];
  assets: KnowledgeAssetMetadata[];
  selectedAssetId: string;
  onSelectAsset: (id: string) => void;
  onSelectGraphNode: (id: string) => void;
  onSelectField: (model: WrenModelingModel, field: WrenModelingField) => void;
  onSelectMetric: (metric: WrenModelingMetric) => void;
  onSelectRelationship: (relationship: WrenModelingRelationship) => void;
  modelingView: WrenModelingViewModel;
}) {
  type TreeRow = {
    id: string;
    label: string;
    detail: string;
    kind: "source" | "snapshot" | "asset" | "model" | "view" | "field" | "relationship" | "metric";
    parentId?: string;
    model?: WrenModelingModel;
    field?: WrenModelingField;
    relationship?: WrenModelingRelationship;
    metric?: WrenModelingMetric;
  };
  const filtered = (items: TreeRow[]) =>
    items.filter((item) => `${item.label} ${item.detail}`.toLowerCase().includes(query.toLowerCase()));
  const modelRows = wrenModelRows(modelingView.models, "model");
  const viewRows = wrenModelRows(modelingView.views, "view");
  const relationshipRows = modelingView.relationships.map((relationship) => ({
    id: relationship.id,
    label: relationship.displayName,
    detail: `${relationship.fromModelId}.${relationship.fromField || "*"} -> ${relationship.toModelId}.${relationship.toField || "*"}`,
    kind: "relationship" as const,
    relationship,
  }));
  const metricRows = modelingView.metrics.map((metric) => ({
    id: metric.id,
    label: metric.displayName,
    detail: metric.modelId || "metric",
    kind: "metric" as const,
    metric,
  }));
  const rows =
    mode === "source"
      ? filtered(sources.map((source) => ({ id: source.id, label: source.name, detail: source.source_type, kind: "source" as const })))
      : mode === "snapshot"
        ? filtered(snapshots.map((snapshot) => ({ id: snapshot.id, label: snapshot.metadata?.name || snapshot.id, detail: snapshot.kind || "snapshot", kind: "snapshot" as const })))
        : filtered([
            ...assets.map((asset) => ({ id: asset.asset_id, label: asset.name, detail: `${asset.publish_state} · ${asset.version || "v1"}`, kind: "asset" as const })),
            ...modelRows,
            ...viewRows,
            ...relationshipRows,
            ...metricRows,
          ]);
  return (
    <aside className="kc-semantic-tree">
      <div className="kc-segmented" role="tablist" aria-label="模型树视图">
        {(["source", "snapshot", "semantic"] as const).map((item) => (
          <button
            key={item}
            type="button"
            className={mode === item ? "is-active" : ""}
            onClick={() => onModeChange(item)}
          >
            {item === "source" ? "Source" : item === "snapshot" ? "Snapshot" : "Semantic Model"}
          </button>
        ))}
      </div>
      <label className="kc-tree-search">
        <Search className="kc-native-icon" />
        <input value={query} placeholder="搜索模型、表、字段" onChange={(event) => onQueryChange(event.target.value)} />
      </label>
      <div className="kc-tree-list">
        {mode === "semantic" ? (
          <>
            <WrenTreeGroup title="Models" count={modelRows.filter((row) => !row.parentId).length} rows={filtered(modelRows)} selectedAssetId={selectedAssetId} assets={assets} onSelectAsset={onSelectAsset} onSelectGraphNode={onSelectGraphNode} onSelectField={onSelectField} onSelectMetric={onSelectMetric} onSelectRelationship={onSelectRelationship} />
            <WrenTreeGroup title="Views" count={viewRows.filter((row) => !row.parentId).length} rows={filtered(viewRows)} selectedAssetId={selectedAssetId} assets={assets} onSelectAsset={onSelectAsset} onSelectGraphNode={onSelectGraphNode} onSelectField={onSelectField} onSelectMetric={onSelectMetric} onSelectRelationship={onSelectRelationship} />
            <WrenTreeGroup title="Relationships" count={relationshipRows.length} rows={filtered(relationshipRows)} selectedAssetId={selectedAssetId} assets={assets} onSelectAsset={onSelectAsset} onSelectGraphNode={onSelectGraphNode} onSelectField={onSelectField} onSelectMetric={onSelectMetric} onSelectRelationship={onSelectRelationship} />
            <WrenTreeGroup title="Metrics" count={metricRows.length} rows={filtered(metricRows)} selectedAssetId={selectedAssetId} assets={assets} onSelectAsset={onSelectAsset} onSelectGraphNode={onSelectGraphNode} onSelectField={onSelectField} onSelectMetric={onSelectMetric} onSelectRelationship={onSelectRelationship} />
          </>
        ) : (
          <>
            <div className="kc-tree-group-title">
              {mode === "source" ? "Sources" : "Snapshots"}
              <span>{rows.length}</span>
            </div>
            {rows.map((row) => (
              <WrenTreeRow
                key={row.id}
                row={row}
                selectedAssetId={selectedAssetId}
                assets={assets}
                onSelectAsset={onSelectAsset}
                onSelectGraphNode={onSelectGraphNode}
                onSelectField={onSelectField}
                onSelectMetric={onSelectMetric}
                onSelectRelationship={onSelectRelationship}
              />
            ))}
          </>
        )}
      </div>
    </aside>
  );
}

function wrenModelRows(models: WrenModelingModel[], kind: "model" | "view"): Array<{
  id: string;
  label: string;
  detail: string;
  kind: "model" | "view" | "field" | "metric";
  parentId?: string;
  model?: WrenModelingModel;
  field?: WrenModelingField;
  metric?: WrenModelingMetric;
}> {
  return models.flatMap((model) => [
    {
      id: model.id,
      label: model.displayName,
      detail: `${model.table} · ${model.fields.length} columns`,
      kind,
      model,
    },
    ...model.fields.slice(0, 8).map((field) => ({
      id: `${model.id}:${field.id}`,
      label: field.name,
      detail: field.type,
      kind: "field" as const,
      parentId: model.id,
      model,
      field,
    })),
    ...model.calculatedFields.slice(0, 4).map((field) => ({
      id: `${model.id}:calc:${field.id}`,
      label: field.name,
      detail: "calculated field",
      kind: "field" as const,
      parentId: model.id,
      model,
      field,
    })),
    ...model.relationFields.slice(0, 4).map((field) => ({
      id: `${model.id}:rel:${field.id}`,
      label: field.name,
      detail: field.type,
      kind: "field" as const,
      parentId: model.id,
      model,
      field,
    })),
  ]);
}

function WrenTreeGroup({
  title,
  count,
  rows,
  ...handlers
}: {
  title: string;
  count: number;
  rows: Parameters<typeof WrenTreeRow>[0]["row"][];
  selectedAssetId: string;
  assets: KnowledgeAssetMetadata[];
  onSelectAsset: (id: string) => void;
  onSelectGraphNode: (id: string) => void;
  onSelectField: (model: WrenModelingModel, field: WrenModelingField) => void;
  onSelectMetric: (metric: WrenModelingMetric) => void;
  onSelectRelationship: (relationship: WrenModelingRelationship) => void;
}) {
  return (
    <section className="kc-wren-tree-group">
      <div className="kc-tree-group-title">
        {title}
        <span>({count})</span>
      </div>
      {rows.length ? rows.map((row) => <WrenTreeRow key={row.id} row={row} {...handlers} />) : <p className="kc-muted-line">Empty</p>}
    </section>
  );
}

function WrenTreeRow({
  row,
  selectedAssetId,
  assets,
  onSelectAsset,
  onSelectGraphNode,
  onSelectField,
  onSelectMetric,
  onSelectRelationship,
}: {
  row: {
    id: string;
    label: string;
    detail: string;
    kind: "source" | "snapshot" | "asset" | "model" | "view" | "field" | "relationship" | "metric";
    parentId?: string;
    model?: WrenModelingModel;
    field?: WrenModelingField;
    relationship?: WrenModelingRelationship;
    metric?: WrenModelingMetric;
  };
  selectedAssetId: string;
  assets: KnowledgeAssetMetadata[];
  onSelectAsset: (id: string) => void;
  onSelectGraphNode: (id: string) => void;
  onSelectField: (model: WrenModelingModel, field: WrenModelingField) => void;
  onSelectMetric: (metric: WrenModelingMetric) => void;
  onSelectRelationship: (relationship: WrenModelingRelationship) => void;
}) {
  return (
    <button
      type="button"
      className={`${row.id === selectedAssetId ? "is-active" : ""}${row.parentId ? " is-child" : ""}`}
      onClick={() => {
        if (assets.some((asset) => asset.asset_id === row.id)) onSelectAsset(row.id);
        if ((row.kind === "model" || row.kind === "view") && row.model) onSelectGraphNode(row.model.id);
        if (row.kind === "field" && row.model && row.field) onSelectField(row.model, row.field);
        if (row.kind === "metric" && row.metric) onSelectMetric(row.metric);
        if (row.kind === "relationship" && row.relationship) onSelectRelationship(row.relationship);
      }}
    >
      {row.kind === "model" || row.kind === "view" || row.kind === "source" ? (
        <Table2 className="kc-native-icon" />
      ) : row.kind === "field" ? (
        <CircleDot className="kc-native-icon" />
      ) : (
        <GitBranch className="kc-native-icon" />
      )}
      <span>
        <strong>{row.label}</strong>
        <small>{row.detail}</small>
      </span>
    </button>
  );
}

function SemanticMetadataDrawer({
  selectedItem,
  asset,
  mdl,
  modelingView,
  inspector,
  onInspectorChange,
  intent,
  targetDomain,
  publish,
  onIntentChange,
  onTargetDomainChange,
  onPublishChange,
}: {
  selectedItem: SelectedGraphItem | null;
  asset: KnowledgeAssetMetadata | null;
  mdl: Record<string, unknown>;
  modelingView: WrenModelingViewModel;
  inspector: "metadata" | "mdl" | "evals";
  onInspectorChange: (value: "metadata" | "mdl" | "evals") => void;
  intent: string;
  targetDomain: string;
  publish: boolean;
  onIntentChange: (value: string) => void;
  onTargetDomainChange: (value: string) => void;
  onPublishChange: (value: boolean) => void;
}) {
  const metrics = arrayValue(mdl.metrics);
  const dimensions = arrayValue(mdl.dimensions);
  const relationships = arrayValue(mdl.relationships);
  const evidence = arrayValue(mdl.evidence);
  const selectedTitle =
    selectedItem?.type === "node"
      ? selectedItem.data.label
      : selectedItem?.type === "field"
        ? `${selectedItem.model.displayName}.${selectedItem.data.name}`
        : selectedItem?.type === "metric"
          ? selectedItem.data.displayName
          : selectedItem?.type === "relationship"
            ? selectedItem.data.displayName
            : selectedItem?.id || asset?.name || "未选择";
  const selectedRaw =
    selectedItem?.type === "node"
      ? selectedItem.data.source
      : selectedItem?.type === "edge"
        ? selectedItem.data
        : selectedItem?.type === "field"
          ? selectedItem.data.raw
          : selectedItem?.type === "metric"
            ? selectedItem.data.raw
            : selectedItem?.type === "relationship"
              ? selectedItem.data.raw
              : {};
  const selectedConfidence =
    selectedItem?.type === "edge"
      ? selectedItem.data.confidence
      : selectedItem?.type === "node"
        ? selectedItem.data.source?.confidence
        : undefined;
  return (
    <aside className="kc-semantic-drawer" data-testid="semantic-metadata-drawer">
      <div className="kc-segmented" role="tablist" aria-label="语义详情">
        {(["metadata", "mdl", "evals"] as const).map((item) => (
          <button key={item} type="button" className={inspector === item ? "is-active" : ""} onClick={() => onInspectorChange(item)}>
            {item === "metadata" ? "Metadata" : item === "mdl" ? "MDL" : "Evals"}
          </button>
        ))}
      </div>
      {inspector === "metadata" ? (
        <div className="kc-inspector-stack">
          <section>
            <h3>{selectedItem?.type === "edge" || selectedItem?.type === "relationship" ? "关系边" : selectedItem?.type === "field" ? "字段元数据" : selectedItem?.type === "metric" ? "指标元数据" : "节点元数据"}</h3>
            <dl>
              <div><dt>名称</dt><dd>{selectedTitle}</dd></div>
              <div><dt>版本</dt><dd>{asset?.version || "v1"}</dd></div>
              <div><dt>来源</dt><dd>{String(asset?.provenance?.runner_backend || "unknown")}</dd></div>
              <div><dt>置信度</dt><dd>{String(selectedConfidence || asset?.gate?.score || "n/a")}</dd></div>
            </dl>
          </section>
          <section>
            <h3>当前选择</h3>
            <InspectorList items={[selectedRaw].filter((item) => Object.keys(objectValue(item)).length)} />
          </section>
          <section>
            <h3>字段</h3>
            <InspectorList items={selectedItem?.type === "node" ? selectedItem.data.fields : modelingView.models.flatMap((model) => model.fields).slice(0, 6).map((field) => field.raw)} />
          </section>
          <section>
            <h3>指标与维度</h3>
            <InspectorList items={[...metrics.slice(0, 5), ...dimensions.slice(0, 5)]} />
          </section>
          <section>
            <h3>关系</h3>
            <InspectorList items={relationships.slice(0, 6)} />
          </section>
          <section>
            <h3>策略与证据</h3>
            <InspectorList items={[objectValue(mdl.permissions), ...evidence.slice(0, 5)]} />
          </section>
          <section className="kc-agent-form-mini">
            <label>
              <span>目标领域</span>
              <input value={targetDomain} onChange={(event) => onTargetDomainChange(event.target.value)} />
            </label>
            <label>
              <span>用户 intent</span>
              <textarea value={intent} onChange={(event) => onIntentChange(event.target.value)} />
            </label>
            <label className="kc-native-checkbox">
              <input type="checkbox" checked={publish} onChange={(event) => onPublishChange(event.target.checked)} />
              <span>生成后发布</span>
            </label>
          </section>
        </div>
      ) : inspector === "mdl" ? (
        <pre className="kc-json-view"><code>{formatJson(mdl)}</code></pre>
      ) : (
        <pre className="kc-json-view"><code>{formatJson(asset?.capabilities?.eval_cases ?? asset?.provenance?.validation_result ?? [])}</code></pre>
      )}
    </aside>
  );
}

function InspectorList({ items }: { items: unknown[] }) {
  if (!items.length) return <p className="kc-muted-line">暂无选择项。</p>;
  return (
    <ul className="kc-inspector-list">
      {items.map((item, index) => (
        <li key={`${labelFrom(item)}-${index}`}>
          <Braces className="kc-native-icon" />
          <span>
            <strong>{labelFrom(item)}</strong>
            <small>{typeof item === "object" ? formatJson(item).slice(0, 180) : String(item)}</small>
          </span>
        </li>
      ))}
    </ul>
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

function SemanticWorkbenchState({ title, text }: { title: string; text: string }) {
  return (
    <section className="kc-workbench-state">
      <Database className="kc-native-icon" />
      <strong>{title}</strong>
      <span>{text}</span>
    </section>
  );
}

function blockedReason(
  latestJob: KnowledgeAssetBuildJob | null,
  selectedAsset: KnowledgeAssetMetadata | null,
): string {
  const errorMessage = latestJob?.error?.message;
  if (typeof errorMessage === "string" && errorMessage.trim()) return errorMessage;
  const jobBlockers = latestJob?.output?.blocked_reasons;
  if (Array.isArray(jobBlockers) && jobBlockers.length) return jobBlockers.map(String).join(", ");
  const blockers = selectedAsset?.gate?.blockers;
  if (Array.isArray(blockers) && blockers.length) return blockers.join(", ");
  return "none";
}

export function buildSemanticGraph(mdl: Record<string, unknown>): {
  nodes: SemanticGraphNodeType[];
  edges: SemanticGraphEdgeType[];
} {
  const entities = arrayValue(mdl.entities).filter((item) => typeof item === "object") as Array<Record<string, unknown>>;
  const metrics = arrayValue(mdl.metrics).filter((item) => typeof item === "object") as Array<Record<string, unknown>>;
  const dimensions = arrayValue(mdl.dimensions).filter((item) => typeof item === "object") as Array<Record<string, unknown>>;
  const relationships = arrayValue(mdl.relationships).filter((item) => typeof item === "object") as Array<Record<string, unknown>>;
  const rawNodes: SemanticGraphNodeType[] = entities.length
    ? entities.map((entity) => {
        const id = String(entity.id || entity.table || labelFrom(entity));
        return {
          id,
          type: "semanticNode",
          position: { x: 0, y: 0 },
          data: {
            label: labelFrom(entity),
            kind: String(entity.kind || entity.type || "").toLowerCase().includes("view") ? "view" : "table",
            table: String(entity.table || ""),
            description: String(entity.description || ""),
            fields: arrayValue(entity.fields).filter((item) => typeof item === "object") as Array<Record<string, unknown>>,
            metrics: metrics.filter((metric) => String(metric.entity || metric.entityId || "") === id),
            dimensions: dimensions.filter((dimension) => String(dimension.entity || dimension.entityId || "") === id),
            source: entity,
          },
        };
      })
    : [
        {
          id: "semantic-model",
          type: "semanticNode",
          position: { x: 0, y: 0 },
          data: {
            label: labelFrom(objectValue(mdl.model), "Semantic Model"),
            kind: "model",
            fields: [],
            metrics,
            dimensions,
            description: "Packaged MDL model",
          },
        },
      ];
  const rawEdges: SemanticGraphEdgeType[] = relationships.map((relationship, index) => {
    const source = String(relationship.from_entity || relationship.from || relationship.from_table || relationship.source || rawNodes[0]?.id);
    const target = String(relationship.to_entity || relationship.to || relationship.to_table || relationship.target || rawNodes[1]?.id || rawNodes[0]?.id);
    return {
      id: String(relationship.id || `rel-${index}`),
      source,
      target,
      label: String(relationship.label || relationship.kind || "relationship"),
      data: relationship,
      className: "kc-semantic-edge",
    };
  }).filter((edge) => edge.source && edge.target && edge.source !== edge.target);
  return layoutGraph(rawNodes, rawEdges);
}

export function relationshipFieldHighlights(relationship: Record<string, unknown>): {
  source: string[];
  target: string[];
} {
  const joinFields = arrayValue(relationship.join_fields ?? relationship.joinFields);
  const source = new Set<string>();
  const target = new Set<string>();
  joinFields.forEach((item) => {
    const record = objectValue(item);
    const from = String(record.from ?? record.from_column ?? record.source_field ?? record.source ?? "");
    const to = String(record.to ?? record.to_column ?? record.target_field ?? record.target ?? "");
    if (from) source.add(from);
    if (to) target.add(to);
  });
  for (const key of ["from_column", "fromField", "source_column", "source_field"]) {
    const value = relationship[key];
    if (value) source.add(String(value));
  }
  for (const key of ["to_column", "toField", "target_column", "target_field"]) {
    const value = relationship[key];
    if (value) target.add(String(value));
  }
  return {
    source: [...source],
    target: [...target],
  };
}

function relationshipHoverLabel(
  relationship: Record<string, unknown>,
  fallback: unknown,
): string {
  const highlights = relationshipFieldHighlights(relationship);
  const joins = highlights.source.map((source, index) => {
    const target = highlights.target[index] ?? highlights.target[0] ?? "?";
    return `${source} = ${target}`;
  });
  return joins.length ? joins.join(", ") : String(fallback || relationship.label || relationship.kind || "relationship");
}

function normalizeFieldName(value: string): string {
  return value.trim().replace(/^.*\./, "").toLowerCase();
}

function layoutGraph(
  nodes: SemanticGraphNodeType[],
  edges: SemanticGraphEdgeType[],
): { nodes: SemanticGraphNodeType[]; edges: SemanticGraphEdgeType[] } {
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "LR", nodesep: 70, ranksep: 110, marginx: 30, marginy: 30 });
  nodes.forEach((node) => graph.setNode(node.id, { width: 260, height: 210 }));
  edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
  dagre.layout(graph);
  return {
    nodes: nodes.map((node) => {
      const next = graph.node(node.id);
      return {
        ...node,
        position: { x: (next?.x ?? 0) - 130, y: (next?.y ?? 0) - 105 },
      };
    }),
    edges,
  };
}
