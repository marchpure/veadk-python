import {
  AlertCircle,
  CheckCircle2,
  Database,
  FileJson,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  buildSemanticSkill,
  listKnowledgeAssetSnapshots,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSnapshot,
  type KnowledgeAssetSource,
} from "../adk/knowledgeAssets";
import { CapabilityPanelSlot } from "./capabilitySlots";
import type {
  CapabilityBuildJobStatus,
  CapabilityPublishState,
} from "./capabilitySlots";

type BuildState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; snapshots: KnowledgeAssetSnapshot[] }
  | { status: "error"; message: string };

function jobOutput(job: KnowledgeAssetBuildJob | null): Record<string, unknown> {
  return job?.output && typeof job.output === "object" ? job.output : {};
}

function capabilityMdl(asset: KnowledgeAssetMetadata | null): Record<string, unknown> {
  const pkg = asset?.capability_package;
  const mdl = pkg && typeof pkg === "object" ? pkg.mdl : null;
  return mdl && typeof mdl === "object" ? (mdl as Record<string, unknown>) : {};
}

function arrayCount(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function labels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        return String(record.id ?? record.name ?? record.field ?? "").trim();
      }
      return "";
    })
    .filter(Boolean)
    .slice(0, 8);
}

function userFacingError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message && error.message !== "Failed to fetch") {
    return error.message;
  }
  return `${fallback} 请检查 Studio 后端是否可用，并刷新后重试。`;
}

function slotPublishState(value: string | undefined): CapabilityPublishState {
  if (value === "published" || value === "archived") return value;
  return "draft";
}

