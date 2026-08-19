import {
  AlertCircle,
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Database,
  FileArchive,
  FileImage,
  FileSearch,
  GitBranch,
  Globe2,
  KeyRound,
  Layers3,
  Loader2,
  LockKeyhole,
  Plus,
  ShieldCheck,
  RefreshCw,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  Table2,
  UploadCloud,
  X,
  type LucideIcon,
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
  createKnowledgeAssetCapability,
  createKnowledgeAssetSpace,
  getKnowledgeAssetOverview,
  importKnowledgeAssetSource,
  listKnowledgeAssetBuildJobs,
  listKnowledgeAssetSidecars,
  listKnowledgeAssetSources,
  listKnowledgeAssetSpaces,
  type KnowledgeAssetBuildJob,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetOverview,
  type KnowledgeAssetSidecar,
  type KnowledgeAssetSource,
  type KnowledgeAssetSpace,
  type KnowledgeAssetType,
  type KnowledgeCapabilityKind,
  listKnowledgeAssets,
} from "../adk/knowledgeAssets";
import {
  knowledgeCapabilityLabel,
  knowledgeSourceCoverageText,
} from "../create/skills/knowledgeAssets";
import { AskDashboardWorkbench } from "./AskDashboardWorkbench";
import {
  CapabilityPanelSlot,
  type CapabilityBuildJobView,
  type KnowledgeCapabilityCardProps,
} from "./capabilitySlots";
import { EvaluationWorkbench } from "./EvaluationWorkbench";
import "./KnowledgeCenter.css";
import { SemanticBuildPanel } from "./SemanticBuildPanel";
// Wren mapping note: <SemanticModelingWorkbench was folded into SemanticBuildPanel for Session J2.

type LoadState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "unauthorized"; message: string; diagnostic: string }
  | { status: "error"; message: string; diagnostic: string };

type WorkbenchTab =
  | "overview"
  | "sources"
  | "semantic"
  | "askdashboard"
  | "evaluation"
  | "capabilities"
  | "jobs"
  | "settings";
type CapabilityFocusTarget = "semantic_skill" | "dashboard_skill" | "askdata";
type SourceFlowStep = "type" | "details" | "preview";
type SourceType =
  | "file"
  | "pdf"
  | "image"
  | "web"
  | "local_web"
  | "intranet_web"
  | "feishu_doc"
  | "database"
  | "schema_snapshot";

type SourceFlowState = {
  open: boolean;
  step: SourceFlowStep;
  type: SourceType;
  name: string;
  description: string;
  uri: string;
  provider: string;
  targetKnowledgeBaseId: string;
  content: string;
  selectedFile: SourceFileDraft | null;
  schemaText: string;
  metadataText: string;
  advancedOpen: boolean;
  error: WorkbenchError | null;
  lastResult: {
    source: KnowledgeAssetSource;
    job: KnowledgeAssetBuildJob;
  } | null;
};

type SpaceFormState = {
  open: boolean;
  name: string;
  description: string;
  region: string;
  defaultKnowledgeBaseId: string;
  error: WorkbenchError | null;
};

type WorkbenchError = {
  title: string;
  reason: string;
  diagnostic: string;
  action: string;
  status?: number;
};

type SourceFileDraft = {
  name: string;
  mimeType: string;
  size: number;
  data: string;
  textPreview: string;
};

function readSourceFile(file: File): Promise<SourceFileDraft> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("文件读取失败，请重新选择文件。"));
    reader.onload = () => {
      const data = typeof reader.result === "string" ? reader.result : "";
      const textReader = new FileReader();
      textReader.onerror = () => {
        resolve({
          name: file.name,
          mimeType: file.type || "application/octet-stream",
          size: file.size,
          data,
          textPreview: "",
        });
      };
      textReader.onload = () => {
        resolve({
          name: file.name,
          mimeType: file.type || "application/octet-stream",
          size: file.size,
          data,
          textPreview: typeof textReader.result === "string" ? textReader.result.slice(0, 12000) : "",
        });
      };
      textReader.readAsText(file.slice(0, 64 * 1024));
    };
    reader.readAsDataURL(file);
  });
}

const tabs: Array<{ id: WorkbenchTab; label: string; icon: LucideIcon }> = [
  { id: "overview", label: "概览", icon: Layers3 },
  { id: "sources", label: "数据源", icon: Database },
  { id: "semantic", label: "语义构建", icon: GitBranch },
  { id: "askdashboard", label: "AskTable / Dashboard", icon: BarChart3 },
  { id: "evaluation", label: "测评", icon: ShieldCheck },
  { id: "capabilities", label: "能力", icon: Sparkles },
  { id: "jobs", label: "构建任务", icon: Clock3 },
  { id: "settings", label: "设置", icon: Settings },
];

const sourceTypeGroups: Array<{
  title: string;
  items: Array<{
    type: SourceType;
    label: string;
    description: string;
    icon: LucideIcon;
  }>;
}> = [
  {
    title: "文件材料",
    items: [
      { type: "file", label: "文件", description: "Markdown、文本或结构化导出", icon: FileArchive },
      { type: "pdf", label: "PDF", description: "上传或粘贴已抽取正文", icon: UploadCloud },
      { type: "image", label: "图片", description: "图片资料登记，等待 OCR 接入", icon: FileImage },
    ],
  },
  {
    title: "页面与文档",
    items: [
      { type: "web", label: "在线网页", description: "抓取公开 URL 并写入检索后端", icon: Globe2 },
      { type: "local_web", label: "本地页面", description: "粘贴清洗后的本地 HTML/Markdown", icon: BookOpen },
      { type: "intranet_web", label: "内网页面", description: "仅保存清洗内容，不保存登录态", icon: LockKeyhole },
      { type: "feishu_doc", label: "飞书文档", description: "登记文档，等待 OAuth 连接器", icon: FileSearch },
    ],
  },
  {
    title: "数据库与 Schema",
    items: [
      { type: "database", label: "数据库", description: "Oracle、MySQL、Postgres 连接登记", icon: Database },
      { type: "schema_snapshot", label: "Schema Snapshot", description: "导入表、字段、关系快照", icon: Table2 },
    ],
  },
];

const sourceTypeLabels: Record<SourceType, string> = Object.fromEntries(
  sourceTypeGroups.flatMap((group) =>
    group.items.map((item) => [item.type, item.label]),
  ),
) as Record<SourceType, string>;

function initialSourceFlow(): SourceFlowState {
  return {
    open: false,
    step: "type",
    type: "web",
    name: "",
    description: "",
    uri: "",
    provider: "",
    targetKnowledgeBaseId: "",
    content: "",
    selectedFile: null,
    schemaText: '{\n  "models": [],\n  "fields": []\n}',
    metadataText: "{\n}",
    advancedOpen: false,
    error: null,
    lastResult: null,
  };
}

function initialSpaceForm(): SpaceFormState {
  return {
    open: false,
    name: "",
    description: "",
    region: "cn-beijing",
    defaultKnowledgeBaseId: "",
    error: null,
  };
}

function readableStatus(value?: string): string {
  const status = normalizeStatus(value);
  const labels: Record<string, string> = {
    registered: "已登记",
    needs_configuration: "需要配置",
    auth_required: "需要授权",
    importing: "正在导入",
    indexed: "已索引",
    ready: "可用",
    failed: "导入失败",
    credential_expired: "凭据过期",
    running: "运行中",
    succeeded: "成功",
    blocked: "已阻塞",
    cancelled: "已取消",
    published: "已发布",
    draft: "草稿",
    validating: "校验中",
  };
  return labels[status] || value || "未知";
}

