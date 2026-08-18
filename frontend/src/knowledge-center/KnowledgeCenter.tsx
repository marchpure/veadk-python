import {
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Database,
  ExternalLink,
  FileSearch,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  XCircle,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  createKnowledgeAssetSource,
  createKnowledgeAssetSpace,
  createSemanticDashboardBuildJob,
  listKnowledgeAssetBuildJobs,
  listKnowledgeAssetSidecars,
  listKnowledgeAssetSources,
  listKnowledgeAssetSpaces,
  publishSemanticDashboardBuildJob,
  recordKnowledgeAssetSkillPackage,
  recordKnowledgeAssetBuildJob,
  runSemanticDashboardBuildJob,
  updateKnowledgeAssetBuildJob,
  updateKnowledgeAssetSourceStatus,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetSidecar,
  type KnowledgeAssetSource,
  type KnowledgeAssetSpace,
  type KnowledgeAssetType,
  type KnowledgeCapabilityKind,
  type KnowledgeAssetMetadata,
  listKnowledgeAssets,
} from "../adk/knowledgeAssets";
import {
  knowledgeCapabilityLabel,
  knowledgeSourceCoverageText,
} from "../create/skills/knowledgeAssets";
import "./KnowledgeCenter.css";

type LoadState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "unauthorized"; message: string }
  | { status: "error"; message: string };

type CreatePanel = "space" | "source" | "capability" | "semanticBuild" | null;

const SOURCE_TYPES = [
  "file",
  "pdf",
  "image",
  "web",
  "feishu_doc",
  "local_web",
  "intranet_web",
  "database",
  "schema_snapshot",
];

function statusCopy(value?: string): string {
  const status = (value || "").trim().toLowerCase();
  if (!status) return "未配置";
  if (["ready", "published", "succeeded", "connected", "available"].includes(status)) {
    return "可用";
  }
  if (["running", "pending", "validating", "building", "indexing"].includes(status)) {
    return "构建中";
  }
  if (["failed", "blocked", "error", "expired", "unauthorized"].includes(status)) {
    return status === "expired" ? "凭据过期" : status === "unauthorized" ? "未授权" : "异常";
  }
  if (status === "not_configured") return "未配置";
  return value || "未知";
}

function capabilityIcon(kind: KnowledgeCapabilityKind, type?: KnowledgeAssetType) {
  if (kind === "retrieval_binding" || type === "knowledge_resource") return FileSearch;
  if (kind === "dashboard_skill" || type === "dashboard") return BarChart3;
  return Database;
}

function normalizeAssetId(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80) || `asset-${Date.now().toString(36)}`
  );
}

function sourceTypeLabel(type: string): string {
  const map: Record<string, string> = {
    file: "文件",
    pdf: "PDF",
    image: "图片",
    web: "网页",
    feishu_doc: "飞书文档",
    local_web: "本地页面",
    intranet_web: "内网页面",
    database: "数据库连接",
    schema_snapshot: "Schema Snapshot",
  };
  return map[type] ?? type;
}

function assetTypeForCapability(kind: KnowledgeCapabilityKind): KnowledgeAssetType {
  if (kind === "retrieval_binding") return "knowledge_resource";
  if (kind === "dashboard_skill") return "dashboard";
  return "semantic_model";
}

function queryUrlForAsset(type: KnowledgeAssetType, assetId: string): string {
  if (type === "knowledge_resource") {
    return `/api/knowledge-assets/assets/knowledge_resource/${assetId}`;
  }
  return `/api/knowledge-assets/assets/${type}/${assetId}/query`;
}

function capabilityIdentifier(value: string): string {
  return (
    value
      .trim()
      .replace(/[^a-zA-Z0-9_.-]+/g, "_")
      .slice(0, 128) || "field"
  );
}

function evaluationSuite(kind: KnowledgeCapabilityKind, assetId: string) {
  return {
    suite: {
      contract_version: "evaluation.suite_version.v1",
      id: `${assetId}_evals`,
      capability_kind: kind,
      cases: [],
    },
    "README.md": "EvaluationSuite placeholder for future AgentKit evaluation runs.",
  };
}