function slotJobStatus(value: string | undefined): CapabilityBuildJobStatus {
  if (
    value === "succeeded" ||
    value === "failed" ||
    value === "blocked" ||
    value === "cancelled" ||
    value === "running" ||
    value === "queued"
  ) {
    return value;
  }
  return value === "pending" || value === "building" ? "running" : "queued";
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
  const [state, setState] = useState<BuildState>({ status: "idle" });
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [selectedDocSourceId, setSelectedDocSourceId] = useState("");
  const [name, setName] = useState("销售语义问数 Skill");
  const [intent, setIntent] = useState("围绕销售票数、销售额、门店、时间趋势生成聚合问数能力");
  const [submitting, setSubmitting] = useState(false);
  const [lastJob, setLastJob] = useState<KnowledgeAssetBuildJob | null>(null);
  const [snapshotRetry, setSnapshotRetry] = useState(0);

  const databaseSources = useMemo(
    () =>
      sources.filter((source) =>
        ["database", "schema_snapshot"].includes(String(source.source_type).toLowerCase()),
      ),
    [sources],
  );
  const documentSources = useMemo(
    () =>
      sources.filter((source) =>
        ["document", "web", "feishu", "file", "knowledge_resource"].includes(
          String(source.source_type).toLowerCase(),
        ),
      ),
    [sources],
  );
  const semanticAssets = assets.filter(
    (asset) => asset.capability_kind === "semantic_skill" || asset.asset_type === "semantic_model",
  );
  const latestSemanticJob =
    lastJob ??
    buildJobs.find((job) => job.job_type === "semantic_skill") ??
    null;
  const previewAsset =
    semanticAssets.find((asset) => asset.asset_id === latestSemanticJob?.result_skill_id) ??
    semanticAssets[0] ??
    null;
  const mdl = capabilityMdl(previewAsset);
  const metrics = labels(mdl.metrics);
  const dimensions = labels(mdl.dimensions);
  const relationships = labels(mdl.relationships);
  const output = jobOutput(latestSemanticJob);
  const blockedReasons = [
    ...((previewAsset?.gate?.blockers ?? []).map(String)),
    ...((output.gate &&
    typeof output.gate === "object" &&
    Array.isArray((output.gate as Record<string, unknown>).blockers)
      ? ((output.gate as Record<string, unknown>).blockers as unknown[])
      : []
    ).map(String)),
  ].filter(Boolean);

  useEffect(() => {
    if (!selectedSourceId) {
      setState({ status: "idle" });
      setSelectedSnapshotId("");
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    listKnowledgeAssetSnapshots({ sourceId: selectedSourceId })
      .then((snapshots) => {
        if (cancelled) return;
        setState({ status: "ready", snapshots });
        setSelectedSnapshotId(snapshots[0]?.id ?? "");
      })
      .catch((error) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: userFacingError(error, "读取 schema snapshot 失败。"),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSourceId, snapshotRetry]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceId || !selectedSourceId) return;
    setSubmitting(true);
    try {
      const job = await buildSemanticSkill({
        space_id: spaceId,
        source_ids: [selectedSourceId, selectedDocSourceId].filter(Boolean),
        snapshot_ids: selectedSnapshotId ? [selectedSnapshotId] : [],
        name,
        intent,
        target_domain: "sales",
        publish: true,
      });
      setLastJob(job);
      await onRefresh();
    } catch (error) {
      setLastJob({
        id: "semantic-build-local-error",
        job_type: "semantic_skill",
        status: "failed",
        error: {
          message: userFacingError(error, "生成 Semantic Skill 失败。"),
        },
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <CapabilityPanelSlot
      kind="semantic_skill"
      capabilities={semanticAssets.map((asset) => ({
        id: asset.asset_id,
        name: asset.name,
        kind: "semantic_skill",
        status: asset.status === "ready" ? "ready" : "draft",
        publish_state: slotPublishState(asset.publish_state),
        source_ids: [],
        description: asset.description ?? "",
      }))}
      build_jobs={buildJobs
        .filter((job) => job.job_type === "semantic_skill")
        .map((job) => ({
          id: job.id,
          status: slotJobStatus(job.status),
          job_type: job.job_type,
          source_id: job.source_id ?? undefined,
          asset_id: job.asset_id ?? undefined,
          error_message:
            typeof job.error?.message === "string" ? job.error.message : undefined,
          logs_ref: job.logs_ref ?? undefined,
          created_at: job.created_at,
          updated_at: job.updated_at,
        }))}
      render={() => (
        <section className="kc-semantic-build">
          <div className="kc-semantic-build__head">
            <div>
              <h2>Semantic Skill 生成</h2>
              <p>从数据库 schema snapshot 生成 MDL-in-Skill 能力包，供 Agent 创建页选择。</p>
            </div>
            <button type="button" onClick={() => void onRefresh()}>
              <RefreshCw className="kc-native-icon" />
              刷新
            </button>
          </div>

          <div className="kc-semantic-build__grid">
            <form className="kc-semantic-card" onSubmit={submit}>
              <header>
                <Sparkles className="kc-native-icon" />
                <strong>构建向导</strong>
              </header>
              <label>
                <span>数据库 source</span>
                <select
                  required
                  value={selectedSourceId}
                  onChange={(event) => setSelectedSourceId(event.target.value)}
                >
                  <option value="">选择带 schema 的数据库来源</option>
                  {databaseSources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>业务文档上下文（可选）</span>
                <select
                  value={selectedDocSourceId}
                  onChange={(event) => setSelectedDocSourceId(event.target.value)}
                >
                  <option value="">不附加文档 source</option>
                  {documentSources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Schema snapshot</span>
                <select
                  value={selectedSnapshotId}
                  onChange={(event) => setSelectedSnapshotId(event.target.value)}
                  disabled={state.status !== "ready" || state.snapshots.length === 0}
                >
                  <option value="">使用该 source 的最新 snapshot</option>
                  {state.status === "ready"
                    ? state.snapshots.map((snapshot) => (
                        <option key={snapshot.id} value={snapshot.id}>
                          {snapshot.metadata?.name ?? snapshot.kind ?? "Schema snapshot"}
                        </option>
                      ))
                    : null}
                </select>
              </label>
              <label>
                <span>能力名称</span>
                <input value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label>
                <span>生成意图</span>
                <textarea value={intent} onChange={(event) => setIntent(event.target.value)} />
              </label>
              <div className="kc-semantic-policy">
                <ShieldCheck className="kc-native-icon" />
                <span>默认拒绝 customer/contact/phone/address/passport/member card 字段；只生成受治理 REST 查询工具。</span>
              </div>
              <button
                className="is-primary"
                type="submit"
                disabled={!spaceId || !selectedSourceId || submitting}
              >
                {submitting ? <Loader2 className="kc-native-icon kc-spin" /> : <Sparkles className="kc-native-icon" />}
                生成 Semantic Skill
              </button>
              {databaseSources.length === 0 ? (
                <div className="kc-semantic-error" role="alert">
                  <AlertCircle className="kc-native-icon" />
                  <span>需要先登记数据库或 schema snapshot 来源。</span>
                </div>
              ) : null}
              {state.status === "error" ? (
                <div className="kc-semantic-error" role="alert">
                  <AlertCircle className="kc-native-icon" />
                  <div>
                    <strong>读取失败</strong>
                    <span>{state.message}</span>
                    <button type="button" onClick={() => setSnapshotRetry((value) => value + 1)}>
                      重试读取
                    </button>
                  </div>
                </div>
              ) : null}
            </form>

            <article className="kc-semantic-card">
              <header>
                {latestSemanticJob?.status === "succeeded" ? (
                  <CheckCircle2 className="kc-native-icon" />
                ) : latestSemanticJob?.status === "running" ? (
                  <Loader2 className="kc-native-icon kc-spin" />
                ) : (
                  <FileJson className="kc-native-icon" />
                )}
                <strong>构建状态</strong>
              </header>
              <dl className="kc-semantic-status">
                <div>
                  <dt>状态</dt>
                  <dd>{latestSemanticJob?.status ?? "尚未生成"}</dd>
                </div>
                <div>
                  <dt>生成模式</dt>
                  <dd>{String(output.generation_mode ?? "等待执行")}</dd>
                </div>
                <div>
                  <dt>模型</dt>
                  <dd>{output.model_status === "not_configured" ? "not_configured" : "configured"}</dd>
                </div>
                <div>
                  <dt>发布状态</dt>
                  <dd>{previewAsset?.publish_state ?? String(output.publish_state ?? "草案")}</dd>
                </div>
              </dl>
              <BuildSteps status={latestSemanticJob?.status} />
              <PreviewList
                title="日志摘要"
                items={[
                  selectedSourceId ? "已选择数据库 source" : "等待选择数据库 source",
                  selectedSnapshotId ? "已锁定 schema snapshot" : "将使用最新 schema snapshot",
                  String(output.model_status ?? "").includes("not_configured")
                    ? "模型未配置，发布会被 gate 阻止"
                    : "模型状态已记录",
                  previewAsset?.publish_state === "published" ? "已发布到 Agent 能力选择器" : "等待发布或处理 blocker",
                ]}
                empty="暂无日志"
              />
              {blockedReasons.length ? (
                <div className="kc-semantic-blocked" role="alert">
                  <AlertCircle className="kc-native-icon" />
                  <div>
                    <strong>需要处理后才能发布</strong>
                    {blockedReasons.slice(0, 3).map((reason) => (
                      <span key={reason}>{reason}</span>
                    ))}
                    <button type="button" onClick={() => void onRefresh()}>
                      重新检查 snapshot
                    </button>
                  </div>
                </div>
              ) : null}
              {output.model_status === "not_configured" ? (
                <div className="kc-semantic-config" role="status">
                  <Wrench className="kc-native-icon" />
                  <div>
                    <strong>模型未配置</strong>
                    <span>配置 Studio 后端模型环境变量，或仅保存 deterministic 草案等待复核。</span>
                    <button type="button" onClick={() => window.dispatchEvent(new CustomEvent("agentkit:open-settings"))}>
                      打开设置
                    </button>
                  </div>
                </div>
              ) : null}
              {latestSemanticJob?.error?.message ? (
                <div className="kc-semantic-error" role="alert">
                  <AlertCircle className="kc-native-icon" />
                  <span>{String(latestSemanticJob.error.message)}</span>
                </div>
              ) : null}
            </article>

            <article className="kc-semantic-card kc-semantic-card--preview">
              <header>
                <Database className="kc-native-icon" />
                <strong>MDL 预览</strong>
              </header>
              <div className="kc-semantic-summary">
                <span>{arrayCount(mdl.entities)} entities</span>
                <span>{arrayCount(mdl.relationships)} relationships</span>
                <span>{arrayCount(mdl.metrics)} metrics</span>
                <span>{arrayCount(mdl.dimensions)} dimensions</span>
              </div>
              <PreviewList title="指标" items={metrics} empty="暂无指标候选" />
              <PreviewList title="维度" items={dimensions} empty="暂无维度候选" />
              <PreviewList title="关系" items={relationships} empty="暂无 join path" />
              <PreviewList
                title="策略"
                items={labels((mdl.permissions as Record<string, unknown> | undefined)?.denied_fields)}
                empty="暂无策略命中"
              />
              <PreviewList
                title="Eval cases"
                items={labels(previewAsset?.capabilities?.eval_cases)}
                empty="暂无 eval case"
              />
            </article>
          </div>
        </section>
      )}
    />
  );
}

function BuildSteps({ status }: { status: string | undefined }) {
  const steps = [
    ["profile", "读取 schema/profile"],
    ["mapping", "生成 graph 与候选"],
    ["package", "写入 MDL-in-Skill"],
    ["gate", "执行发布 gate"],
  ];
  const done = status === "succeeded" ? steps.length : status === "blocked" || status === "failed" ? 3 : status === "running" ? 2 : 0;
  return (
    <ol className="kc-semantic-steps">
      {steps.map(([id, label], index) => (
        <li key={id} className={index < done ? "is-done" : ""}>
          <span>{index + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}

function PreviewList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="kc-semantic-preview-list">
      <strong>{title}</strong>
      {items.length ? (
        <div>
          {items.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : (
        <em>{empty}</em>
      )}
    </div>
  );
}