function normalizeStatus(value?: string): string {
  const status = (value || "").trim().toLowerCase();
  if (status === "pending") return "registered";
  if (status === "not_configured") return "needs_configuration";
  if (status === "expired" || status === "expired_credential") {
    return "credential_expired";
  }
  return status || "registered";
}

function statusTone(value?: string): "success" | "warning" | "danger" | "muted" {
  const status = normalizeStatus(value);
  if (["ready", "indexed", "succeeded", "published"].includes(status)) return "success";
  if (["importing", "running", "registered", "draft", "validating"].includes(status)) {
    return "warning";
  }
  if (["failed", "blocked", "auth_required", "credential_expired"].includes(status)) {
    return "danger";
  }
  return "muted";
}

function capabilityIcon(kind: KnowledgeCapabilityKind, type?: KnowledgeAssetType) {
  if (kind === "retrieval_binding" || type === "knowledge_resource") return FileSearch;
  if (kind === "dashboard_skill" || type === "dashboard") return BarChart3;
  return Database;
}

function assetTypeForCapability(kind: KnowledgeCapabilityKind): KnowledgeAssetType {
  if (kind === "retrieval_binding") return "knowledge_resource";
  if (kind === "dashboard_skill") return "dashboard";
  return "semantic_model";
}

function slug(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80) || `asset-${Date.now().toString(36)}`
  );
}

function asWorkbenchError(
  error: unknown,
  title: string,
  fallbackReason: string,
  diagnostic: string,
  action = "请检查配置后重试。",
): WorkbenchError {
  const record = error as { status?: unknown; code?: unknown; message?: unknown };
  const rawMessage = typeof record?.message === "string" ? record.message : "";
  const status = typeof record?.status === "number" ? record.status : undefined;
  const code = typeof record?.code === "string" ? record.code : "";
  const browserFetchFailure = ["Failed", "to", "fetch"].join(" ");
  const reason = rawMessage && rawMessage !== browserFetchFailure
    ? rawMessage
    : fallbackReason;
  const detail = [
    diagnostic,
    status ? `HTTP ${status}` : "",
    code ? `错误码 ${code}` : "",
  ].filter(Boolean).join(" · ");
  return { title, reason, diagnostic: detail, action, status };
}

function parseSchemaJson(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Schema Snapshot 必须是 JSON object。");
  }
  return parsed as Record<string, unknown>;
}