function buildManualCapabilityPackage({
  kind,
  assetType,
  assetId,
  name,
  description,
  sourceIds,
  knowledgeBaseId,
  metrics,
  dimensions,
  timeField,
  permissionHint,
  dashboardViews,
}: {
  kind: KnowledgeCapabilityKind;
  assetType: KnowledgeAssetType;
  assetId: string;
  name: string;
  description?: string;
  sourceIds: string[];
  knowledgeBaseId?: string;
  metrics: string[];
  dimensions: string[];
  timeField?: string;
  permissionHint: string;
  dashboardViews: Array<Record<string, unknown>>;
}): Record<string, unknown> {
  const evals = evaluationSuite(kind, assetId);
  if (kind === "retrieval_binding") {
    const kbId = knowledgeBaseId || assetId;
    return {
      package_type: "retrieval_binding",
      source_ids: sourceIds,
      runtime: {
        transport: "agentkit_retrieval",
        direct_database_access: false,
        raw_sql_fallback: false,
      },
      retrieval: {
        backend: "viking",
        knowledge_base_id: kbId,
        index: kbId,
      },
      evals,
      governance: {
        raw_sql_fallback: false,
        usage_policy: { permission_hint: permissionHint },
      },
    };
  }

  const metricPayloads = metrics.map((metric) => {
    const id = capabilityIdentifier(metric);
    return {
      id,
      name: metric,
      formula: id,
      definition: `Metric ${metric}.`,
      time_field: timeField || undefined,
    };
  });
  const dimensionPayloads = dimensions.map((dimension) => {
    const id = capabilityIdentifier(dimension);
    return {
      id,
      name: dimension,
      field: id,
      kind: timeField && dimension === timeField ? "time" : "category",
    };
  });

  if (kind === "dashboard_skill") {
    const views = dashboardViews.length
      ? dashboardViews
      : [
          {
            id: "overview",
            title: name,
            kind: "metric_summary",
            metric: metricPayloads[0]?.id,
            dimensions: dimensionPayloads.map((dimension) => dimension.id),
          },
        ];
    const manifest = {
      schema: "agentkit.dashboard.manifest.v1",
      id: assetId,
      title: name,
      description: description || "",
      semantic_bindings: metricPayloads.map((metric) => ({
        metric: metric.id,
        dimensions: dimensionPayloads.map((dimension) => dimension.id),
      })),
      data_views: views,
      filters: timeField
        ? [{ id: "time_range", type: "time_range", dimension: capabilityIdentifier(timeField) }]
        : [],
      tiles: views.map((view, index) => ({
        id: `tile_${String(view.id || `view_${index + 1}`)}`,
        type: String(view.kind || "metric_summary"),
        title: String(view.title || view.id || `View ${index + 1}`),
        data_view_id: String(view.id || `view_${index + 1}`),
      })),
      layout: views.map((view, index) => ({
        tile_id: `tile_${String(view.id || `view_${index + 1}`)}`,
        x: (index % 3) * 4,
        y: Math.floor(index / 3) * 3,
        w: 4,
        h: 3,
      })),
      policies: {
        raw_sql_fallback: false,
        uses_only_defined_metrics_and_dimensions: true,
      },
    };
    return {
      package_type: "dashboard_skill",
      source_ids: sourceIds,
      runtime: {
        transport: "agentkit_governed_rest",
        query_url: queryUrlForAsset(assetType, assetId),
        direct_database_access: false,
        raw_sql_fallback: false,
      },
      dashboard: manifest,
      evals,
      governance: {
        raw_sql_fallback: false,
        usage_policy: { permission_hint: permissionHint },
      },
    };
  }

  return {
    package_type: "semantic_skill",
    source_ids: sourceIds,
    runtime: {
      transport: "agentkit_governed_rest",
      query_url: queryUrlForAsset(assetType, assetId),
      direct_database_access: false,
      raw_sql_fallback: false,
    },
    mdl: {
      schema: "agentkit.mdl.v1",
      model: {
        id: assetId,
        slug: assetId,
        name,
        version: "v1",
      },
      entities: [],
      relationships: [],
      metrics: metricPayloads,
      dimensions: dimensionPayloads,
      permissions: {
        raw_sql_fallback: false,
        permission_hint: permissionHint,
      },
      freshness: {
        status: sourceIds.length ? "source_registered" : "no_source",
      },
    },
    evals,
    governance: {
      allowed_metrics: metricPayloads.map((metric) => metric.id),
      allowed_dimensions: dimensionPayloads.map((dimension) => dimension.id),
      raw_sql_fallback: false,
      usage_policy: { permission_hint: permissionHint },
    },
  };
}

interface SpaceFormState {
  name: string;
  description: string;
  region: string;
  defaultKnowledgeBaseId: string;
}

interface SourceFormState {
  sourceType: string;
  name: string;
  uri: string;
  provider: string;
  description: string;
}

interface CapabilityFormState {
  kind: KnowledgeCapabilityKind;
  name: string;
  assetId: string;
  description: string;
  knowledgeBaseId: string;
  metrics: string;
  dimensions: string;
  timeField: string;
  exampleQuestions: string;
  dashboardViews: string;
  permissionHint: string;
  publish: boolean;
}

interface SemanticBuildFormState {
  sourceIds: string[];
  mode: "schema_only" | "sampled_rows" | "hybrid";
  targetDomain: string;
  dashboardGoal: string;
  maxRowsPerTable: number;
  publish: boolean;
}

function initialSpaceForm(): SpaceFormState {
  return { name: "", description: "", region: "cn-beijing", defaultKnowledgeBaseId: "" };
}

function initialSourceForm(): SourceFormState {
  return {
    sourceType: "web",
    name: "",
    uri: "",
    provider: "",
    description: "",
  };
}

function initialCapabilityForm(): CapabilityFormState {
  return {
    kind: "retrieval_binding",
    name: "",
    assetId: "",
    description: "",
    knowledgeBaseId: "",
    metrics: "",
    dimensions: "",
    timeField: "",
    exampleQuestions: "",
    dashboardViews: "",
    permissionHint: "",
    publish: true,
  };
}

function initialSemanticBuildForm(): SemanticBuildFormState {
  return {
    sourceIds: [],
    mode: "schema_only",
    targetDomain: "sales",
    dashboardGoal: "sales overview",
    maxRowsPerTable: 200,
    publish: true,
  };
}

function userFacingError(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : "";
  if (!message || /failed to fetch/i.test(message)) {
    return `${fallback}。请确认 Studio 后端可用后重试。`;
  }
  return message;
}

