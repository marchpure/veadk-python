import "@xyflow/react/dist/style.css";
import { AlertCircle, Database, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  getKnowledgeAssetBuildJob,
  listKnowledgeAssetSnapshots,
  streamSemanticBuild,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSnapshot,
  type KnowledgeAssetSource,
} from "../adk/knowledgeAssets";
import {
  createWrenSemanticSourcePortViewModel,
  relationshipJoinFields,
} from "../features/knowledge-assets/adapters/wrenSemanticAdapter";
import {
  WrenModelingSourcePort,
  type WrenSourcePortSelection,
} from "../features/knowledge-assets/source-ports/wren/WrenModelingSourcePort";
import {
  arrayValue,
  labelFrom,
} from "./knowledgeWorkbenchUtils";

export function SemanticModelingWorkbench({
  spaceId,
  sources,
  assets,
  buildJobs,
  onRefresh,
  showBuildForm = true,
}: {
  spaceId: string;
  sources: KnowledgeAssetSource[];
  assets: KnowledgeAssetMetadata[];
  buildJobs: KnowledgeAssetBuildJob[];
  onRefresh: () => void | Promise<void>;
  showBuildForm?: boolean;
}) {
  const semanticAssets = assets.filter(
    (asset) => asset.asset_type === "semantic_model" && asset.capability_kind === "semantic_skill",
  );
  const databaseSources = useMemo(
    () =>
      sources.filter((source) =>
        ["database", "schema_snapshot"].includes(String(source.source_type).toLowerCase()),
      ),
    [sources],
  );
  const [assetId, setAssetId] = useState(semanticAssets[0]?.asset_id || "");
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [snapshots, setSnapshots] = useState<KnowledgeAssetSnapshot[]>([]);
  const [snapshotState, setSnapshotState] = useState<"idle" | "loading" | "error">("idle");
  const [treeMode, setTreeMode] = useState<"source" | "snapshot" | "semantic">("semantic");
  const [treeQuery, setTreeQuery] = useState("");
  const [selectedItem, setSelectedItem] = useState<WrenSourcePortSelection>(null);
  const [name, setName] = useState("销售语义问数 Skill");
  const [intent, setIntent] = useState("围绕销售票数、销售额、门店、时间趋势生成聚合问数能力");
  const [targetDomain, setTargetDomain] = useState("sales");
  const [publish, setPublish] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastJob, setLastJob] = useState<KnowledgeAssetBuildJob | null>(null);
  const [inspector, setInspector] = useState<"metadata" | "mdl" | "evals">("metadata");

  const viewModel = useMemo(
    () =>
      createWrenSemanticSourcePortViewModel({
        sources,
        snapshots,
        assets,
        buildJobs,
        selectedAssetId: assetId,
        lastJob,
      }),
    [assetId, assets, buildJobs, lastJob, snapshots, sources],
  );

  useEffect(() => {
    setSelectedSourceId((current) => {
      if (current && databaseSources.some((source) => source.id === current)) return current;
      return databaseSources[0]?.id || "";
    });
  }, [databaseSources]);

  useEffect(() => {
    setAssetId((current) => current || semanticAssets[0]?.asset_id || "");
  }, [semanticAssets]);

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

  async function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!spaceId || !selectedSourceId) {
      setError("请选择资产空间和数据库 source。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const events = await streamSemanticBuild({
        space_id: spaceId,
        source_ids: [selectedSourceId],
        snapshot_ids: selectedSnapshotId ? [selectedSnapshotId] : [],
        name,
        intent,
        target_domain: targetDomain,
        publish,
      }, () => undefined);
      const terminal = [...events].reverse().find((item) => item.event_type === "job_status");
      const jobId = String(terminal?.payload?.job_id || "");
      const finalJob = jobId ? await pollBuildJob(jobId) : null;
      if (finalJob) setLastJob(finalJob);
      await onRefresh();
      const resultSkillId = finalJob?.result_skill_id || String(terminal?.payload?.semantic_pack_id || "");
      if (resultSkillId) setAssetId(resultSkillId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成语义 Skill 失败。");
    } finally {
      setBusy(false);
    }
  }

  async function pollBuildJob(jobId: string): Promise<KnowledgeAssetBuildJob> {
    let latest = await getKnowledgeAssetBuildJob(jobId);
    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (!["queued", "running", "pending", "building"].includes(latest.status)) return latest;
      await new Promise((resolve) => window.setTimeout(resolve, attempt === 0 ? 250 : 900));
      latest = await getKnowledgeAssetBuildJob(jobId);
    }
    return latest;
  }

  if (!databaseSources.length) {
    return (
      <section className="kc-wren-source-port" data-testid="semantic-modeling-workbench">
        <SemanticWorkbenchState
          title="需要数据库或 Schema Snapshot"
          text="先在数据源页登记数据库 source 或导入 schema snapshot，之后可在这里生成 Semantic Skill。"
        />
      </section>
    );
  }

  return (
    <section data-testid="semantic-modeling-workbench">
      {showBuildForm ? (
        <form className="kc-wren-build-form" onSubmit={submit}>
        <select aria-label="Semantic Skill" value={viewModel.selectedAsset?.asset_id || ""} onChange={(event) => setAssetId(event.target.value)}>
          <option value="">Semantic Skill</option>
          {semanticAssets.map((asset) => <option key={asset.asset_id} value={asset.asset_id}>{asset.name} · {asset.version || "v1"}</option>)}
        </select>
        <select value={selectedSourceId} onChange={(event) => setSelectedSourceId(event.target.value)}>
          <option value="">Source</option>
          {databaseSources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
        </select>
        <select value={selectedSnapshotId} onChange={(event) => setSelectedSnapshotId(event.target.value)} disabled={!selectedSourceId || snapshotState === "loading"}>
          <option value="">{snapshotState === "loading" ? "读取 Snapshot" : "Snapshot"}</option>
          {snapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>{snapshot.metadata?.name || snapshot.id}</option>)}
        </select>
        <input value={name} onChange={(event) => setName(event.target.value)} aria-label="语义 Skill 名称" />
        <button type="submit" disabled={busy}>{busy ? <Loader2 className="kc-native-icon kc-spin" /> : null}生成语义</button>
        </form>
      ) : null}
      {error || viewModel.latestJob?.status === "blocked" ? (
        <div className="kc-workbench-alert" role="alert">
          <AlertCircle className="kc-native-icon" />
          <span>{error || String(viewModel.latestJob?.error?.message || "构建被阻塞，请查看 Agent 状态。")}</span>
        </div>
      ) : null}
      <WrenModelingSourcePort
        viewModel={viewModel}
        treeMode={treeMode}
        onTreeModeChange={setTreeMode}
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
        onBuild={() => void submit()}
        busy={busy}
        intent={intent}
        targetDomain={targetDomain}
        publish={publish}
        onIntentChange={setIntent}
        onTargetDomainChange={setTargetDomain}
        onPublishChange={setPublish}
      />
    </section>
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

export function relationshipFieldHighlights(relationship: Record<string, unknown>): {
  source: string[];
  target: string[];
} {
  return relationshipJoinFields(relationship);
}

export function buildSemanticGraph(mdl: Record<string, unknown>): {
  nodes: Array<{ id: string; type: "semanticNode"; data: Record<string, unknown> }>;
  edges: Array<{ id: string; source: string; target: string; data: Record<string, unknown> }>;
} {
  const entities = arrayValue(mdl.entities).filter((item) => typeof item === "object") as Array<Record<string, unknown>>;
  const relationships = arrayValue(mdl.relationships).filter((item) => typeof item === "object") as Array<Record<string, unknown>>;
  const nodes = entities.map((entity) => ({
    id: String(entity.id || entity.table || labelFrom(entity)),
    type: "semanticNode" as const,
    data: entity,
  }));
  const edges = relationships.map((relationship, index) => ({
    id: String(relationship.id || `rel-${index}`),
    source: String(relationship.from_entity || relationship.from || relationship.from_table || relationship.source || nodes[0]?.id),
    target: String(relationship.to_entity || relationship.to || relationship.to_table || relationship.target || nodes[1]?.id || nodes[0]?.id),
    data: relationship,
  }));
  return { nodes, edges };
}