function parseObjectJson(text: string, label: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON object。`);
  }
  return parsed as Record<string, unknown>;
}

function sourceCoverageLabel(value: unknown): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  for (const key of ["name", "label", "title", "id", "source_id"]) {
    if (typeof record[key] === "string" && record[key].trim()) {
      return record[key].trim();
    }
  }
  return "";
}

function latestJobForSource(
  jobs: KnowledgeAssetBuildJob[],
  sourceId: string,
): KnowledgeAssetBuildJob | null {
  return [...jobs]
    .filter((job) => job.source_id === sourceId)
    .sort((left, right) => {
      const leftTime = Date.parse(left.updated_at || left.created_at || "");
      const rightTime = Date.parse(right.updated_at || right.created_at || "");
      return (Number.isFinite(rightTime) ? rightTime : 0) -
        (Number.isFinite(leftTime) ? leftTime : 0);
    })[0] ?? null;
}

function toCapabilitySlot(asset: KnowledgeAssetMetadata): KnowledgeCapabilityCardProps {
  return {
    id: asset.asset_id,
    name: asset.name,
    kind: asset.capability_kind,
    status: normalizeStatus(asset.status) as KnowledgeCapabilityCardProps["status"],
    publish_state: asset.publish_state === "published" ? "published" :
      asset.publish_state === "archived" ? "archived" : "draft",
    source_ids: Array.isArray(asset.provenance?.source_ids)
      ? asset.provenance.source_ids.map(String)
      : [],
    created_at: typeof asset.freshness?.built_at === "string"
      ? asset.freshness.built_at
      : undefined,
    description: asset.description || undefined,
    next_cta: {
      label: asset.publish_state === "published" ? "打开能力" : "继续配置",
      description: "由能力构建器接管后续发布、验证和查询入口。",
      action: asset.publish_state === "published" ? "open" : "configure",
    },
  };
}

function toCapabilityJob(job: KnowledgeAssetBuildJob): CapabilityBuildJobView {
  const status = normalizeStatus(job.status);
  return {
    id: job.id,
    status: (["succeeded", "failed", "blocked", "cancelled", "running", "queued"].includes(status)
      ? status
      : "running") as CapabilityBuildJobView["status"],
    job_type: job.job_type,
    source_id: job.source_id || undefined,
    asset_id: job.asset_id || undefined,
    error_message:
      typeof job.error?.message === "string" ? job.error.message : undefined,
    logs_ref: job.logs_ref || undefined,
    created_at: job.created_at,
    updated_at: job.updated_at,
  };
}

export function KnowledgeCenterView() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [spaces, setSpaces] = useState<KnowledgeAssetSpace[]>([]);
  const [sources, setSources] = useState<KnowledgeAssetSource[]>([]);
  const [assets, setAssets] = useState<KnowledgeAssetMetadata[]>([]);
  const [buildJobs, setBuildJobs] = useState<KnowledgeAssetBuildJob[]>([]);
  const [sidecars, setSidecars] = useState<KnowledgeAssetSidecar[]>([]);
  const [overview, setOverview] = useState<KnowledgeAssetOverview | null>(null);
  const [activeSpaceId, setActiveSpaceId] = useState("");
  const [activeTab, setActiveTab] = useState<WorkbenchTab>("overview");
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sourceFlow, setSourceFlow] = useState<SourceFlowState>(initialSourceFlow);
  const [spaceForm, setSpaceForm] = useState<SpaceFormState>(initialSpaceForm);
  const [pageError, setPageError] = useState<WorkbenchError | null>(null);
  const activeSpaceIdRef = useRef("");
  const pendingCapabilityFocusRef = useRef<CapabilityFocusTarget | null>(null);

  const setActiveSpace = useCallback((spaceId: string) => {
    activeSpaceIdRef.current = spaceId;
    setActiveSpaceId(spaceId);
  }, []);

  const refresh = useCallback(async (preferredSpaceId?: string) => {
    setState({ status: "loading" });
    setPageError(null);
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
      const [sourceItems, jobItems, overviewPayload] = await Promise.all([
        listKnowledgeAssetSources(nextActiveSpaceId || undefined),
        listKnowledgeAssetBuildJobs(nextActiveSpaceId || undefined),
        getKnowledgeAssetOverview(nextActiveSpaceId || undefined),
      ]);
      setSpaces(spaceItems);
      setActiveSpace(nextActiveSpaceId);
      setSources(sourceItems);
      setAssets(assetPayload.items ?? []);
      setBuildJobs(jobItems);
      setSidecars(sidecarItems);
      setOverview(overviewPayload);
      setState({ status: "ready" });
    } catch (error) {
      const mapped = asWorkbenchError(
        error,
        "知识资产工作台暂不可用",
        "无法连接后端服务或读取工作台数据失败。",
        "/api/knowledge-assets/health",
        "确认 Studio 后端已启动，然后重试。",
      );
      setState({
        status: mapped.status === 401 || mapped.status === 403 ? "unauthorized" : "error",
        message: mapped.reason,
        diagnostic: mapped.diagnostic,
      });
    }
  }, [setActiveSpace]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeSpace = spaces.find((space) => space.id === activeSpaceId) ?? null;
  const spaceSources = sources.filter(
    (source) => !activeSpaceId || source.space_id === activeSpaceId,
  );
  const sidecar = sidecars.find((item) => item.id === "byaan-datastudio");

  const filteredAssets = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return assets;
    return assets.filter((asset) => {
      const values = [
        asset.name,
        asset.description,
        asset.asset_type,
        asset.capability_kind,
        knowledgeCapabilityLabel(asset.asset_type, asset.capability_kind),
      ];
      return values.some((value) => String(value ?? "").toLowerCase().includes(needle));
    });
  }, [assets, query]);
  const semanticSkills = useMemo(
    () =>
      assets.filter(
        (asset) =>
          asset.asset_type === "semantic_model" &&
          asset.capability_kind === "semantic_skill" &&
          asset.publish_state === "published",
      ),
    [assets],
  );
  const dashboardSkills = useMemo(
    () =>
      assets.filter(
        (asset) =>
          asset.asset_type === "dashboard" &&
          asset.capability_kind === "dashboard_skill" &&
          asset.publish_state === "published",
      ),
    [assets],
  );

  const assetsByKind = useMemo(() => ({
    retrieval_binding: filteredAssets.filter(
      (asset) => asset.capability_kind === "retrieval_binding",
    ),
    semantic_skill: filteredAssets.filter(
      (asset) => asset.capability_kind === "semantic_skill",
    ),
    dashboard_skill: filteredAssets.filter(
      (asset) => asset.capability_kind === "dashboard_skill",
    ),
  }), [filteredAssets]);

  const sourceCounts = overview?.source_counts ?? {};
  const capabilityCards = filteredAssets.map(toCapabilitySlot);
  const capabilityJobs = buildJobs.map(toCapabilityJob);

  const reloadSpaceScoped = useCallback(async (spaceId: string) => {
    const [sourceItems, jobItems, overviewPayload, assetPayload] = await Promise.all([
      listKnowledgeAssetSources(spaceId || undefined),
      listKnowledgeAssetBuildJobs(spaceId || undefined),
      getKnowledgeAssetOverview(spaceId || undefined),
      listKnowledgeAssets({ limit: 100 }),
    ]);
    setSources(sourceItems);
    setBuildJobs(jobItems);
    setOverview(overviewPayload);
    setAssets(assetPayload.items ?? []);
  }, []);

  function openSourceFlow(type?: SourceType) {
    setSourceFlow({
      ...initialSourceFlow(),
      open: true,
      type: type || "web",
      targetKnowledgeBaseId: activeSpace?.default_knowledge_base_id || "",
    });
    setActiveTab("sources");
  }

  function openWorkbenchTarget(tab: WorkbenchTab, target?: CapabilityFocusTarget) {
    pendingCapabilityFocusRef.current = target ?? null;
    if (target === "semantic_skill") {
      setActiveTab("semantic");
      return;
    }
    if (target === "dashboard_skill" || target === "askdata") {
      setActiveTab("askdashboard");
      return;
    }
    setActiveTab(tab);
  }

  useEffect(() => {
    if (
      !["capabilities", "semantic", "askdashboard"].includes(activeTab) ||
      !pendingCapabilityFocusRef.current
    ) return;
    const focusTarget = pendingCapabilityFocusRef.current;
    pendingCapabilityFocusRef.current = null;
    window.requestAnimationFrame(() => {
      const target = document.querySelector<HTMLElement>(
        `[data-workbench-target="${focusTarget}"], [data-capability-target="${focusTarget}"]`,
      );
      target?.scrollIntoView({ block: "start", behavior: "smooth" });
      target?.focus({ preventScroll: true });
    });
  }, [activeTab]);

  async function submitSpace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSpaceForm((prev) => ({ ...prev, error: null }));
    setSubmitting(true);
    try {
      const created = await createKnowledgeAssetSpace({
        name: spaceForm.name,
        description: spaceForm.description || undefined,
        region: spaceForm.region || undefined,
        default_knowledge_base_id: spaceForm.defaultKnowledgeBaseId || undefined,
      });
      setActiveSpace(created.id);
      setSpaceForm(initialSpaceForm());
      await refresh(created.id);
    } catch (error) {
      setSpaceForm((prev) => ({
        ...prev,
        error: asWorkbenchError(
          error,
          "创建资产空间失败",
          "资产空间没有创建成功。",
          "/api/knowledge-assets/spaces",
          "保留当前表单内容，检查名称和默认检索后端后重试。",
        ),
      }));
    } finally {
      setSubmitting(false);
    }
  }

  function validateSourceDetails(): WorkbenchError | null {
    if (!activeSpace) {
      return {
        title: "需要资产空间",
        reason: "请先创建或选择资产空间。",
        diagnostic: "当前没有 active space。",
        action: "创建资产空间后继续添加数据源。",
      };
    }
    if (!sourceFlow.name.trim()) {
      return {
        title: "缺少数据源名称",
        reason: "数据源名称用于 Agent 创建页和构建任务展示。",
        diagnostic: "字段 name 为空。",
        action: "填写一个面向业务用户可读的名称。",
      };
    }
    if (sourceFlow.type === "web") {
      try {
        const parsed = new URL(sourceFlow.uri);
        if (!["http:", "https:"].includes(parsed.protocol)) {
          throw new Error("unsupported protocol");
        }
      } catch {
        return {
          title: "网页 URL 无效",
          reason: "在线网页需要 http 或 https URL。",
          diagnostic: "第二步 URL/domain 预检查未通过。",
          action: "填写可访问的公开网页地址后重试。",
        };
      }
    }
    if (["local_web", "intranet_web"].includes(sourceFlow.type)) {
      const lower = sourceFlow.content.toLowerCase();
      if (/authorization\s*:|cookie\s*:|refresh[_-]?token|access[_-]?token/.test(lower)) {
        return {
          title: "内容包含登录态",
          reason: "本地/内网页面导入不能保存 cookie、Authorization header 或 token。",
          diagnostic: "客户端预检查检测到疑似浏览器凭据。",
          action: "移除登录态和请求头，只保留清洗后的正文内容。",
        };
      }
      if (!sourceFlow.content.trim()) {
        return {
          title: "缺少正文内容",
          reason: "当前类型需要上传或粘贴可索引正文。",
          diagnostic: "content 为空。",
          action: "粘贴清洗后的 Markdown、文本或 HTML 正文。",
        };
      }
    }
    if (["file", "pdf", "image"].includes(sourceFlow.type)) {
      if (!sourceFlow.selectedFile) {
        return {
          title: "缺少上传文件",
          reason: "文件、PDF 和图片类型需要先选择本地文件。",
          diagnostic: "file 字段为空。",
          action: "选择文件后再进入预检查。",
        };
      }
      if (sourceFlow.selectedFile.size > 8 * 1024 * 1024) {
        return {
          title: "文件过大",
          reason: "当前工作台单次导入文件不能超过 8 MB。",
          diagnostic: `文件大小 ${sourceFlow.selectedFile.size} bytes。`,
          action: "压缩文件或拆分内容后重试。",
        };
      }
      const lower = sourceFlow.selectedFile.textPreview.toLowerCase();
      if (/authorization\s*:|cookie\s*:|refresh[_-]?token|access[_-]?token/.test(lower)) {
        return {
          title: "文件内容包含登录态",
          reason: "上传文件不能包含 cookie、Authorization header 或 token。",
          diagnostic: "客户端预检查检测到疑似浏览器凭据。",
          action: "移除登录态和请求头，只上传清洗后的材料。",
        };
      }
    }
    if (sourceFlow.type === "schema_snapshot") {
      try {
        parseSchemaJson(sourceFlow.schemaText);
      } catch (error) {
        return {
          title: "Schema JSON 无效",
          reason: error instanceof Error ? error.message : "Schema Snapshot 解析失败。",
          diagnostic: "第三步 schema 预检查未通过。",
          action: "修正 JSON 后再继续。",
        };
      }
    }
    if (sourceFlow.advancedOpen) {
      try {
        parseObjectJson(sourceFlow.metadataText, "metadata");
      } catch (error) {
        return {
          title: "Metadata JSON 无效",
          reason: error instanceof Error ? error.message : "metadata 解析失败。",
          diagnostic: "高级设置 metadata 预检查未通过。",
          action: "修正 JSON 后再继续，敏感字段不要写入 metadata。",
        };
      }
    }
    return null;
  }

  async function submitSourceImport() {
    if (!activeSpace) return;
    const validation = validateSourceDetails();
    if (validation) {
      setSourceFlow((prev) => ({ ...prev, error: validation }));
      return;
    }
    setSubmitting(true);
    setSourceFlow((prev) => ({ ...prev, error: null, lastResult: null }));
    try {
      const schema = sourceFlow.type === "schema_snapshot"
        ? parseSchemaJson(sourceFlow.schemaText)
        : {};
      const advancedMetadata = parseObjectJson(sourceFlow.metadataText, "metadata");
      const result = await importKnowledgeAssetSource({
        space_id: activeSpace.id,
        source_type: sourceFlow.type,
        name: sourceFlow.name,
        description: sourceFlow.description || undefined,
        uri: sourceFlow.uri || undefined,
        provider: sourceFlow.provider || undefined,
        target_knowledge_base_id: sourceFlow.targetKnowledgeBaseId || undefined,
        region: activeSpace.region || undefined,
        content: sourceFlow.content || sourceFlow.selectedFile?.textPreview || undefined,
        content_format: sourceFlow.content || sourceFlow.selectedFile?.textPreview ? "markdown" : undefined,
        file: sourceFlow.selectedFile
          ? {
              name: sourceFlow.selectedFile.name,
              mime_type: sourceFlow.selectedFile.mimeType,
              size: sourceFlow.selectedFile.size,
              data: sourceFlow.selectedFile.data,
            }
          : undefined,
        schema,
        locator: sourceFlow.uri ? { uri: sourceFlow.uri } : {},
        metadata: {
          ...advancedMetadata,
          created_from: "agentkit_native_workbench",
          ...(sourceFlow.selectedFile
            ? {
                file_name: sourceFlow.selectedFile.name,
                file_size: sourceFlow.selectedFile.size,
                mime_type: sourceFlow.selectedFile.mimeType,
              }
            : {}),
        },
      });
      setSourceFlow((prev) => ({ ...prev, lastResult: result }));
      await reloadSpaceScoped(activeSpace.id);
    } catch (error) {
      setSourceFlow((prev) => ({
        ...prev,
        error: asWorkbenchError(
          error,
          "数据源导入失败",
          "后端没有完成数据源导入。",
          "/api/knowledge-assets/sources/import",
          "表单数据已保留，请按诊断信息修正后重试。",
        ),
      }));
    } finally {
      setSubmitting(false);
    }
  }

  async function createRetrievalBinding(source: KnowledgeAssetSource) {
    if (!activeSpace) return;
    setPageError(null);
    setSubmitting(true);
    const assetId = slug(`${source.name}-retrieval`);
    try {
      await createKnowledgeAssetCapability({
        space_id: activeSpace.id,
        asset_type: assetTypeForCapability("retrieval_binding"),
        asset_id: assetId,
        capability_kind: "retrieval_binding",
        name: `${source.name} 检索能力`,
        description: `从数据源「${source.name}」创建的检索绑定。`,
        status: "ready",
        publish_state: "published",
        source_ids: [source.id],
        type: "retrieval_binding",
        query_url: `/api/knowledge-assets/assets/knowledge_resource/${assetId}`,
        capability_package: {
          retrieval: {
            backend: "viking",
            knowledge_base_id:
              String(source.default_index_policy?.target_knowledge_base_id || "") ||
              activeSpace.default_knowledge_base_id ||
              "",
          },
        },
        capabilities: { source_count: 1 },
        usage_policy: { permission_hint: "按资产空间授权执行检索。" },
        provenance: { source_ids: [source.id] },
      });
      await reloadSpaceScoped(activeSpace.id);
      setActiveTab("capabilities");
    } catch (error) {
      setPageError(asWorkbenchError(
        error,
        "创建检索能力失败",
        "检索绑定未创建成功。",
        "/api/knowledge-assets/skill-packages",
        "确认数据源已索引且目标 Viking 检索后端可用。",
      ));
    } finally {
      setSubmitting(false);
    }
  }

  if (state.status === "loading") {
    return (
      <main className="kc-native-page">
        <StateView icon={Loader2} spin title="正在加载知识资产工作台" text="正在读取资产空间、数据源和能力状态。" />
      </main>
    );
  }

  if (state.status === "unauthorized") {
    return (
      <main className="kc-native-page">
        <StateView
          icon={ShieldAlert}
          title="未授权访问知识资产"
          text={state.message}
          diagnostic={state.diagnostic}
          actionLabel="重新加载"
          onAction={() => void refresh()}
        />
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="kc-native-page">
        <StateView
          icon={AlertCircle}
          title="知识资产工作台暂不可用"
          text={state.message}
          diagnostic={state.diagnostic}
          actionLabel="重试"
          onAction={() => void refresh()}
        />
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
            onClick={() => setSpaceForm({ ...initialSpaceForm(), open: true })}
          >
            <Plus className="kc-native-icon" />
          </button>
        </div>

        {spaces.length === 0 ? (
          <div className="kc-native-empty-card">
            <Database className="kc-native-icon" />
            <strong>还没有资产空间</strong>
            <span>先创建空间，再添加原始材料和 Agent 可选能力。</span>
            <button
              type="button"
              onClick={() => setSpaceForm({ ...initialSpaceForm(), open: true })}
            >
              创建资产空间
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
                  <small>{space.description || "资料与能力的工作空间"}</small>
                </span>
              </button>
            ))}
          </div>
        )}
      </aside>

      <section className="kc-native-main">
        <header className="kc-native-head">
          <div>
            <h1>{activeSpace?.name ?? "知识资产工作台"}</h1>
            <p>在 Studio 内管理数据源和 Agent 可运行能力。</p>
          </div>
          <div className="kc-native-actions">
            <button type="button" onClick={() => void refresh()}>
              <RefreshCw className="kc-native-icon" />
              刷新
            </button>
            <button type="button" onClick={() => openSourceFlow()} disabled={!activeSpace}>
              <Plus className="kc-native-icon" />
              添加数据源
            </button>
          </div>
        </header>

        <nav className="kc-native-tabs" aria-label="知识资产工作台视图">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                type="button"
                className={activeTab === tab.id ? "is-active" : ""}
                aria-pressed={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon className="kc-native-icon" />
                {tab.label}
              </button>
            );
          })}
        </nav>

        {pageError ? (
          <ErrorPanel error={pageError} onRetry={() => setPageError(null)} />
        ) : null}

        <div className="kc-native-view">
          {activeTab === "overview" ? (
            <OverviewTab
              sourceCounts={sourceCounts}
              capabilityCounts={overview?.capability_counts ?? {}}
              sources={spaceSources}
              assets={assets}
              jobs={buildJobs}
              onAddSource={() => openSourceFlow()}
              onCreateSpace={() => setSpaceForm({ ...initialSpaceForm(), open: true })}
              onOpenSources={() => openWorkbenchTarget("sources")}
              onOpenCapability={(target) => {
                if (target === "semantic_skill") openWorkbenchTarget("semantic", target);
                else openWorkbenchTarget("askdashboard", target);
              }}
              onOpenEvaluation={() => openWorkbenchTarget("evaluation")}
            />
          ) : null}
          {activeTab === "sources" ? (
            <SourcesTab
              sources={spaceSources}
              jobs={buildJobs}
              onAddSource={() => openSourceFlow()}
              onCreateRetrievalBinding={(source) => void createRetrievalBinding(source)}
              busy={submitting}
            />
          ) : null}
          {activeTab === "semantic" ? (
            <div className="kc-semantic-composite" data-workbench-target="semantic_skill" tabIndex={-1}>
              <SemanticBuildPanel
                spaceId={activeSpace?.id ?? ""}
                sources={spaceSources}
                assets={assets}
                buildJobs={buildJobs}
                onRefresh={() => refresh(activeSpaceIdRef.current)}
              />
            </div>
          ) : null}
          {activeTab === "askdashboard" ? (
            <div data-workbench-target="askdata" tabIndex={-1}>
              <AskDashboardWorkbench
                activeSpace={activeSpace}
                semanticSkills={semanticSkills}
                dashboardSkills={dashboardSkills}
                buildJobs={buildJobs}
                onRefresh={() => refresh(activeSpaceIdRef.current)}
              />
            </div>
          ) : null}
          {activeTab === "capabilities" ? (
            <CapabilitiesTab
              query={query}
              onQueryChange={setQuery}
              assetsByKind={assetsByKind}
              capabilityCards={capabilityCards}
              capabilityJobs={capabilityJobs}
              semanticSkills={semanticSkills}
            />
          ) : null}
          {activeTab === "evaluation" ? (
            <EvaluationWorkbench
              activeSpace={activeSpace}
              assets={assets}
            />
          ) : null}
          {activeTab === "jobs" ? (
            <BuildJobsTab jobs={buildJobs} sources={spaceSources} />
          ) : null}
          {activeTab === "settings" ? (
            <SettingsTab
              activeSpace={activeSpace}
              sidecar={sidecar}
              health={{ configured: true, mock: false }}
            />
          ) : null}
        </div>
      </section>

      {spaceForm.open ? (
        <Modal title="创建资产空间" onClose={() => setSpaceForm(initialSpaceForm())}>
          {spaceForm.error ? <ErrorPanel error={spaceForm.error} compact /> : null}
          <form className="kc-native-form" onSubmit={submitSpace}>
            <Field label="空间名称">
              <input
                required
                value={spaceForm.name}
                onChange={(event) =>
                  setSpaceForm((prev) => ({ ...prev, name: event.target.value }))
                }
              />
            </Field>
            <Field label="描述">
              <textarea
                value={spaceForm.description}
                onChange={(event) =>
                  setSpaceForm((prev) => ({ ...prev, description: event.target.value }))
                }
              />
            </Field>
            <Field label="区域">
              <input
                value={spaceForm.region}
                onChange={(event) =>
                  setSpaceForm((prev) => ({ ...prev, region: event.target.value }))
                }
              />
            </Field>
            <Field label="默认检索后端">
              <input
                value={spaceForm.defaultKnowledgeBaseId}
                placeholder="可稍后在检索能力中指定"
                onChange={(event) =>
                  setSpaceForm((prev) => ({
                    ...prev,
                    defaultKnowledgeBaseId: event.target.value,
                  }))
                }
              />
            </Field>
            <FormActions busy={submitting} submitLabel="创建空间" />
          </form>
        </Modal>
      ) : null}

      {sourceFlow.open ? (
        <Modal title="添加数据源" onClose={() => setSourceFlow(initialSourceFlow())}>
          <SourceFlow
            flow={sourceFlow}
            activeSpace={activeSpace}
            busy={submitting}
            onChange={setSourceFlow}
            onValidate={() => {
              const validation = validateSourceDetails();
              if (validation) {
                setSourceFlow((prev) => ({ ...prev, error: validation }));
                return;
              }
              setSourceFlow((prev) => ({ ...prev, error: null, step: "preview" }));
            }}
            onSubmit={() => void submitSourceImport()}
            onCreateRetrieval={
              sourceFlow.lastResult
                ? () => void createRetrievalBinding(sourceFlow.lastResult!.source)
                : undefined
            }
          />
        </Modal>
      ) : null}
    </main>
  );
}

function OverviewTab({
  sourceCounts,
  capabilityCounts,
  sources,
  assets,
  jobs,
  onAddSource,
  onCreateSpace,
  onOpenSources,
  onOpenCapability,
  onOpenEvaluation,
}: {
  sourceCounts: Record<string, number>;
  capabilityCounts: Record<string, number>;
  sources: KnowledgeAssetSource[];
  assets: KnowledgeAssetMetadata[];
  jobs: KnowledgeAssetBuildJob[];
  onAddSource: () => void;
  onCreateSpace: () => void;
  onOpenSources: () => void;
  onOpenCapability: (target: CapabilityFocusTarget) => void;
  onOpenEvaluation: () => void;
}) {
  const latestJob = jobs[0];
  return (
    <div className="kc-native-overview">
      <div className="kc-native-status-grid">
        <StatusTile icon={Database} title="数据源" value={String(sources.length)} detail={`可用 ${sourceCounts.ready || 0} · 已索引 ${sourceCounts.indexed || 0}`} tone="success" />
        <StatusTile icon={Sparkles} title="能力" value={String(assets.length)} detail={`检索 ${capabilityCounts.retrieval_binding || 0} · 语义 ${capabilityCounts.semantic_skill || 0}`} tone="success" />
        <StatusTile icon={ShieldCheck} title="测评" value="可运行" detail="本地 deterministic checks + optional judge" tone="success" />
        <StatusTile icon={Clock3} title="构建任务" value={latestJob ? readableStatus(latestJob.status) : "暂无"} detail={latestJob?.job_type || "等待导入或构建"} tone={statusTone(latestJob?.status)} />
        <StatusTile icon={KeyRound} title="凭据" value={sourceCounts.credential_expired ? "有过期" : "安全"} detail="明文凭据不进入前端状态" tone={sourceCounts.credential_expired ? "danger" : "success"} />
      </div>
      {sources.length === 0 ? (
        <ActionEmpty
          icon={Database}
          title="从添加第一个数据源开始"
          text="文件、网页、飞书文档、数据库连接和 Schema Snapshot 都先作为原始材料登记。"
          actionLabel="添加数据源"
          onAction={onAddSource}
          secondaryLabel="创建空间"
          onSecondary={onCreateSpace}
        />
      ) : (
        <section className="kc-native-panel">
          <PanelHead title="下一步" count={5} />
          <div className="kc-native-next-grid">
            <NextAction
              icon={FileSearch}
              title="创建检索能力"
              text="把已索引数据源变成 Agent 可选择的 Retrieval Binding。"
              onClick={onOpenSources}
            />
            <NextAction
              icon={Database}
              title="生成语义 Skill"
              text="从 Schema 数据源生成包含 MDL、策略、评测和受治理查询工具的 Skill。"
              onClick={() => onOpenCapability("semantic_skill")}
            />
            <NextAction
              icon={BarChart3}
              title="新建 Dashboard Skill"
              text="基于已发布 Semantic Skill 生成可查询的 dashboard_spec 和同源工具。"
              onClick={() => onOpenCapability("dashboard_skill")}
            />
            <NextAction
              icon={ShieldCheck}
              title="运行测评"
              text="验证 Semantic Skill、AskTable Query 和 Dashboard Skill 的证据完整性。"
              onClick={onOpenEvaluation}
            />
            <NextAction
              icon={Search}
              title="打开 AskData"
              text="通过已发布 Semantic Skill 的 governed query 获取指标、SQL 和证据。"
              onClick={() => onOpenCapability("askdata")}
            />
          </div>
        </section>
      )}
    </div>
  );
}

function SourcesTab({
  sources,
  jobs,
  onAddSource,
  onCreateRetrievalBinding,
  busy,
}: {
  sources: KnowledgeAssetSource[];
  jobs: KnowledgeAssetBuildJob[];
  onAddSource: () => void;
  onCreateRetrievalBinding: (source: KnowledgeAssetSource) => void;
  busy: boolean;
}) {
  return (
    <section className="kc-native-panel">
      <PanelHead title="数据源" count={sources.length} actionLabel="添加数据源" onAction={onAddSource} />
      {sources.length === 0 ? (
        <ActionEmpty
          icon={Database}
          title="暂无数据源"
          text="添加原始材料后，工作台会显示导入状态、凭据需求和 source 级任务历史。"
          actionLabel="添加数据源"
          onAction={onAddSource}
        />
      ) : (
        <div className="kc-native-source-grid">
          {sources.map((source) => (
            <SourceCard
              key={source.id}
              source={source}
              job={latestJobForSource(jobs, source.id)}
              jobs={jobs.filter((job) => job.source_id === source.id)}
              busy={busy}
              onCreateRetrieval={() => onCreateRetrievalBinding(source)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function CapabilitiesTab({
  query,
  onQueryChange,
  assetsByKind,
  capabilityCards,
  capabilityJobs,
  semanticSkills,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  assetsByKind: Record<"retrieval_binding" | "semantic_skill" | "dashboard_skill", KnowledgeAssetMetadata[]>;
  capabilityCards: KnowledgeCapabilityCardProps[];
  capabilityJobs: CapabilityBuildJobView[];
  semanticSkills: KnowledgeAssetMetadata[];
}) {
  return (
    <section className="kc-native-panel">
      <div className="kc-native-panel-head">
        <div>
          <h2>Agent 能力</h2>
          <span>创建 Agent 时选择能力，不选择原始材料。</span>
        </div>
        <div className="kc-native-search">
          <Search className="kc-native-icon" />
          <input
            value={query}
            placeholder="搜索能力名称或类型"
            onChange={(event) => onQueryChange(event.target.value)}
          />
        </div>
      </div>
      <CapabilityGroup title="Retrieval Binding" assets={assetsByKind.retrieval_binding} emptyText="从已索引数据源创建检索能力。" />
      <section className="kc-capability-target" data-capability-target="semantic_skill" tabIndex={-1}>
        <CapabilityPanelSlot
          kind="semantic_skill"
          capabilities={capabilityCards.filter((item) => item.kind === "semantic_skill")}
          build_jobs={capabilityJobs.filter((job) => job.job_type.includes("semantic"))}
          render={({ capabilities }) => (
            <CapabilitySelectorList
              capabilities={capabilities}
              emptyText="到语义构建页发布 Semantic Skill 后，这里会出现在创建 Agent 的能力选择列表。"
            />
          )}
        />
      </section>
      <section className="kc-capability-target" data-capability-target="dashboard_skill" tabIndex={-1}>
        <CapabilityPanelSlot
          kind="dashboard_skill"
          capabilities={capabilityCards.filter((item) => item.kind === "dashboard_skill")}
          build_jobs={capabilityJobs.filter((job) => job.job_type.includes("dashboard"))}
          render={({ capabilities }) => (
            <CapabilitySelectorList
              capabilities={capabilities}
              emptyText="到 AskTable / Dashboard 页生成 Dashboard Skill 后，这里会出现可选看板能力。"
            />
          )}
        />
      </section>
      <CapabilityGroup title="AskTable 语义能力" assets={semanticSkills} emptyText="AskTable 使用已发布 Semantic Skill，不作为单独构建器挂载。" />
    </section>
  );
}

function CapabilitySelectorList({
  capabilities,
  emptyText,
}: {
  capabilities: KnowledgeCapabilityCardProps[];
  emptyText: string;
}) {
  if (capabilities.length === 0) {
    return <div className="kc-native-inline-empty"><span>{emptyText}</span></div>;
  }
  return (
    <div className="kc-capability-selector-list">
      {capabilities.map((capability) => (
        <article key={capability.id} className="kc-native-asset-card">
          <header>
            <span>
              <strong>{capability.name}</strong>
              <p>{capability.description || "Agent 创建时可选择的已发布能力。"}</p>
            </span>
            <span className={`kc-native-badge is-${statusTone(capability.status)}`}>
              {readableStatus(capability.status)}
            </span>
          </header>
          <dl>
            <div>
              <dt>类型</dt>
              <dd>{capability.kind}</dd>
            </div>
            <div>
              <dt>发布态</dt>
              <dd>{capability.publish_state}</dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  );
}

function BuildJobsTab({
  jobs,
  sources,
}: {
  jobs: KnowledgeAssetBuildJob[];
  sources: KnowledgeAssetSource[];
}) {
  const sourceName = (sourceId?: string | null) =>
    sources.find((source) => source.id === sourceId)?.name || "未关联数据源";
  return (
    <section className="kc-native-panel">
      <PanelHead title="构建任务" count={jobs.length} />
      {jobs.length === 0 ? (
        <ActionEmpty icon={Clock3} title="暂无构建任务" text="导入数据源或创建能力后，这里会按 source 展示终态和错误。" />
      ) : (
        <div className="kc-native-job-list">
          {jobs.map((job) => (
            <article key={job.id} className="kc-native-job-row">
              <span className={`kc-native-badge is-${statusTone(job.status)}`}>
                {readableStatus(job.status)}
              </span>
              <div>
                <strong>{job.job_type}</strong>
                <p>{sourceName(job.source_id)}</p>
                {typeof job.error?.message === "string" ? (
                  <small>{job.error.message}</small>
                ) : null}
              </div>
              <time>{job.updated_at || job.created_at || ""}</time>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function SettingsTab({
  activeSpace,
  sidecar,
  health,
}: {
  activeSpace: KnowledgeAssetSpace | null;
  sidecar?: KnowledgeAssetSidecar;
  health: { configured: boolean; mock: boolean };
}) {
  return (
    <section className="kc-native-panel">
      <PanelHead title="设置与诊断" count={3} />
      <div className="kc-native-settings-grid">
        <DiagnosticCard title="本地资产仓" value={health.configured ? "已配置" : "未配置"} detail={health.mock ? "mock 模式" : "SQLite Asset Store 仅作为后端存储。"} />
        <DiagnosticCard title="默认检索后端" value={activeSpace?.default_knowledge_base_id ? "已绑定" : "未配置"} detail={activeSpace?.default_knowledge_base_id || "可在空间或检索能力中配置。"} />
        <DiagnosticCard title="BYAAN sidecar" value={sidecar?.configured ? "可用" : "未配置"} detail={sidecar?.configured ? "仅作为受治理后端能力，不作为主 UI。" : "缺失时原生工作台仍可打开。"} />
      </div>
    </section>
  );
}

function SourceFlow({
  flow,
  activeSpace,
  busy,
  onChange,
  onValidate,
  onSubmit,
  onCreateRetrieval,
}: {
  flow: SourceFlowState;
  activeSpace: KnowledgeAssetSpace | null;
  busy: boolean;
  onChange: (updater: (prev: SourceFlowState) => SourceFlowState) => void;
  onValidate: () => void;
  onSubmit: () => void;
  onCreateRetrieval?: () => void;
}) {
  async function handleFile(file: File | undefined) {
    if (!file) return;
    try {
      const selectedFile = await readSourceFile(file);
      onChange((prev) => ({
        ...prev,
        selectedFile,
        name: prev.name || selectedFile.name.replace(/\.[^.]+$/, ""),
        error: null,
      }));
    } catch (error) {
      onChange((prev) => ({
        ...prev,
        selectedFile: null,
        error: asWorkbenchError(
          error,
          "读取文件失败",
          "浏览器没有完成本地文件读取。",
          "FileReader",
          "重新选择文件或改为粘贴清洗后的正文。",
        ),
      }));
    }
  }

  return (
    <div className="kc-source-flow">
      <div className="kc-flow-steps" aria-label="添加数据源步骤">
        {(["type", "details", "preview"] as SourceFlowStep[]).map((step, index) => (
          <span key={step} className={flow.step === step ? "is-active" : ""}>
            {index + 1}. {step === "type" ? "选择类型" : step === "details" ? "填写信息" : "预检查"}
          </span>
        ))}
      </div>
      {flow.error ? <ErrorPanel error={flow.error} compact /> : null}
      {flow.lastResult ? (
        <div className="kc-import-result">
          <CheckCircle2 className="kc-native-icon" />
          <div>
            <strong>{readableStatus(flow.lastResult.source.status)}</strong>
            <p>{flow.lastResult.source.status_reason || "数据源状态已更新。"}</p>
          </div>
          {normalizeStatus(flow.lastResult.source.status) === "indexed" ? (
            <button type="button" onClick={onCreateRetrieval}>
              创建检索能力
            </button>
          ) : null}
        </div>
      ) : null}
      {flow.step === "type" ? (
        <div className="kc-source-type-groups">
          {sourceTypeGroups.map((group) => (
            <section key={group.title}>
              <h3>{group.title}</h3>
              <div className="kc-source-type-grid">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.type}
                      type="button"
                      className={flow.type === item.type ? "is-selected" : ""}
                      onClick={() => onChange((prev) => ({ ...prev, type: item.type }))}
                    >
                      <Icon className="kc-native-icon" />
                      <strong>{item.label}</strong>
                      <span>{item.description}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
          <div className="kc-native-form-actions">
            <button type="button" onClick={() => onChange((prev) => ({ ...prev, step: "details" }))}>
              下一步
              <ChevronRight className="kc-native-icon" />
            </button>
          </div>
        </div>
      ) : null}
      {flow.step === "details" ? (
        <div className="kc-native-form">
          <Field label="数据源名称">
            <input
              required
              value={flow.name}
              onChange={(event) => onChange((prev) => ({ ...prev, name: event.target.value }))}
            />
          </Field>
          {flow.type === "web" ? (
            <Field label="网页 URL">
              <input
                value={flow.uri}
                placeholder="https://example.com/docs"
                onChange={(event) => onChange((prev) => ({ ...prev, uri: event.target.value }))}
              />
            </Field>
          ) : null}
          {["local_web", "intranet_web", "file", "pdf", "image"].includes(flow.type) ? (
            <Field label="清洗后的正文">
              <textarea
                className="kc-native-large-textarea"
                value={flow.content}
                placeholder="只粘贴正文内容，不包含 Cookie、Authorization header 或 session token。"
                onChange={(event) => onChange((prev) => ({ ...prev, content: event.target.value }))}
              />
            </Field>
          ) : null}
          {["file", "pdf", "image"].includes(flow.type) ? (
            <Field label="上传文件">
              <div className="kc-file-picker">
                <input
                  type="file"
                  accept={flow.type === "pdf" ? ".pdf,application/pdf" : flow.type === "image" ? "image/*" : ".md,.markdown,.txt,.json,.csv,.pdf,image/*"}
                  onChange={(event) => void handleFile(event.currentTarget.files?.[0])}
                />
                <span>
                  {flow.selectedFile
                    ? `${flow.selectedFile.name} · ${Math.ceil(flow.selectedFile.size / 1024)} KB`
                    : "选择本地文件，提交前会做大小与凭据预检查。"}
                </span>
              </div>
            </Field>
          ) : null}
          {flow.type === "feishu_doc" ? (
            <InfoBlock
              icon={KeyRound}
              title="需要飞书 OAuth"
              text="当前工作台只登记飞书文档来源并返回需要授权状态，不会 mock 导入成功。"
            />
          ) : null}
          {flow.type === "database" ? (
            <InfoBlock
              icon={Database}
              title="只登记连接元数据"
              text="数据库凭据不会进入前端；schema introspection 和语义构建由后续 builder 接管。"
            />
          ) : null}
          {flow.type === "schema_snapshot" ? (
            <Field label="Schema JSON">
              <textarea
                className="kc-native-large-textarea"
                value={flow.schemaText}
                onChange={(event) => onChange((prev) => ({ ...prev, schemaText: event.target.value }))}
              />
            </Field>
          ) : null}
          <Field label="描述">
            <textarea
              value={flow.description}
              onChange={(event) => onChange((prev) => ({ ...prev, description: event.target.value }))}
            />
          </Field>
          <button
            className="kc-advanced-toggle"
            type="button"
            onClick={() => onChange((prev) => ({ ...prev, advancedOpen: !prev.advancedOpen }))}
          >
            高级设置
          </button>
          {flow.advancedOpen ? (
            <div className="kc-advanced-fields">
              <Field label="Provider">
                <input
                  value={flow.provider}
                  placeholder="web / oracle / mysql / postgres / feishu"
                  onChange={(event) => onChange((prev) => ({ ...prev, provider: event.target.value }))}
                />
              </Field>
              <Field label="目标检索后端">
                <input
                  value={flow.targetKnowledgeBaseId}
                  placeholder={activeSpace?.default_knowledge_base_id || "可留空进入需要配置状态"}
                  onChange={(event) => onChange((prev) => ({ ...prev, targetKnowledgeBaseId: event.target.value }))}
                />
              </Field>
              <Field label="URI 或连接标识">
                <input
                  value={flow.uri}
                  placeholder="不要填写用户名、密码、cookie 或 Authorization header"
                  onChange={(event) => onChange((prev) => ({ ...prev, uri: event.target.value }))}
                />
              </Field>
              <Field label="metadata JSON">
                <textarea
                  className="kc-native-large-textarea"
                  value={flow.metadataText}
                  placeholder="{\n}"
                  onChange={(event) => onChange((prev) => ({ ...prev, metadataText: event.target.value }))}
                />
              </Field>
            </div>
          ) : null}
          <div className="kc-native-form-actions">
            <button type="button" onClick={() => onChange((prev) => ({ ...prev, step: "type" }))}>
              上一步
            </button>
            <button type="button" onClick={onValidate}>
              预检查
            </button>
          </div>
        </div>
      ) : null}
      {flow.step === "preview" ? (
        <div className="kc-preview-list">
          <PreviewItem label="类型" value={sourceTypeLabels[flow.type]} />
          <PreviewItem label="名称" value={flow.name} />
          <PreviewItem label="写入检索后端" value={flow.targetKnowledgeBaseId || "未配置，提交后进入需要配置状态"} />
          <PreviewItem label="凭据需求" value={flow.type === "feishu_doc" ? "需要 OAuth" : flow.type === "database" ? "需要后端凭据仓" : "不需要前端凭据"} />
          <PreviewItem label="预期状态" value={expectedSourceStatus(flow)} />
          <div className="kc-native-form-actions">
            <button type="button" onClick={() => onChange((prev) => ({ ...prev, step: "details" }))}>
              返回修改
            </button>
            <button type="button" disabled={busy} onClick={onSubmit}>
              {busy ? <Loader2 className="kc-native-icon kc-spin" /> : null}
              提交导入
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function expectedSourceStatus(flow: SourceFlowState): string {
  if (flow.type === "database") return "需要配置凭据";
  if (flow.type === "feishu_doc") return "需要授权";
  if (flow.type === "schema_snapshot") return "可用";
  return flow.targetKnowledgeBaseId ? "已索引或导入失败" : "需要配置检索后端";
}

function SourceCard({
  source,
  job,
  jobs,
  busy,
  onCreateRetrieval,
}: {
  source: KnowledgeAssetSource;
  job: KnowledgeAssetBuildJob | null;
  jobs: KnowledgeAssetBuildJob[];
  busy: boolean;
  onCreateRetrieval: () => void;
}) {
  const status = normalizeStatus(source.status);
  const canCreateRetrieval = ["indexed", "ready"].includes(status) &&
    source.source_type !== "schema_snapshot" &&
    source.source_type !== "database";
  return (
    <article className="kc-native-source-card">
      <header>
        <div>
          <strong>{source.name}</strong>
          <span>{sourceTypeLabels[source.source_type as SourceType] || source.source_type}</span>
        </div>
        <span className={`kc-native-badge is-${statusTone(source.status)}`}>
          {readableStatus(source.status)}
        </span>
      </header>
      <p>{source.status_reason || source.description || "等待下一步操作。"}</p>
      <dl>
        <div>
          <dt>最近任务</dt>
          <dd>{job ? `${job.job_type} · ${readableStatus(job.status)}` : "暂无"}</dd>
        </div>
        <div>
          <dt>同步状态</dt>
          <dd>{String(source.metadata?.last_synced_at || source.metadata?.schema_status || "未同步")}</dd>
        </div>
      </dl>
      <div className="kc-source-job-history" aria-label={`${source.name} 构建任务历史`}>
        {jobs.length ? (
          jobs.slice(0, 3).map((item) => (
            <span key={item.id}>
              {item.job_type} · {readableStatus(item.status)}
            </span>
          ))
        ) : (
          <span>暂无 source 级任务历史</span>
        )}
      </div>
      <footer>
        {status === "needs_configuration" ? <button type="button">去配置</button> : null}
        {status === "auth_required" ? <button type="button">配置授权</button> : null}
        {status === "failed" ? <button type="button">重试导入</button> : null}
        {canCreateRetrieval ? (
          <button type="button" disabled={busy} onClick={onCreateRetrieval}>
            创建检索能力
          </button>
        ) : null}
      </footer>
    </article>
  );
}

function CapabilityGroup({
  title,
  assets,
  emptyText,
}: {
  title: string;
  assets: KnowledgeAssetMetadata[];
  emptyText: string;
}) {
  return (
    <section className="kc-capability-group">
      <h3>{title}</h3>
      {assets.length === 0 ? (
        <p className="kc-muted-line">{emptyText}</p>
      ) : (
        <div className="kc-native-asset-grid">
          {assets.map((asset) => (
            <AssetCard key={`${asset.asset_type}:${asset.asset_id}`} asset={asset} />
          ))}
        </div>
      )}
    </section>
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
    ].map(sourceCoverageLabel).filter(Boolean),
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
        <em className={`kc-native-badge is-${statusTone(asset.publish_state)}`}>
          {readableStatus(asset.publish_state)}
        </em>
      </header>
      <strong>{asset.name}</strong>
      <p>{asset.description || sourceCoverage || "已登记能力。"}</p>
      <dl>
        <div>
          <dt>来源覆盖</dt>
          <dd>{sourceCoverage || "未声明"}</dd>
        </div>
        <div>
          <dt>指标</dt>
          <dd>{metrics.length ? metrics.slice(0, 3).join("、") : "未声明"}</dd>
        </div>
      </dl>
    </article>
  );
}

function StatusTile({
  icon: Icon,
  title,
  value,
  detail,
  tone,
}: {
  icon: LucideIcon;
  title: string;
  value: string;
  detail: string;
  tone: "success" | "warning" | "danger" | "muted";
}) {
  return (
    <article className={`kc-native-status-tile is-${tone}`}>
      <Icon className="kc-native-icon" />
      <div>
        <span>{title}</span>
        <strong>{value}</strong>
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
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="kc-native-panel-head">
      <div>
        <h2>{title}</h2>
        <span>{count} 项</span>
      </div>
      {actionLabel && onAction ? (
        <button type="button" onClick={onAction}>
          <Plus className="kc-native-icon" />
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function ActionEmpty({
  icon: Icon,
  title,
  text,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondary,
}: {
  icon: LucideIcon;
  title: string;
  text: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  return (
    <div className="kc-native-inline-empty">
      <Icon className="kc-native-state-icon" />
      <strong>{title}</strong>
      <span>{text}</span>
      <div>
        {actionLabel && onAction ? <button type="button" onClick={onAction}>{actionLabel}</button> : null}
        {secondaryLabel && onSecondary ? <button type="button" onClick={onSecondary}>{secondaryLabel}</button> : null}
      </div>
    </div>
  );
}

function NextAction({
  icon: Icon,
  title,
  text,
  onClick,
}: {
  icon: LucideIcon;
  title: string;
  text: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className="kc-next-action" onClick={onClick}>
      <Icon className="kc-native-icon" />
      <strong>{title}</strong>
      <p>{text}</p>
    </button>
  );
}

function ErrorPanel({
  error,
  onRetry,
  compact,
}: {
  error: WorkbenchError;
  onRetry?: () => void;
  compact?: boolean;
}) {
  return (
    <div className={`kc-error-panel ${compact ? "is-compact" : ""}`} role="alert">
      <AlertCircle className="kc-native-icon" />
      <div>
        <strong>{error.title}</strong>
        <p>{error.reason}</p>
        <small>{error.diagnostic}</small>
        <span>{error.action}</span>
      </div>
      {onRetry ? <button type="button" onClick={onRetry}>重试</button> : null}
    </div>
  );
}

function StateView({
  icon: Icon,
  title,
  text,
  diagnostic,
  actionLabel,
  onAction,
  spin,
}: {
  icon: LucideIcon;
  title: string;
  text: string;
  diagnostic?: string;
  actionLabel?: string;
  onAction?: () => void;
  spin?: boolean;
}) {
  return (
    <div className="kc-native-state" role="status">
      <Icon className={`kc-native-state-icon ${spin ? "kc-spin" : ""}`} />
      <strong>{title}</strong>
      <span>{text}</span>
      {diagnostic ? <small>{diagnostic}</small> : null}
      {actionLabel && onAction ? (
        <button type="button" onClick={onAction}>
          <RefreshCw className="kc-native-icon" />
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="kc-native-drawer" role="dialog" aria-modal="true">
      <div className="kc-native-drawer-panel">
        <header>
          <h2>{title}</h2>
          <button type="button" onClick={onClose} aria-label="关闭">
            <X className="kc-native-icon" />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label>
      <span>{label}</span>
      {children}
    </label>
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

function InfoBlock({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <div className="kc-info-block">
      <Icon className="kc-native-icon" />
      <div>
        <strong>{title}</strong>
        <span>{text}</span>
      </div>
    </div>
  );
}

function PreviewItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="kc-preview-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DiagnosticCard({
  title,
  value,
  detail,
}: {
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="kc-diagnostic-card">
      <span>{title}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}