export function KnowledgeCenterView() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [spaces, setSpaces] = useState<KnowledgeAssetSpace[]>([]);
  const [sources, setSources] = useState<KnowledgeAssetSource[]>([]);
  const [assets, setAssets] = useState<KnowledgeAssetMetadata[]>([]);
  const [buildJobs, setBuildJobs] = useState<KnowledgeAssetBuildJob[]>([]);
  const [sidecars, setSidecars] = useState<KnowledgeAssetSidecar[]>([]);
  const [activeSpaceId, setActiveSpaceId] = useState("");
  const [activePanel, setActivePanel] = useState<CreatePanel>(null);
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [spaceForm, setSpaceForm] = useState<SpaceFormState>(initialSpaceForm);
  const [sourceForm, setSourceForm] = useState<SourceFormState>(initialSourceForm);
  const [capabilityForm, setCapabilityForm] = useState<CapabilityFormState>(
    initialCapabilityForm,
  );
  const [semanticBuildForm, setSemanticBuildForm] = useState<SemanticBuildFormState>(
    initialSemanticBuildForm,
  );
  const activeSpaceIdRef = useRef("");

  const setActiveSpace = useCallback((spaceId: string) => {
    activeSpaceIdRef.current = spaceId;
    setActiveSpaceId(spaceId);
  }, []);

  const refresh = useCallback(async (preferredSpaceId?: string) => {
    setState({ status: "loading" });
    try {
      const [spaceItems, assetPayload, sidecarItems] = await Promise.all([
        listKnowledgeAssetSpaces(),
        listKnowledgeAssets({ limit: 100 }),
        listKnowledgeAssetSidecars(),
      ]);
      const preferred = preferredSpaceId || activeSpaceIdRef.current;
      const nextActiveSpaceId = spaceItems.some((space) => space.id === preferred)
        ? preferred
        : spaceItems[0]?.id || "";
      const [sourceItems, jobItems] = await Promise.all([
        listKnowledgeAssetSources(nextActiveSpaceId || undefined),
        listKnowledgeAssetBuildJobs(nextActiveSpaceId || undefined),
      ]);
      setSpaces(spaceItems);
      setActiveSpace(nextActiveSpaceId);
      setSources(sourceItems);
      setAssets(assetPayload.items ?? []);
      setBuildJobs(jobItems);
      setSidecars(sidecarItems);
      setState({ status: "ready" });
    } catch (error) {
      const status = typeof (error as { status?: unknown }).status === "number"
        ? (error as { status: number }).status
        : 0;
      setState({
        status: status === 401 || status === 403 ? "unauthorized" : "error",
        message:
          userFacingError(error, "加载知识资产工作台失败"),
      });
    }
  }, [setActiveSpace]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeSpace = spaces.find((space) => space.id === activeSpaceId) ?? null;
  const filteredAssets = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return assets;
    return assets.filter((asset) => {
      const values = [
        asset.name,
        asset.description,
        asset.asset_id,
        asset.capability_kind,
        asset.asset_type,
      ];
      return values.some((value) => String(value ?? "").toLowerCase().includes(needle));
    });
  }, [assets, query]);

  const spaceSources = sources.filter(
    (source) => !activeSpaceId || source.space_id === activeSpaceId,
  );
  const latestBuildJob = useMemo(
    () =>
      [...buildJobs].sort((left, right) => {
        const leftTime = Date.parse(left.updated_at || left.created_at || "");
        const rightTime = Date.parse(right.updated_at || right.created_at || "");
        return (Number.isFinite(rightTime) ? rightTime : 0) -
          (Number.isFinite(leftTime) ? leftTime : 0);
      })[0] ?? null,
    [buildJobs],
  );
  const latestBuildStatus = String(latestBuildJob?.status || "").toLowerCase();
  const buildRunning = ["running", "pending", "building", "indexing"].includes(
    latestBuildStatus,
  );
  const buildFailed = ["failed", "blocked", "error"].includes(latestBuildStatus);
  const buildSucceeded = ["succeeded", "success", "ready"].includes(latestBuildStatus);
  const expiredCredential = spaceSources.find((source) =>
    String(source.status).toLowerCase().includes("expired"),
  );
  const unauthorizedSource = spaceSources.find((source) =>
    String(source.status).toLowerCase().includes("unauthorized"),
  );
  const sidecar = sidecars.find((item) => item.id === "governed-query-backend");
  const buildableSources = spaceSources.filter((source) =>
    ["database", "schema_snapshot"].includes(source.source_type),
  );

  const reloadSpaceScoped = useCallback(
    async (spaceId: string) => {
      const [sourceItems, jobItems] = await Promise.all([
        listKnowledgeAssetSources(spaceId || undefined),
        listKnowledgeAssetBuildJobs(spaceId || undefined),
      ]);
      setSources(sourceItems);
      setBuildJobs(jobItems);
    },
    [],
  );

  async function submitSpace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setSubmitting(true);
    try {
      const created = await createKnowledgeAssetSpace({
        name: spaceForm.name,
        description: spaceForm.description || undefined,
        region: spaceForm.region || undefined,
        default_knowledge_base_id: spaceForm.defaultKnowledgeBaseId || undefined,
      });
      setActiveSpace(created.id);
      setActivePanel(null);
      setSpaceForm(initialSpaceForm());
      await refresh(created.id);
    } catch (error) {
      setFormError(userFacingError(error, "创建资产空间失败"));
    } finally {
      setSubmitting(false);
    }
  }

  async function submitSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeSpace) {
      setFormError("请先创建资产空间。");
      return;
    }
    setFormError("");
    setSubmitting(true);
    try {
      const created = await createKnowledgeAssetSource({
        space_id: activeSpace.id,
        source_type: sourceForm.sourceType,
        provider: sourceForm.provider || undefined,
        name: sourceForm.name,
        description: sourceForm.description || undefined,
        uri: sourceForm.uri || undefined,
        status: sourceForm.sourceType === "database" ? "not_configured" : "pending",
        locator: sourceForm.uri ? { uri: sourceForm.uri } : {},
        metadata: { created_from: "agentkit_native_workbench" },
      });
      await recordKnowledgeAssetBuildJob({
        space_id: activeSpace.id,
        source_id: created.id,
        job_type: "source_registered",
        status: "succeeded",
        output: { source_type: created.source_type },
      });
      setActivePanel(null);
      setSourceForm(initialSourceForm());
      await reloadSpaceScoped(activeSpace.id);
    } catch (error) {
      setFormError(userFacingError(error, "创建数据源失败"));
    } finally {
      setSubmitting(false);
    }
  }

  async function submitCapability(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeSpace) {
      setFormError("请先创建资产空间。");
      return;
    }
    setFormError("");
    setSubmitting(true);
    const assetType = assetTypeForCapability(capabilityForm.kind);
    const assetId = normalizeAssetId(capabilityForm.assetId || capabilityForm.name);
    let buildJob: KnowledgeAssetBuildJob | null = null;
    try {
      const sourceIds = spaceSources.map((source) => source.id);
      buildJob = await recordKnowledgeAssetBuildJob({
        space_id: activeSpace.id,
        asset_type: assetType,
        asset_id: assetId,
        job_type: capabilityForm.kind,
        status: "running",
        input: {
          source_count: sourceIds.length,
          asset_type: assetType,
          capability_kind: capabilityForm.kind,
        },
      });
      const metrics = capabilityForm.metrics
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const dimensions = capabilityForm.dimensions
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const exampleQuestions = capabilityForm.exampleQuestions
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
      const dashboardViews = capabilityForm.dashboardViews
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean)
        .map((title, index) => ({
          id: `view_${index + 1}`,
          title,
          kind: "metric_summary",
        }));
      const permissionHint =
        capabilityForm.permissionHint ||
        "按资产空间授权和能力包策略执行。";
      const knowledgeBaseId =
        capabilityForm.knowledgeBaseId ||
        activeSpace.default_knowledge_base_id ||
        assetId;
      const capabilityPackage = buildManualCapabilityPackage({
        kind: capabilityForm.kind,
        assetType,
        assetId,
        name: capabilityForm.name,
        description: capabilityForm.description || undefined,
        sourceIds,
        knowledgeBaseId,
        metrics,
        dimensions,
        timeField: capabilityForm.timeField || undefined,
        permissionHint,
        dashboardViews,
      });
      const capability = await recordKnowledgeAssetSkillPackage({
        space_id: activeSpace.id,
        asset_type: assetType,
        asset_id: assetId,
        capability_kind: capabilityForm.kind,
        name: capabilityForm.name,
        description: capabilityForm.description || undefined,
        status: "ready",
        publish_state: capabilityForm.publish ? "published" : "draft",
        source_ids: sourceIds,
        type: capabilityForm.kind,
        query_url: queryUrlForAsset(assetType, assetId),
        capability_package: capabilityPackage,
        capabilities: {
          metrics,
          dimensions,
          time_field: capabilityForm.timeField || "",
          example_questions: exampleQuestions,
          source_count: sourceIds.length,
          ...(assetType === "knowledge_resource"
            ? { knowledge_base_id: knowledgeBaseId }
            : {}),
          ...(assetType === "dashboard"
            ? { data_views: dashboardViews.map((view) => String(view.id || "")) }
            : {}),
        },
        freshness: {
          status: sourceIds.length ? "source_registered" : "no_source",
        },
        provenance: {
          builder: "agentkit_native_manual_capability_recorder",
          source_ids: sourceIds,
        },
        usage_policy: {
          permission_hint: permissionHint,
          raw_sql_fallback: false,
        },
        sample_evidence: [],
        metadata: {
          query_backend: sidecar?.configured ? "advanced" : "native",
        },
      });
      await updateKnowledgeAssetBuildJob(buildJob.id, {
        status: "succeeded",
        result_skill_id: capability.asset_id,
        output: { publish_state: capability.publish_state },
      });
      setActivePanel(null);
      setCapabilityForm(initialCapabilityForm());
      await refresh();
    } catch (error) {
      const failure = {
        status: "failed",
        error: { message: error instanceof Error ? error.message : String(error) },
      };
      if (buildJob) {
        await updateKnowledgeAssetBuildJob(buildJob.id, failure).catch(() => undefined);
      } else {
        await recordKnowledgeAssetBuildJob({
          space_id: activeSpace.id,
          asset_type: assetType,
          asset_id: assetId,
          job_type: capabilityForm.kind,
          ...failure,
        }).catch(() => undefined);
      }
      setFormError(userFacingError(error, "创建知识能力失败"));
    } finally {
      setSubmitting(false);
    }
  }

  async function submitSemanticBuild(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeSpace) {
      setFormError("请先创建资产空间。");
      return;
    }
    const sourceIds =
      semanticBuildForm.sourceIds.length > 0
        ? semanticBuildForm.sourceIds
        : buildableSources.slice(0, 1).map((source) => source.id);
    if (!sourceIds.length) {
      setFormError("请先登记包含 schema snapshot 的数据库数据源。");
      return;
    }
    setFormError("");
    setSubmitting(true);
    try {
      const created = await createSemanticDashboardBuildJob({
        space_id: activeSpace.id,
        source_ids: sourceIds,
        mode: semanticBuildForm.mode,
        target_domain: semanticBuildForm.targetDomain,
        dashboard_goal: semanticBuildForm.dashboardGoal,
        sample_policy: {
          max_rows_per_table: semanticBuildForm.maxRowsPerTable,
          pii_scan: true,
          mask_customer_contact: true,
        },
        publish: false,
      });
      const ready = await runSemanticDashboardBuildJob(created.job_id, {
        publish: false,
      });
      if (ready.blocked_reasons?.length) {
        setFormError(`语义构建被拦截：${ready.blocked_reasons.join("；")}`);
        await reloadSpaceScoped(activeSpace.id);
        return;
      }
      if (semanticBuildForm.publish) {
        await publishSemanticDashboardBuildJob(created.job_id);
      }
      setActivePanel(null);
      setSemanticBuildForm(initialSemanticBuildForm());
      await refresh(activeSpace.id);
    } catch (error) {
      setFormError(userFacingError(error, "生成语义模型和 Dashboard 失败"));
    } finally {
      setSubmitting(false);
    }
  }

  async function markExpired(source: KnowledgeAssetSource) {
    await updateKnowledgeAssetSourceStatus(source.id, {
      status: "expired_credential",
      status_reason: "Credential marked expired from native workbench.",
    });
    if (activeSpace) await reloadSpaceScoped(activeSpace.id);
  }

  if (state.status === "loading") {
    return (
      <main className="kc-native-page">
        <div className="kc-native-state" role="status">
          <Loader2 className="kc-native-icon kc-spin" />
          正在加载知识资产工作台…
        </div>
      </main>
    );
  }

  if (state.status === "unauthorized") {
    return (
      <main className="kc-native-page">
        <div className="kc-native-state" role="alert">
          <ShieldAlert className="kc-native-state-icon" />
          <strong>未授权访问知识资产</strong>
          <span>{state.message}</span>
        </div>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="kc-native-page">
        <div className="kc-native-state" role="alert">
          <AlertCircle className="kc-native-state-icon" />
          <strong>知识资产工作台暂不可用</strong>
          <span>{state.message}</span>
          <button type="button" onClick={() => void refresh()}>
            <RefreshCw className="kc-native-icon" />
            重试
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="kc-native-page">
      <aside className="kc-native-sidebar">
        <div className="kc-native-sidebar-head">
          <div>
            <h2>资产空间</h2>
            <span>{spaces.length} 个空间</span>
          </div>
          <button
            type="button"
            aria-label="创建资产空间"
            title="创建资产空间"
            onClick={() => {
              setFormError("");
              setActivePanel("space");
            }}
          >
            <Plus className="kc-native-icon" />
          </button>
        </div>

        {spaces.length === 0 ? (
          <div className="kc-native-empty-card">
            <Database className="kc-native-icon" />
            <strong>还没有资产空间</strong>
            <span>先创建一个空间，再登记数据源和 Agent 可选择的能力。</span>
            <button type="button" onClick={() => setActivePanel("space")}>
              创建空间
            </button>
          </div>
        ) : (
          <div className="kc-native-space-list" aria-label="资产空间列表">
            {spaces.map((space) => (
              <button
                key={space.id}
                type="button"
                className={`kc-native-space ${space.id === activeSpaceId ? "is-active" : ""}`}
                onClick={() => {
                  setActiveSpace(space.id);
                  void reloadSpaceScoped(space.id);
                }}
              >
                <span className="kc-native-space-icon">
                  <Database className="kc-native-icon" />
                </span>
                <span>
                  <strong>{space.name}</strong>
                  <small>
                    {space.default_knowledge_base_id ? "已绑定检索索引" : "检索索引待绑定"}
                  </small>
                </span>
              </button>
            ))}
          </div>
        )}

        <div className="kc-native-sidecar">
          <div>
            <span className={`kc-native-dot is-${sidecar?.status ?? "not_configured"}`} />
            <strong>治理查询后端</strong>
          </div>
          <p>
            {sidecar?.configured
              ? "已配置高级受治理查询通道。"
              : "未配置高级通道；原生构建仍可基于 schema snapshot 工作。"}
          </p>
          {sidecar?.debug_url ? (
            <a href={sidecar.debug_url} target="_blank" rel="noreferrer">
              <ExternalLink className="kc-native-icon" />
              诊断入口
            </a>
          ) : null}
        </div>
      </aside>

      <section className="kc-native-main">
        <header className="kc-native-head">
          <div>
            <h1>{activeSpace?.name ?? "知识资产工作台"}</h1>
            <p>
              原生管理资产空间、数据源和 Agent 可运行能力。创建 Agent 时选择能力，
              不直接选择原始数据源。
            </p>
          </div>
          <div className="kc-native-actions">
            <button type="button" onClick={() => void refresh()}>
              <RefreshCw className="kc-native-icon" />
              刷新
            </button>
            <button
              type="button"
              onClick={() => {
                setFormError("");
                setActivePanel("source");
              }}
              disabled={!activeSpace}
            >
              <Plus className="kc-native-icon" />
              数据源
            </button>
            <button
              type="button"
              className="is-primary"
              onClick={() => {
                setFormError("");
                setSemanticBuildForm((prev) => ({
                  ...prev,
                  sourceIds: buildableSources.slice(0, 1).map((source) => source.id),
                }));
                setActivePanel("semanticBuild");
              }}
              disabled={!activeSpace}
            >
              <Sparkles className="kc-native-icon" />
              生成
            </button>
          </div>
        </header>

        <div className="kc-native-status-grid">
          <StatusTile
            icon={Database}
            title="资产仓库"
            status="可用"
            tone="success"
            detail={`${spaces.length} 空间 · ${assets.length} 能力`}
          />
          <StatusTile
            icon={FileSearch}
            title="资料检索"
            status={activeSpace?.default_knowledge_base_id ? "已绑定" : "未配置"}
            tone={activeSpace?.default_knowledge_base_id ? "success" : "muted"}
            detail={activeSpace?.default_knowledge_base_id ? "默认索引可用" : "创建检索绑定时可补充索引"}
          />
          <StatusTile
            icon={KeyRound}
            title="凭据状态"
            status={
              expiredCredential
                ? "凭据过期"
                : unauthorizedSource
                  ? "未授权"
                  : "未发现泄露"
            }
            tone={expiredCredential || unauthorizedSource ? "danger" : "success"}
            detail={
              expiredCredential?.name ||
              unauthorizedSource?.name ||
              "前端仅展示连接状态"
            }
          />
          <StatusTile
            icon={buildRunning ? Clock3 : buildFailed ? XCircle : CheckCircle2}
            title="构建任务"
            status={
              buildRunning
                ? "构建中"
                : buildFailed
                  ? "构建失败"
                  : buildSucceeded
                    ? "构建成功"
                    : "暂无任务"
            }
            tone={buildRunning ? "warning" : buildFailed ? "danger" : "success"}
            detail={
              latestBuildJob?.job_type ||
              "创建能力后展示状态"
            }
          />
        </div>

        <div className="kc-native-columns">
          <section className="kc-native-panel">
            <PanelHead
              title="数据源"
              count={spaceSources.length}
              actionLabel="新增"
              onAction={activeSpace ? () => setActivePanel("source") : undefined}
            />
            {spaceSources.length === 0 ? (
              <InlineEmpty
                icon={Database}
                title="暂无数据源"
                text="登记文件、网页、飞书文档、数据库连接或 schema snapshot。凭据只保存在后端。"
              />
            ) : (
              <div className="kc-native-list">
                {spaceSources.map((source) => (
                  <article key={source.id} className="kc-native-source-card">
                    <div>
                      <strong>{source.name}</strong>
                      <span>{sourceTypeLabel(source.source_type)}</span>
                    </div>
                    <p>{source.description || source.uri || "未填写描述"}</p>
                    <footer>
                      <span className={`kc-native-badge is-${source.status}`}>
                        {statusCopy(source.status)}
                      </span>
                      <button type="button" onClick={() => void markExpired(source)}>
                        标记过期
                      </button>
                    </footer>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="kc-native-panel kc-native-panel--wide">
            <div className="kc-native-panel-head">
              <div>
                <h2>能力</h2>
                <span>{filteredAssets.length} 个可选能力</span>
              </div>
              <div className="kc-native-search">
                <Search className="kc-native-icon" />
                <input
                  value={query}
                  placeholder="搜索资料检索、语义问数、看板问数"
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
            </div>
            {filteredAssets.length === 0 ? (
              <InlineEmpty
                icon={Sparkles}
                title={assets.length === 0 ? "暂无已发布能力" : "没有匹配结果"}
                text="创建 Agent 时只选择这些能力，不直接选择原始文件、网页或数据库连接。"
              />
            ) : (
              <div className="kc-native-asset-grid">
                {filteredAssets.map((asset) => (
                  <AssetCard key={`${asset.asset_type}:${asset.asset_id}`} asset={asset} />
                ))}
              </div>
            )}
          </section>
        </div>
      </section>

      {activePanel ? (
        <div className="kc-native-drawer" role="dialog" aria-modal="true">
          <div className="kc-native-drawer-panel">
            <header>
              <h2>
                {activePanel === "space"
                  ? "创建资产空间"
                  : activePanel === "source"
                    ? "登记数据源"
                    : activePanel === "semanticBuild"
                      ? "生成语义模型和 Dashboard"
                      : "创建 Agent 能力"}
              </h2>
              <button type="button" onClick={() => setActivePanel(null)}>
                关闭
              </button>
            </header>
            {formError ? <div className="kc-native-form-error">{formError}</div> : null}
            {activePanel === "space" ? (
              <form className="kc-native-form" onSubmit={submitSpace}>
                <label>
                  <span>空间名称</span>
                  <input
                    required
                    value={spaceForm.name}
                    onChange={(event) =>
                      setSpaceForm((prev) => ({ ...prev, name: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>描述</span>
                  <textarea
                    value={spaceForm.description}
                    onChange={(event) =>
                      setSpaceForm((prev) => ({
                        ...prev,
                        description: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>区域</span>
                  <input
                    value={spaceForm.region}
                    onChange={(event) =>
                      setSpaceForm((prev) => ({ ...prev, region: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>默认检索索引</span>
                  <input
                    value={spaceForm.defaultKnowledgeBaseId}
                    placeholder="可稍后在检索绑定中指定"
                    onChange={(event) =>
                      setSpaceForm((prev) => ({
                        ...prev,
                        defaultKnowledgeBaseId: event.target.value,
                      }))
                    }
                  />
                </label>
                <FormActions busy={submitting} submitLabel="创建空间" />
              </form>
            ) : activePanel === "source" ? (
              <form className="kc-native-form" onSubmit={submitSource}>
                <label>
                  <span>类型</span>
                  <select
                    value={sourceForm.sourceType}
                    onChange={(event) =>
                      setSourceForm((prev) => ({
                        ...prev,
                        sourceType: event.target.value,
                      }))
                    }
                  >
                    {SOURCE_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {sourceTypeLabel(type)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>名称</span>
                  <input
                    required
                    value={sourceForm.name}
                    onChange={(event) =>
                      setSourceForm((prev) => ({ ...prev, name: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>URI 或连接标识</span>
                  <input
                    value={sourceForm.uri}
                    placeholder="不填写凭据、cookie 或 Authorization header"
                    onChange={(event) =>
                      setSourceForm((prev) => ({ ...prev, uri: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Provider</span>
                  <input
                    value={sourceForm.provider}
                    placeholder="feishu / oracle / web / local"
                    onChange={(event) =>
                      setSourceForm((prev) => ({
                        ...prev,
                        provider: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>描述</span>
                  <textarea
                    value={sourceForm.description}
                    onChange={(event) =>
                      setSourceForm((prev) => ({
                        ...prev,
                        description: event.target.value,
                      }))
                    }
                  />
                </label>
                <FormActions busy={submitting} submitLabel="登记数据源" />
              </form>
            ) : activePanel === "semanticBuild" ? (
              <form className="kc-native-form" onSubmit={submitSemanticBuild}>
                <label>
                  <span>数据库数据源</span>
                  <select
                    multiple
                    value={semanticBuildForm.sourceIds}
                    onChange={(event) =>
                      setSemanticBuildForm((prev) => ({
                        ...prev,
                        sourceIds: Array.from(event.currentTarget.selectedOptions).map(
                          (option) => option.value,
                        ),
                      }))
                    }
                  >
                    {buildableSources.map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.name}
                      </option>
                    ))}
                  </select>
                </label>
                {buildableSources.length === 0 ? (
                  <div className="kc-native-form-hint">
                    当前空间还没有数据库或 schema snapshot 数据源。
                  </div>
                ) : null}
                <label>
                  <span>构建模式</span>
                  <select
                    value={semanticBuildForm.mode}
                    onChange={(event) =>
                      setSemanticBuildForm((prev) => ({
                        ...prev,
                        mode: event.target.value as SemanticBuildFormState["mode"],
                      }))
                    }
                  >
                    <option value="schema_only">Schema-only</option>
                    <option value="hybrid">Hybrid redacted sample</option>
                    <option value="sampled_rows">Sampled rows</option>
                  </select>
                </label>
                <label>
                  <span>业务域</span>
                  <input
                    required
                    value={semanticBuildForm.targetDomain}
                    onChange={(event) =>
                      setSemanticBuildForm((prev) => ({
                        ...prev,
                        targetDomain: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>Dashboard 目标</span>
                  <input
                    required
                    value={semanticBuildForm.dashboardGoal}
                    onChange={(event) =>
                      setSemanticBuildForm((prev) => ({
                        ...prev,
                        dashboardGoal: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>采样上限</span>
                  <input
                    type="number"
                    min={0}
                    max={1000}
                    value={semanticBuildForm.maxRowsPerTable}
                    onChange={(event) =>
                      setSemanticBuildForm((prev) => ({
                        ...prev,
                        maxRowsPerTable: Number(event.target.value) || 0,
                      }))
                    }
                  />
                </label>
                <label className="kc-native-checkbox">
                  <input
                    type="checkbox"
                    checked={semanticBuildForm.publish}
                    onChange={(event) =>
                      setSemanticBuildForm((prev) => ({
                        ...prev,
                        publish: event.target.checked,
                      }))
                    }
                  />
                  <span>验证通过后发布到 Agent 能力选择器</span>
                </label>
                <FormActions busy={submitting} submitLabel="生成语义和 Dashboard" />
              </form>
            ) : (
              <form className="kc-native-form" onSubmit={submitCapability}>
                <label>
                  <span>能力类型</span>
                  <select
                    value={capabilityForm.kind}
                    onChange={(event) =>
                      setCapabilityForm((prev) => ({
                        ...prev,
                        kind: event.target.value as KnowledgeCapabilityKind,
                      }))
                    }
                  >
                    <option value="retrieval_binding">资料检索</option>
                    <option value="semantic_skill">语义问数</option>
                    <option value="dashboard_skill">看板问数</option>
                  </select>
                </label>
                <label>
                  <span>名称</span>
                  <input
                    required
                    value={capabilityForm.name}
                    onChange={(event) =>
                      setCapabilityForm((prev) => ({
                        ...prev,
                        name: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>能力标识</span>
                  <input
                    value={capabilityForm.assetId}
                    placeholder="默认由名称生成"
                    onChange={(event) =>
                      setCapabilityForm((prev) => ({
                        ...prev,
                        assetId: event.target.value,
                      }))
                    }
                  />
                </label>
                {capabilityForm.kind === "retrieval_binding" ? (
                  <label>
                    <span>检索索引</span>
                    <input
                      value={capabilityForm.knowledgeBaseId}
                      placeholder={activeSpace?.default_knowledge_base_id || "例如 policy-docs"}
                      onChange={(event) =>
                        setCapabilityForm((prev) => ({
                          ...prev,
                          knowledgeBaseId: event.target.value,
                        }))
                      }
                    />
                  </label>
                ) : (
                  <>
                    <label>
                      <span>指标</span>
                      <input
                        value={capabilityForm.metrics}
                        placeholder="逗号分隔"
                        onChange={(event) =>
                          setCapabilityForm((prev) => ({
                            ...prev,
                            metrics: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>维度</span>
                      <input
                        value={capabilityForm.dimensions}
                        placeholder="逗号分隔"
                        onChange={(event) =>
                          setCapabilityForm((prev) => ({
                            ...prev,
                            dimensions: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>时间字段</span>
                      <input
                        value={capabilityForm.timeField}
                        placeholder="例如 paid_at / sell_date"
                        onChange={(event) =>
                          setCapabilityForm((prev) => ({
                            ...prev,
                            timeField: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <label>
                      <span>示例问题</span>
                      <textarea
                        value={capabilityForm.exampleQuestions}
                        placeholder="每行一个问题"
                        onChange={(event) =>
                          setCapabilityForm((prev) => ({
                            ...prev,
                            exampleQuestions: event.target.value,
                          }))
                        }
                      />
                    </label>
                    {capabilityForm.kind === "dashboard_skill" ? (
                      <label>
                        <span>看板视图</span>
                        <textarea
                          value={capabilityForm.dashboardViews}
                          placeholder="每行一个视图标题"
                          onChange={(event) =>
                            setCapabilityForm((prev) => ({
                              ...prev,
                              dashboardViews: event.target.value,
                            }))
                          }
                        />
                      </label>
                    ) : null}
                  </>
                )}
                <label>
                  <span>权限提示</span>
                  <input
                    value={capabilityForm.permissionHint}
                    onChange={(event) =>
                      setCapabilityForm((prev) => ({
                        ...prev,
                        permissionHint: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>描述</span>
                  <textarea
                    value={capabilityForm.description}
                    onChange={(event) =>
                      setCapabilityForm((prev) => ({
                        ...prev,
                        description: event.target.value,
                      }))
                    }
                  />
                </label>
                <label className="kc-native-checkbox">
                  <input
                    type="checkbox"
                    checked={capabilityForm.publish}
                    onChange={(event) =>
                      setCapabilityForm((prev) => ({
                        ...prev,
                        publish: event.target.checked,
                      }))
                    }
                  />
                  <span>创建后发布到 Agent 能力选择器</span>
                </label>
                <FormActions busy={submitting} submitLabel="创建能力" />
              </form>
            )}
          </div>
        </div>
      ) : null}
    </main>
  );
}

function StatusTile({
  icon: Icon,
  title,
  status,
  detail,
  tone,
}: {
  icon: typeof Database;
  title: string;
  status: string;
  detail: string;
  tone: "success" | "warning" | "danger" | "muted";
}) {
  return (
    <article className={`kc-native-status-tile is-${tone}`}>
      <Icon className="kc-native-icon" />
      <div>
        <span>{title}</span>
        <strong>{status}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function PanelHead({
  title,
  count,
  actionLabel,
  onAction,
}: {
  title: string;
  count: number;
  actionLabel: string;
  onAction?: () => void;
}) {
  return (
    <div className="kc-native-panel-head">
      <div>
        <h2>{title}</h2>
        <span>{count} 项</span>
      </div>
      {onAction ? (
        <button type="button" onClick={onAction}>
          <Plus className="kc-native-icon" />
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function InlineEmpty({
  icon: Icon,
  title,
  text,
}: {
  icon: typeof Database;
  title: string;
  text: string;
}) {
  return (
    <div className="kc-native-inline-empty">
      <Icon className="kc-native-state-icon" />
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

function AssetCard({ asset }: { asset: KnowledgeAssetMetadata }) {
  const Icon = capabilityIcon(asset.capability_kind, asset.asset_type);
  const sourceCoverage = knowledgeSourceCoverageText(
    [
      ...(Array.isArray(asset.provenance?.source_ids)
        ? asset.provenance.source_ids
        : []),
      ...(Array.isArray(asset.capability_package?.source_ids)
        ? asset.capability_package.source_ids
        : []),
    ].map(String),
  );
  const metrics = Array.isArray(asset.capabilities?.metrics)
    ? asset.capabilities.metrics.map(String)
    : [];
  return (
    <article className="kc-native-asset-card">
      <header>
        <span>
          <Icon className="kc-native-icon" />
          {knowledgeCapabilityLabel(asset.asset_type, asset.capability_kind)}
        </span>
        <em className={`kc-native-badge is-${asset.publish_state}`}>
          {statusCopy(asset.publish_state)}
        </em>
      </header>
      <strong>{asset.name}</strong>
      <p>{asset.description || sourceCoverage}</p>
      <dl>
        <div>
          <dt>类型</dt>
          <dd>{knowledgeCapabilityLabel(asset.asset_type, asset.capability_kind)}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{sourceCoverage}</dd>
        </div>
        <div>
          <dt>指标</dt>
          <dd>{metrics.length ? metrics.slice(0, 3).join("、") : "未声明"}</dd>
        </div>
      </dl>
      <footer>
        <span>{asset.version || "v1"}</span>
        <span>{asset.usage_policy?.permission_hint?.toString() || "按能力策略执行"}</span>
      </footer>
    </article>
  );
}

function FormActions({
  busy,
  submitLabel,
}: {
  busy: boolean;
  submitLabel: string;
}) {
  return (
    <div className="kc-native-form-actions">
      <button type="submit" disabled={busy}>
        {busy ? <Loader2 className="kc-native-icon kc-spin" /> : null}
        {submitLabel}
      </button>
    </div>
  );
}
