import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  Activity,
  ArrowLeft,
  Bell,
  Check,
  CheckCircle2,
  ChevronRight,
  CirclePlus,
  Database,
  FileText,
  Globe,
  History,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Settings2,
  Share2,
  ToyBrick,
  Upload,
  User,
  X,
} from "lucide-react";
import {
  resolveIdentity,
  setLocalUser,
  USERNAME_RE,
  type AuthStatus,
} from "../../../adk/identity";
import {
  getRuntimes,
  type CloudRuntime,
} from "../../../adk/client";
import { ArtifactViewer } from "../artifact/ArtifactViewer";
import { AssistantPanel } from "../assistant/AssistantPanel";
import { DataToolDrawer } from "../creator/DataToolDrawer";
import { SkillCreateLanding } from "../creator/SkillCreateLanding";
import {
  assistantReducer,
  initialAssistantState,
} from "../assistant/assistant-reducer";
import type { ConversationTurnModel } from "../assistant/assistant-model";
import {
  knowledgeApi,
  KnowledgeApiError,
  type AdapterCapabilityResult,
  type CreateConnectionInput,
  type JobResult,
  type OAuthAuthorizeResult,
  type UploadResult,
} from "../api/client";
import { OAuthFlowPollError, waitForOAuthConnection } from "../api/oauthFlow";
import { Modal } from "../components/Modal";
import { SkillWorkspaceShell } from "../workspace/SkillWorkspaceShell";
import { readQuery, writeQuery } from "../application/cache";
import type {
  Artifact,
  ConnectorDefinition,
  ConnectionProfile,
  Draft,
  Invocation,
  JsonObject,
  JsonValue,
  KnowledgeInvocationEvent,
  Revision,
  TemplateKey,
  WorkspaceResource,
  Publication,
} from "../domain/types";
import {
  authSchemaOptions,
  schemaForAuth,
  schemaProperties,
} from "../domain/connectionSchema";
import "./knowledge-workspace.css";

type WorkspaceFile =
  | "connection"
  | "resource"
  | "skill_new"
  | "draft"
  | "published";

interface WorkspaceRoute {
  file: WorkspaceFile;
  draftId: string;
  connectionId: string;
  resourceId: string;
  modal: string;
}

const STATUS_LABELS: Record<ConnectionProfile["status"], string> = {
  draft: "草稿",
  validating: "验证中",
  ready: "可用",
  degraded: "需关注",
  error: "验证失败",
  revoked: "已撤销",
};

const DRAFT_LIFECYCLE_LABELS: Record<Draft["lifecycle"], string> = {
  editing: "编辑中",
  generating: "生成中",
  generated: "已生成",
  validating: "校验中",
  ready_to_publish: "待发布",
  published: "已发布",
  failed: "运行失败",
  cancelled: "已取消",
};

const TEMPLATE_DEFINITIONS: Array<{
  key: TemplateKey;
  label: string;
  description: string;
  config: JsonObject;
}> = [
  {
    key: "generic",
    label: "Auto",
    description: "由 Agent 根据业务任务自动推荐呈现方式",
    config: { mode: "auto" },
  },
  {
    key: "semantic",
    label: "Semantic",
    description: "沉淀 schema、指标口径、只读 SQL 和样例问题",
    config: { mode: "semantic_validation" },
  },
  {
    key: "dashboard",
    label: "Dashboard",
    description: "基于真实 schema/data 生成可筛选、可刷新的 HTML 看板",
    config: { mode: "interactive_dashboard" },
  },
  {
    key: "sop",
    label: "SOP",
    description: "从文档、OpenViking 和 action 证据生成可执行流程",
    config: { mode: "evidence_sop" },
  },
];

const TEMPLATE_LABELS: Record<TemplateKey, string> = {
  generic: "Generic",
  semantic: "Semantic",
  dashboard: "Dashboard",
  sop: "SOP",
};

function templateLabel(value?: TemplateKey): string {
  return TEMPLATE_LABELS[value || "generic"] || TEMPLATE_LABELS.generic;
}

function templateDefinition(value?: TemplateKey) {
  return TEMPLATE_DEFINITIONS.find((item) => item.key === value);
}

const ERROR_LABELS: Record<string, string> = {
  AUTH_REQUIRED: "登录状态已失效，请重新登录后重试。",
  FORBIDDEN: "当前账号没有访问该资源的权限。",
  WORKSPACE_NOT_FOUND: "当前工作区不存在或已被移除，请返回工作台后重试。",
  CONNECTION_NOT_READY: "连接尚未可用，请先完成验证。",
  CONNECTION_VALIDATION_FAILED: "连接验证失败，请检查配置并重试。",
  LEASE_EXPIRED: "连接授权已过期，请重新验证连接后重试。",
  AUTOSKILL_UNAVAILABLE: "Skill 服务暂不可用，请稍后重试。",
  AUTOSKILL_PROTOCOL_ERROR: "Skill 服务协议异常，请联系管理员。",
  SKILL_ZIP_INVALID: "生成的 Skill 包未通过安全校验，请重新生成。",
  ARTIFACT_UNSAFE: "运行产物未通过安全校验，暂不能展示。",
  REVISION_CONFLICT: "草稿已被其他操作更新，请刷新后重试。",
  PUBLISH_GATE_FAILED: "发布门禁未通过，请先完成真实运行和检查。",
  IDEMPOTENCY_CONFLICT: "请求已被重复提交且内容不一致，请刷新后重试。",
  PRECONDITION_FAILED: "草稿已发生变化，请刷新后重试。",
  NOT_FOUND: "请求的知识资产不存在，可能已被移除。",
  INVALID_ARGUMENT: "提交的信息不完整或格式不正确，请检查后重试。",
};

function errorMessage(error: unknown): string {
  if (error instanceof OAuthFlowPollError) {
    if (error.code === "OAUTH_POPUP_BLOCKED") return "浏览器阻止了授权窗口，请允许弹窗后重试。";
    if (error.code === "OAUTH_CANCELLED") return "授权窗口已关闭，连接尚未创建。";
    if (error.code === "OAUTH_PROVIDER_ERROR") return error.message;
    if (error.code === "OAUTH_TIMEOUT") return "授权已超时，请重新发起 OAuth。";
  }
  if (error instanceof KnowledgeApiError) {
    return ERROR_LABELS[error.code] || error.message;
  }
  return error instanceof Error ? error.message : "操作失败，请重试。";
}

function formatServerTimestamp(value?: string): string {
  if (!value) return "时间由 BFF 返回";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间不可用"
    : date.toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" });
}

function formatElapsed(startedAt?: string, now = Date.now()): string {
  if (!startedAt) return "0s";
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function readableConnectorCategory(value?: string): string {
  const normalized = (value || "").toLowerCase();
  if (["db", "database", "databases"].includes(normalized)) return "数据库";
  if (["office", "collaboration", "document", "docs"].includes(normalized)) return "办公协作";
  if (["file", "files", "spreadsheet"].includes(normalized)) return "文件";
  if (["api", "http", "webhook", "adapter"].includes(normalized)) return "API / MCP";
  if (["cloud", "storage", "object_storage"].includes(normalized)) return "对象存储";
  if (normalized === "custom") return "自定义";
  return value || "其它";
}

function connectorSearchText(connector: ConnectorDefinition): string {
  return [
    connector.connector_key,
    connector.display_name,
    connector.category,
    connector.status,
    ...connector.capabilities,
    ...schemaProperties(connector.config_schema).map(([name, schema]) => `${name} ${String(schema.title || "")}`),
    ...schemaProperties(connector.auth_schema).map(([name, schema]) => `${name} ${String(schema.title || "")}`),
  ].filter(Boolean).join(" ").toLowerCase();
}

function connectorSchemaSummary(connector: ConnectorDefinition): string {
  const configFields = schemaProperties(connector.config_schema).map(([, schema]) => String(schema.title || ""));
  const authFields = schemaProperties(connector.auth_schema).map(([, schema]) => String(schema.title || ""));
  const fields = [...configFields, ...authFields].filter(Boolean);
  if (!fields.length) return "无需额外配置";
  return fields.slice(0, 4).join(" / ");
}

interface SkillFilePreview {
  path: string;
  kind: "markdown" | "script" | "test" | "file";
  content?: string;
}

const MISSING_SKILL_SOURCE = "当前 Revision 尚未返回文件清单/源文件内容";

function skillFileKind(path: string): SkillFilePreview["kind"] {
  return path.endsWith("SKILL.md")
    ? "markdown"
    : path.includes("/tests/") || path.includes("tests/") || path.includes("test_")
      ? "test"
      : path.includes("/scripts/") || path.includes("scripts/") || path.endsWith(".py") || path.endsWith(".sh")
        ? "script"
        : "file";
}

function manifestStringList(manifest: JsonObject | undefined, keys: string[]): string[] {
  if (!manifest) return [];
  for (const key of keys) {
    const value = manifest[key];
    if (Array.isArray(value)) return value.map(String).filter(Boolean);
  }
  return [];
}

function manifestFileFromRecord(value: JsonValue): SkillFilePreview | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const pathValue = value.path ?? value.name ?? value.filename;
  if (typeof pathValue !== "string" || !pathValue.trim()) return null;
  const contentValue = value.content ?? value.text ?? value.source;
  return {
    path: pathValue,
    kind: skillFileKind(pathValue),
    ...(typeof contentValue === "string" && contentValue.trim() ? { content: contentValue } : {}),
  };
}

function collectBundlePaths(manifest: JsonObject | undefined): SkillFilePreview[] {
  const zip = manifest?.zip;
  if (!zip || typeof zip !== "object" || Array.isArray(zip)) return [];
  return manifestStringList(zip, ["paths", "file_paths"])
    .map((path) => ({ path, kind: skillFileKind(path) }));
}

function collectManifestFiles(value: JsonValue | undefined): SkillFilePreview[] {
  if (Array.isArray(value)) {
    return value.flatMap((entry) => {
      if (typeof entry === "string" && entry.trim()) {
        return [{ path: entry, kind: skillFileKind(entry) }];
      }
      const file = manifestFileFromRecord(entry);
      return file ? [file] : [];
    });
  }
  if (!value || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([pathValue, fileValue]) => {
    if (!pathValue.includes("/") && !pathValue.includes(".") && pathValue !== "SKILL.md") return [];
    if (typeof fileValue === "string") {
      return [{ path: pathValue, kind: skillFileKind(pathValue), content: fileValue }];
    }
    const file = manifestFileFromRecord({ path: pathValue, ...(fileValue && typeof fileValue === "object" && !Array.isArray(fileValue) ? fileValue : {}) });
    return file ? [file] : [];
  });
}

function previewSkillFiles(revision: Revision | null): SkillFilePreview[] {
  const manifest = revision?.manifest;
  const files: SkillFilePreview[] = [
    ...manifestStringList(manifest, ["paths", "file_paths"]).map((path) => ({ path, kind: skillFileKind(path) })),
    ...collectBundlePaths(manifest),
    ...collectManifestFiles(manifest?.files),
    ...collectManifestFiles(manifest?.source_files),
    ...collectManifestFiles(manifest?.bundle_files),
  ];
  const byPath = new Map<string, SkillFilePreview>();
  for (const file of files) {
    const existing = byPath.get(file.path);
    byPath.set(file.path, existing?.content && !file.content ? existing : file);
  }
  return [...byPath.values()];
}

function manifestSkillMarkdown(revision: Revision | null): string | null {
  const manifest = revision?.manifest;
  const value = manifest?.skill_md;
  if (typeof value === "string" && value.trim()) return value;
  const skillFile = previewSkillFiles(revision).find(
    (file) => file.path.split("/").at(-1) === "SKILL.md" && file.content,
  );
  return skillFile?.content || null;
}

function manifestBundleRoot(revision: Revision | null): string | null {
  const manifest = revision?.manifest;
  if (typeof manifest?.root === "string" && manifest.root.trim()) return manifest.root;
  const zip = manifest?.zip;
  if (!zip || typeof zip !== "object" || Array.isArray(zip)) return null;
  return typeof zip.root === "string" && zip.root.trim() ? zip.root : null;
}

function routeFromLocation(): WorkspaceRoute {
  const query = new URLSearchParams(window.location.search);
  const requestedFile = query.get("file");
  const file: WorkspaceFile =
    requestedFile === null || requestedFile === "welcome" || requestedFile === "skill_new"
      ? "skill_new"
      : requestedFile === "connection"
        ? "connection"
        : requestedFile === "resource"
          ? "resource"
        : requestedFile === "draft"
            ? "draft"
            : requestedFile === "published"
              ? "published"
        : requestedFile.startsWith("pub_")
          ? "published"
          : requestedFile.startsWith("draft_")
            ? "draft"
            : "skill_new";
  return {
    file,
    draftId: query.get("draftId") || "",
    connectionId: query.get("connectionId") || "",
    resourceId: query.get("resourceId") || "",
    modal: query.get("modal") || "",
  };
}

function setRoute(file: WorkspaceFile, draftId = "", connectionId = "", resourceId = "") {
  const query = new URLSearchParams();
  query.set("view", "knowledge-workspace");
  if (file !== "skill_new") query.set("file", file);
  if (draftId) query.set("draftId", draftId);
  if (connectionId) query.set("connectionId", connectionId);
  if (resourceId) query.set("resourceId", resourceId);
  window.history.pushState({}, "", `${window.location.pathname}?${query}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function idempotentLabel(status: ConnectionProfile["status"]): string {
  return STATUS_LABELS[status] || status;
}

function parseJsonObject(value: JsonValue | undefined, label: string): JsonObject {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label}不能为空`);
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(`${label}必须是 JSON 对象`);
  return parsed as JsonObject;
}

function parseStringList(value: JsonValue | undefined): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value !== "string") return [];
  return value.split(/[\n,\s]+/u).map((item) => item.trim()).filter(Boolean);
}

export async function uploadSkillInput(
  file: File,
  onProgress: (percent: number) => void,
): Promise<UploadResult> {
  const result = await knowledgeApi.uploadFile(file, "skill_input", onProgress);
  return result.data;
}

export function KnowledgeWorkspacePage() {
  const [route, setRouteState] = useState(routeFromLocation);
  const [connections, setConnections] = useState<ConnectionProfile[]>(
    () => readQuery<ConnectionProfile[]>("connections") || [],
  );
  const [resources, setResources] = useState<WorkspaceResource[]>(
    () => readQuery<WorkspaceResource[]>("resources") || [],
  );
  const [connectors, setConnectors] = useState<ConnectorDefinition[]>(
    () => readQuery<ConnectorDefinition[]>("connector-definitions") || [],
  );
  const [drafts, setDrafts] = useState<Draft[]>(
    () => readQuery<Draft[]>("drafts") || [],
  );
  const [draft, setDraft] = useState<Draft | null>(() => {
    const initialRoute = routeFromLocation();
    return initialRoute.draftId
      ? readQuery<Draft>(`draft:${initialRoute.draftId}`) || null
      : null;
  });
  const [etag, setEtag] = useState("");
  const [draftLoadAttempt, setDraftLoadAttempt] = useState(0);
  const [draftResourceError, setDraftResourceError] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [, setArtifact] = useState<Artifact | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [publication, setPublication] = useState<Publication | null>(null);
  const [selectedConnectionIds, setSelectedConnectionIds] = useState<string[]>([]);
  const [selectedResourceIds, setSelectedResourceIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showConnectionForm, setShowConnectionForm] = useState(false);
  const [showDataToolDrawer, setShowDataToolDrawer] = useState(false);
  const [connectionFormScope, setConnectionFormScope] = useState<"personal" | "team">("personal");
  const [showVersions, setShowVersions] = useState(false);
  const [showPublish, setShowPublish] = useState(false);
  const [welcomeGoal, setWelcomeGoal] = useState("");
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<TemplateKey>("generic");
  const [creatorResetKey, setCreatorResetKey] = useState(0);
  const [connectionJob, setConnectionJob] = useState<{
    kind: "validate" | "discover";
    status: JobResult["status"];
  } | null>(null);
  const [assistantState, dispatchAssistant] = useReducer(
    assistantReducer,
    initialAssistantState,
  );
  const [activeInvocation, setActiveInvocation] = useState<Invocation | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const pendingCreatedDraftRef = useRef<{ draft: Draft; etag: string } | null>(null);
  const contextReturnRouteRef = useRef<WorkspaceRoute | null>(null);
  const lastCursorRef = useRef(new Map<string, string>());
  const terminalInvocationRef = useRef(false);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [localLoginName, setLocalLoginName] = useState("");
  const popstate = useCallback(() => setRouteState(routeFromLocation()), []);

  useLayoutEffect(() => {
    const query = new URLSearchParams(window.location.search);
    if (query.get("file") !== "welcome") return;
    query.delete("file");
    window.history.replaceState({}, "", `${window.location.pathname}?${query}`);
  }, [route]);

  useEffect(() => {
    void resolveIdentity()
      .then((identity) => {
        if (identity.local && identity.status === "unauthenticated") {
          setLocalUser("tester");
          setAuthStatus("authenticated");
          return;
        }
        setAuthStatus(identity.status);
      })
      .catch(() => setAuthStatus("unauthenticated"));
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated") return;
    window.addEventListener("popstate", popstate);
    return () => window.removeEventListener("popstate", popstate);
  }, [authStatus, popstate]);

  const reloadDirectory = useCallback(async (signal?: AbortSignal) => {
    const [connectionResult, connectorResult, draftResult, resourceResult] = await Promise.all([
      knowledgeApi.listConnections(signal),
      knowledgeApi.listConnectorDefinitions(signal),
      knowledgeApi.listDrafts(signal),
      knowledgeApi.listResources(signal),
    ]);
    setConnections(writeQuery("connections", connectionResult.data));
    setConnectors(writeQuery("connector-definitions", connectorResult.data));
    setDrafts(writeQuery("drafts", draftResult.data));
    setResources(writeQuery("resources", resourceResult.data));
    connectionResult.data.forEach((connection) => {
      writeQuery(`connection:${connection.connection_id}`, connection);
    });
    draftResult.data.forEach((item) => {
      writeQuery(`draft:${item.draft_id}`, item);
    });
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated") return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void reloadDirectory(controller.signal)
      .catch((cause) => {
        if (!controller.signal.aborted) setError(errorMessage(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [authStatus, reloadDirectory]);

  useEffect(() => {
    if (authStatus !== "authenticated") return;
    if (route.file !== "connection" || !route.connectionId) return;
    const controller = new AbortController();
    setBusy("load-connection");
    void knowledgeApi.getConnection(route.connectionId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setConnections((current) => [
          ...current.filter((item) => item.connection_id !== result.value.data.connection_id),
          result.value.data,
        ]);
        writeQuery(`connection:${result.value.data.connection_id}`, result.value.data);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(errorMessage(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy("");
      });
    return () => controller.abort();
  }, [authStatus, route.connectionId, route.file]);

  useEffect(() => {
    if (authStatus !== "authenticated") return;
    if (!route.draftId) {
      setDraft(null);
      setRevisions([]);
      setArtifact(null);
      setArtifacts([]);
      setPublication(null);
      setDraftResourceError(null);
      return;
    }
    const controller = new AbortController();
    setBusy("load-draft");
    setDraftResourceError(null);
    const cachedDraft = readQuery<Draft>(`draft:${route.draftId}`);
    if (cachedDraft) setDraft(cachedDraft);
    const cachedRevisions = readQuery<Revision[]>(`revisions:${route.draftId}`);
    if (cachedRevisions) setRevisions(cachedRevisions);
    void knowledgeApi.getDraft(route.draftId, controller.signal)
      .then(async (result) => {
        if (controller.signal.aborted) return;
        setDraft(result.value.data);
        writeQuery(`draft:${route.draftId}`, result.value.data);
        setEtag(result.etag);
        setSelectedConnectionIds(result.value.data.connection_ids);
        setSelectedResourceIds(result.value.data.resource_ids);
        const [revisionResult, conversationResult, publicationResult] = await Promise.all([
          knowledgeApi.listRevisions(route.draftId, controller.signal),
          knowledgeApi.getConversation(route.draftId, controller.signal),
          knowledgeApi.listPublications(controller.signal),
        ]);
        setRevisions(revisionResult.data);
        writeQuery(`revisions:${route.draftId}`, revisionResult.data);
        const currentRevisionId = result.value.data.current_revision_id
          || revisionResult.data.reduce<Revision | null>(
            (current, revision) =>
              !current || revision.number > current.number ? revision : current,
            null,
          )?.revision_id;
        const restoredPublication = [...publicationResult.data].reverse().find(
          (publication) =>
            publication.status === "published"
            && publication.revision_id === currentRevisionId,
        );
        setPublication(restoredPublication || null);
        dispatchAssistant({
          type: "history.restored",
          entries: conversationResult.data,
        });
        const historicalArtifactIds = [...new Set(
          conversationResult.data.flatMap((entry) =>
            entry.events.flatMap((event) =>
              event.type === "artifact.created" ? [event.data.artifact_id] : []),
          ),
        )];
        if (historicalArtifactIds.length) {
          const restoredResults = await Promise.allSettled(
            historicalArtifactIds.map((id) =>
              knowledgeApi.getArtifact(id, controller.signal).then((value) => value.value.data),
            ),
          );
          const restoredArtifacts = restoredResults.flatMap((result) =>
            result.status === "fulfilled" ? [result.value] : []);
          if (!controller.signal.aborted) {
            setArtifacts(restoredArtifacts);
            setArtifact(restoredArtifacts.at(-1) || null);
          }
        }
        lastCursorRef.current = new Map(
          conversationResult.data.flatMap((entry) => {
            const cursor = entry.events.at(-1)?.cursor;
            return cursor ? [[entry.invocation.invocation_id, cursor] as const] : [];
          }),
        );
        const active = [...conversationResult.data].reverse().find(
          (entry) =>
            entry.invocation.status === "queued"
            || entry.invocation.status === "running",
        );
        setActiveInvocation((current) => {
          if (
            current
            && active
            && current.invocation_id === active.invocation.invocation_id
          ) {
            return current;
          }
          return active?.invocation || null;
        });
      })
      .catch((cause) => {
        if (!controller.signal.aborted) {
          setDraftResourceError({
            code: cause instanceof KnowledgeApiError ? cause.code : "UNKNOWN",
            message: errorMessage(cause),
          });
          setError(errorMessage(cause));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy("");
      });
    return () => controller.abort();
  }, [authStatus, draftLoadAttempt, route.draftId]);

  const availableConnections = useMemo(
    () => connections.filter((connection) => connection.status !== "revoked"),
    [connections],
  );
  const personalConnections = useMemo(
    () => availableConnections.filter((connection) => connection.scope === "personal"),
    [availableConnections],
  );
  const teamConnections = useMemo(
    () => availableConnections.filter((connection) => connection.scope === "team"),
    [availableConnections],
  );

  const openDraft = useCallback((nextDraft: Draft) => {
    setRoute("draft", nextDraft.draft_id);
  }, []);

  const openConnectionSelector = useCallback((scope: "personal" | "team" = "personal") => {
    setConnectionFormScope(scope);
    setShowConnectionForm(true);
  }, []);

  const openWorkspace = useCallback(() => {
    setRoute("skill_new");
  }, []);

  const startNewSkill = useCallback(() => {
    setWelcomeGoal("");
    setSelectedTemplateKey("generic");
    setSelectedConnectionIds([]);
    setSelectedResourceIds([]);
    setError("");
    setShowDataToolDrawer(false);
    contextReturnRouteRef.current = null;
    pendingCreatedDraftRef.current = null;
    setCreatorResetKey((current) => current + 1);
    setRoute("skill_new");
  }, []);

  const returnFromContextDetail = useCallback(() => {
    const previous = contextReturnRouteRef.current;
    contextReturnRouteRef.current = null;
    if (previous?.file === "draft" || previous?.file === "published") {
      setRoute(previous.file, previous.draftId);
      setShowDataToolDrawer(true);
      return;
    }
    openWorkspace();
    setShowDataToolDrawer(true);
  }, [openWorkspace]);

  useEffect(() => {
    if (authStatus !== "authenticated") return;
    if (route.draftId || (route.file !== "draft" && route.file !== "published")) return;
    const target = drafts[0];
    if (target) setRoute(route.file, target.draft_id);
  }, [authStatus, drafts, route.draftId, route.file]);

  const createAndGenerate = useCallback(async (
    goal: string,
    templateKey: TemplateKey,
    templateConfig: JsonObject,
    connectionIds: string[],
    resourceIds: string[],
    trialTask: string,
    uploadIds: string[],
  ) => {
    setBusy("generate");
    setError("");
    try {
      const created = pendingCreatedDraftRef.current
        ? await knowledgeApi.updateDraft(
          pendingCreatedDraftRef.current.draft.draft_id,
          {
            goal,
            template_key: templateKey,
            template_config: templateConfig,
            connection_ids: connectionIds,
            resource_ids: resourceIds,
            trial_task: trialTask.trim(),
            upload_ids: uploadIds,
          },
          pendingCreatedDraftRef.current.etag,
        )
        : await knowledgeApi.createDraft({
          goal,
          template_key: templateKey,
          template_config: templateConfig,
          connection_ids: connectionIds,
          ...(resourceIds.length ? { resource_ids: resourceIds } : {}),
          ...(trialTask.trim() ? { trial_task: trialTask.trim() } : {}),
          ...(uploadIds.length ? { upload_ids: uploadIds } : {}),
        });
      pendingCreatedDraftRef.current = {
        draft: created.value.data,
        etag: created.etag,
      };
      setDraft(created.value.data);
      writeQuery(`draft:${created.value.data.draft_id}`, created.value.data);
      setEtag(created.etag);
      setSelectedConnectionIds(connectionIds);
      setSelectedResourceIds(resourceIds);
      setDrafts((current) => [
        ...current.filter((item) => item.draft_id !== created.value.data.draft_id),
        created.value.data,
      ]);
      const invocation = await knowledgeApi.generateDraft(
        created.value.data.draft_id,
        created.etag,
        goal,
      );
      setActiveInvocation(invocation.data);
      dispatchAssistant({ type: "invocation.started", invocation: invocation.data });
      pendingCreatedDraftRef.current = null;
      setRoute("draft", created.value.data.draft_id);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, []);

  const applyEvent = useCallback((event: KnowledgeInvocationEvent) => {
    dispatchAssistant({ type: "event.received", event });
    lastCursorRef.current.set(event.invocation_id, event.cursor);
    if (event.type === "artifact.created") {
      void knowledgeApi.getArtifact(event.data.artifact_id)
        .then((result) => {
          setArtifact(result.value.data);
          setArtifacts((current) => [
            ...current.filter((item) => item.artifact_id !== result.value.data.artifact_id),
            result.value.data,
          ]);
          writeQuery(`artifact:${event.data.artifact_id}`, result.value.data);
        })
        .catch((cause) => setError(errorMessage(cause)));
    } else if (event.type === "revision.created" && draft) {
      setPublication(null);
      void knowledgeApi.listRevisions(draft.draft_id)
        .then((result) => {
          setRevisions(result.data);
          writeQuery(`revisions:${draft.draft_id}`, result.data);
        })
        .catch((cause) => setError(errorMessage(cause)));
    }
    if (
      event.type === "run.completed"
      || event.type === "run.failed"
      || event.type === "run.cancelled"
    ) {
      terminalInvocationRef.current = true;
      dispatchAssistant({
        type: "connection.changed",
        invocationId: event.invocation_id,
        state: "idle",
      });
    }
  }, [draft]);

  const stream = useCallback(async (invocation = activeInvocation) => {
    if (!invocation) return;
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    terminalInvocationRef.current = false;
    dispatchAssistant({
      type: "connection.changed",
      invocationId: invocation.invocation_id,
      state: "connected",
    });
    try {
      for await (const event of knowledgeApi.streamInvocationEvents(invocation, {
        signal: controller.signal,
        lastEventId: lastCursorRef.current.get(invocation.invocation_id),
        onUnknown: (unknown) => dispatchAssistant({
          type: "unknown.received",
          invocationId: invocation.invocation_id,
          event: unknown,
        }),
      })) {
        applyEvent(event);
      }
      if (!controller.signal.aborted && !terminalInvocationRef.current) {
        dispatchAssistant({
          type: "connection.changed",
          invocationId: invocation.invocation_id,
          state: "disconnected",
        });
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        dispatchAssistant({
          type: "connection.changed",
          invocationId: invocation.invocation_id,
          state: "disconnected",
        });
        setError(errorMessage(cause));
      }
    }
  }, [activeInvocation, applyEvent]);

  useEffect(() => {
    if (activeInvocation) {
      void stream(activeInvocation);
    }
    return () => streamAbortRef.current?.abort();
    // A new invocation starts one subscription. Reconnect is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeInvocation]);

  const cancel = useCallback(async () => {
    if (!activeInvocation) return;
    setBusy("cancel");
    try {
      const result = await knowledgeApi.cancelInvocation(activeInvocation.invocation_id);
      streamAbortRef.current?.abort();
      dispatchAssistant({
        type: "invocation.cancelled",
        invocationId: activeInvocation.invocation_id,
        finishedAt: result.data.finished_at || new Date().toISOString(),
      });
      setActiveInvocation(null);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [activeInvocation]);

  const sendMessage = useCallback(async (message: string, intent: "update" | "run") => {
    if (!draft || !message.trim()) return;
    const optimisticId = `pending-${globalThis.crypto?.randomUUID?.() || Date.now()}`;
    const optimistic: Invocation = {
      invocation_id: optimisticId,
      kind: intent,
      status: "queued",
      message: message.trim(),
      event_url: "",
      created_at: new Date().toISOString(),
    };
    dispatchAssistant({ type: "invocation.started", invocation: optimistic });
    setBusy("message");
    setError("");
    try {
      const result = await knowledgeApi.sendDraftMessage(
        draft.draft_id,
        message.trim(),
        intent,
        etag,
      );
      setActiveInvocation(result.data);
      dispatchAssistant({
        type: "invocation.confirmed",
        optimisticId,
        invocation: result.data,
      });
    } catch (cause) {
      dispatchAssistant({
        type: "invocation.rejected",
        invocationId: optimisticId,
        error: {
          code: cause instanceof KnowledgeApiError ? cause.code : "SUBMIT_FAILED",
          message: errorMessage(cause),
          retryable: cause instanceof KnowledgeApiError ? cause.retryable : true,
        },
      });
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [draft, etag]);

  const runSkill = useCallback(async (message: string) => {
    if (!draft || !message.trim()) return;
    const revision = draft.current_revision_id
      ? revisions.find((item) => item.revision_id === draft.current_revision_id)
      : revisions.reduce<Revision | null>(
        (current, item) => !current || item.number > current.number ? item : current,
        null,
      );
    if (!revision) {
      await sendMessage(message, "run");
      return;
    }
    const optimisticId = `pending-${globalThis.crypto?.randomUUID?.() || Date.now()}`;
    const optimistic: Invocation = {
      invocation_id: optimisticId,
      kind: "run",
      status: "queued",
      message: message.trim(),
      event_url: "",
      created_at: new Date().toISOString(),
    };
    dispatchAssistant({ type: "invocation.started", invocation: optimistic });
    setBusy("message");
    setError("");
    try {
      const result = await knowledgeApi.runRevision(
        revision.revision_id,
        draft.connection_ids,
        message.trim(),
        undefined,
        draft.resource_ids,
      );
      setActiveInvocation(result.data);
      dispatchAssistant({
        type: "invocation.confirmed",
        optimisticId,
        invocation: result.data,
      });
    } catch (cause) {
      dispatchAssistant({
        type: "invocation.rejected",
        invocationId: optimisticId,
        error: {
          code: cause instanceof KnowledgeApiError ? cause.code : "SUBMIT_FAILED",
          message: errorMessage(cause),
          retryable: cause instanceof KnowledgeApiError ? cause.retryable : true,
        },
      });
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [draft, revisions, sendMessage]);

  const retryInvocation = useCallback(async (turn?: ConversationTurnModel) => {
    if (!draft) return;
    const source = turn?.invocation || activeInvocation;
    if (!source) return;
    setBusy("retry");
    setError("");
    try {
      const result = source.kind === "generate"
        ? await knowledgeApi.generateDraft(draft.draft_id, etag, source.message)
        : await knowledgeApi.sendDraftMessage(
          draft.draft_id,
          source.message,
          source.kind === "update" ? "update" : "run",
          etag,
      );
      dispatchAssistant({
        type: "invocation.started",
        invocation: result.data,
        retryOf: source.invocation_id,
      });
      setActiveInvocation(result.data);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [activeInvocation, draft, etag]);

  const publish = useCallback(async (target: "personal" | "team") => {
    const revision = draft?.current_revision_id
      ? revisions.find((item) => item.revision_id === draft.current_revision_id)
      : revisions.reduce<Revision | null>(
        (current, item) => !current || item.number > current.number ? item : current,
        null,
      );
    if (!revision) return;
    setBusy("publish");
    try {
      const result = await knowledgeApi.publishRevision(revision.revision_id, target);
      setPublication(result.data);
      setShowPublish(false);
      setRoute("published", draft?.draft_id);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [draft?.current_revision_id, draft?.draft_id, revisions]);

  const updateDraftContext = useCallback(async (
    connectionIds: string[],
    resourceIds: string[],
  ) => {
    setSelectedConnectionIds(connectionIds);
    setSelectedResourceIds(resourceIds);
    if (!draft) return;
    setBusy("update-context");
    setError("");
    try {
      const result = await knowledgeApi.updateDraft(
        draft.draft_id,
        { connection_ids: connectionIds, resource_ids: resourceIds },
        etag,
      );
      setDraft(result.value.data);
      setEtag(result.etag);
      writeQuery(`draft:${draft.draft_id}`, result.value.data);
    } catch (cause) {
      setSelectedConnectionIds(draft.connection_ids);
      setSelectedResourceIds(draft.resource_ids);
      setError(errorMessage(cause));
      throw cause;
    } finally {
      setBusy("");
    }
  }, [draft, etag]);

  // Keep the directory snapshot as the underlying document when a detail
  // request fails. This lets the UI render a real, actionable state overlay
  // instead of collapsing to a URL-only error page.
  const selectedDraft = draft || drafts.find((item) => item.draft_id === route.draftId) || null;
  const selectedConnection = connections.find(
    (item) => item.connection_id === route.connectionId
      || selectedConnectionIds.includes(item.connection_id),
  ) || null;
  const selectedResource = resources.find(
    (item) => item.resource_id === route.resourceId
      || selectedResourceIds.includes(item.resource_id),
  ) || null;
  const selectedRevision = selectedDraft?.current_revision_id
    ? revisions.find((item) => item.revision_id === selectedDraft.current_revision_id) || null
    : revisions.reduce<Revision | null>(
      (current, item) => !current || item.number > current.number ? item : current,
      null,
    );
  const routeModal = route.modal;
  const openRouteModal = useCallback((kind: string) => {
    const query = new URLSearchParams(window.location.search);
    query.set("modal", kind);
    window.history.pushState({}, "", `${window.location.pathname}?${query}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);
  const closeRouteModal = useCallback(() => {
    const query = new URLSearchParams(window.location.search);
    query.delete("modal");
    window.history.pushState({}, "", `${window.location.pathname}?${query}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  if (authStatus === null) {
    return <div className="kw-auth-state" role="status"><Loader2 className="kw-spin" size={18} /> 正在确认登录状态…</div>;
  }
  if (authStatus !== "authenticated") {
    return (
      <div className="kw-auth-state">
        <h1>请先登录知识资产工作台</h1>
        <p>工作台中的连接、草稿和 Artifact 由 Studio 身份权限保护。</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!USERNAME_RE.test(localLoginName)) return;
            setLocalUser(localLoginName);
            setAuthStatus("authenticated");
          }}
        >
          <input
            aria-label="用户名"
            value={localLoginName}
            onChange={(event) => setLocalLoginName(event.target.value)}
            placeholder="用户名（字母 + 数字，最多 16 位）"
            maxLength={16}
          />
          <button
            type="submit"
            className="kw-primary-small"
            disabled={!USERNAME_RE.test(localLoginName)}
          >
            使用本地用户名进入
          </button>
        </form>
      </div>
    );
  }
  const handleAssistantSend = route.file === "published"
    ? async (message: string, intent: "update" | "run") => {
      if (intent === "run") {
        await runSkill(message);
        return;
      }
      await sendMessage(message, intent);
    }
    : sendMessage;

  return (
    <div className={`kw-shell${selectedDraft ? " has-draft" : ""}${route.file === "draft" || route.file === "published" ? " is-workshop-route" : ""}${route.file === "skill_new" ? " is-create-route" : ""}`}>
      <header className="kw-studio-nav">
        <button className="kw-studio-brand" type="button" onClick={openWorkspace}>
          <span className="kw-studio-mark"><Database size={15} /></span>
          <span>Knowledge Asset</span>
        </button>
        <nav className="kw-studio-links" aria-label="Studio">
          <button className="is-active" type="button" onClick={openWorkspace}>工作台</button>
          <button type="button" onClick={startNewSkill}>创建</button>
        </nav>
        <div className="kw-studio-search">
          <Search size={15} />
          <input aria-label="全局搜索资源" placeholder="全局搜索资源…" />
        </div>
        <div className="kw-studio-actions">
          <button type="button" aria-label="通知"><Bell size={16} /></button>
          <button type="button" aria-label="用户"><User size={16} /></button>
        </div>
      </header>
      <div className="kw-workspace-frame">
        <aside className="kw-sidebar">
          <button className="kw-new-resource" type="button" aria-label="新建 Skill" onClick={startNewSkill}>
            <CirclePlus size={16} /> 新建 Skill
          </button>
          <div className="kw-tree-label kw-tree-label-row">
            <span>个人工作区</span>
            <button type="button" aria-label="添加个人连接" onClick={() => openConnectionSelector("personal")}><CirclePlus size={13} /></button>
          </div>
          <button
            className={`kw-tree-item${route.file === "skill_new" ? " is-selected" : ""}`}
            type="button"
            onClick={openWorkspace}
          >
            <MessageSquare size={15} /> 工作台
          </button>
          <div className="kw-tree-label">我的连接</div>
          {loading && !availableConnections.length ? <div className="kw-tree-muted">正在读取连接…</div> : null}
          {personalConnections.map((connection) => (
            <button
              className={`kw-tree-item${selectedConnectionIds.includes(connection.connection_id) ? " is-selected" : ""}`}
              type="button"
              key={connection.connection_id}
              onClick={() => setRoute("connection", "", connection.connection_id)}
            >
              <Settings2 size={15} />
              <span>{connection.display_name}</span>
              <span className={`kw-status-dot is-${connection.status}`} title={idempotentLabel(connection.status)} />
            </button>
          ))}
          <button className="kw-tree-item kw-tree-add" type="button" onClick={() => openConnectionSelector("personal")}>
            <CirclePlus size={15} /> 添加连接
          </button>
          <div className="kw-tree-label">我的资源</div>
          {resources.length ? resources.map((resource) => (
            <button
              className={`kw-tree-item${selectedResourceIds.includes(resource.resource_id) ? " is-selected" : ""}`}
              type="button"
              key={resource.resource_id}
              title={`${resource.display_name} · ${resource.kind} · ${resource.status}`}
              onClick={() => setRoute("resource", "", "", resource.resource_id)}
            >
              <FileText size={15} />
              <span>{resource.display_name}</span>
              <span className={`kw-status-dot is-${resource.status}`} title={`${resource.kind} · ${resource.status}`} />
            </button>
          )) : <div className="kw-tree-muted">暂无专用资源。</div>}
          <div className="kw-tree-label">我的 Skill</div>
          {drafts.map((item) => (
            <button
              className={`kw-tree-item${item.draft_id === route.draftId ? " is-selected" : ""}`}
              type="button"
              key={item.draft_id}
              onClick={() => openDraft(item)}
            >
              <ToyBrick size={15} />
              <span className="kw-truncate">{(item as Draft & { display_name?: string }).display_name || item.goal}</span>
            </button>
          ))}
          <div className="kw-tree-label kw-tree-label-row">
            <span>团队工作区</span>
            <button type="button" aria-label="添加团队连接" onClick={() => openConnectionSelector("team")}><CirclePlus size={13} /></button>
          </div>
          {teamConnections.length ? teamConnections.map((connection) => (
            <button
              className={`kw-tree-item${selectedConnectionIds.includes(connection.connection_id) ? " is-selected" : ""}`}
              type="button"
              key={connection.connection_id}
              onClick={() => setRoute("connection", "", connection.connection_id)}
            >
              <Settings2 size={15} />
              <span>{connection.display_name}</span>
              <span className={`kw-status-dot is-${connection.status}`} title={idempotentLabel(connection.status)} />
            </button>
          )) : <div className="kw-tree-muted">团队目录由当前 BFF 权限返回。</div>}
          <div className="kw-sidebar-footer">通过 Studio BFF 连接</div>
        </aside>

        <main className="kw-main">
        {route.file === "connection" ? (
          <header className="kw-topbar">
            <div className="kw-breadcrumb">
              <button type="button" onClick={openWorkspace}>知识资产</button>
              {selectedConnection ? <><ChevronRight size={14} /><span>{selectedConnection.display_name}</span></> : null}
            </div>
          </header>
        ) : route.file === "resource" ? (
          <header className="kw-topbar">
            <div className="kw-breadcrumb">
              <button type="button" onClick={openWorkspace}>知识资产</button>
              {selectedResource ? <><ChevronRight size={14} /><span>{selectedResource.display_name}</span></> : null}
            </div>
          </header>
        ) : null}
        {error && !draftResourceError ? (
          <div className="kw-error" role="alert">
            <AlertCircle size={16} /> <span>{error}</span>
            <button type="button" onClick={() => setError("")} aria-label="关闭错误"><X size={14} /></button>
          </div>
        ) : null}
        {route.file === "skill_new" ? (
          <SkillCreateLanding
            key={creatorResetKey}
            goal={welcomeGoal}
            setGoal={setWelcomeGoal}
            connections={availableConnections}
            resources={resources}
            selectedConnectionIds={selectedConnectionIds}
            selectedResourceIds={selectedResourceIds}
            templateKey={selectedTemplateKey}
            setTemplateKey={setSelectedTemplateKey}
            onOpenDataTools={() => setShowDataToolDrawer(true)}
            onRemoveConnection={(id) => setSelectedConnectionIds((current) => current.filter((item) => item !== id))}
            onRemoveResource={(id) => setSelectedResourceIds((current) => current.filter((item) => item !== id))}
            onCreate={() => {
              const definition = templateDefinition(selectedTemplateKey);
              void createAndGenerate(
                welcomeGoal.trim(),
                selectedTemplateKey,
                definition?.config || { mode: "auto" },
                selectedConnectionIds,
                selectedResourceIds,
                "",
                [],
              );
            }}
            busy={busy === "generate"}
            error={error}
          />
        ) : route.file === "connection" ? (
          <ConnectionDetailView
            connection={selectedConnection}
            connector={connectors.find((item) => item.connector_key === selectedConnection?.connector_key)}
            onBack={contextReturnRouteRef.current ? returnFromContextDetail : undefined}
            onValidate={async (id) => {
              setBusy("validate");
              try {
                const started = await knowledgeApi.validateConnection(id);
                setConnectionJob({ kind: "validate", status: started.data.status });
                const result = await knowledgeApi.waitForConnectionJob(started);
                setConnectionJob({ kind: "validate", status: result.data.status });
                await reloadDirectory();
              }
              catch (cause) {
                setConnectionJob({ kind: "validate", status: "failed" });
                setError(errorMessage(cause));
              }
              finally { setBusy(""); }
            }}
            onDiscover={async (id) => {
              setBusy("discover");
              try {
                const started = await knowledgeApi.discoverConnection(id);
                setConnectionJob({ kind: "discover", status: started.data.status });
                const result = await knowledgeApi.waitForConnectionJob(started);
                setConnectionJob({ kind: "discover", status: result.data.status });
                await reloadDirectory();
              }
              catch (cause) {
                setConnectionJob({ kind: "discover", status: "failed" });
                setError(errorMessage(cause));
              }
              finally { setBusy(""); }
            }}
            busy={busy === "validate" || busy === "discover"}
            job={connectionJob}
          />
        ) : route.file === "resource" ? (
          <WorkspaceResourceDetail
            resource={selectedResource}
            onBack={contextReturnRouteRef.current ? returnFromContextDetail : undefined}
            onUse={() => {
              if (!selectedResource) return;
              setSelectedResourceIds([selectedResource.resource_id]);
              openWorkspace();
            }}
          />
        ) : selectedDraft && (route.file === "draft" || route.file === "published") ? (
          <SkillWorkspaceShell
            draft={selectedDraft}
            revisions={revisions}
            artifacts={artifacts}
            connections={availableConnections}
            resources={resources}
            turns={assistantState.turns}
            busy={busy}
            published={publication?.status === "published" || selectedDraft.lifecycle === "published"}
            onOpenDataTools={() => setShowDataToolDrawer(true)}
            onUpdateContext={updateDraftContext}
            onSend={handleAssistantSend}
            onCancel={cancel}
            onReconnect={(turn) => {
              if (activeInvocation?.invocation_id === turn.invocation.invocation_id) {
                void stream(activeInvocation);
              } else {
                setActiveInvocation(turn.invocation);
              }
            }}
            onRetry={(turn) => void retryInvocation(turn)}
            onRun={runSkill}
            onShare={() => openRouteModal("share_run")}
            onPublish={() => setShowPublish(true)}
            onBindAgent={() => {
              if (publication?.status !== "published" && selectedDraft.lifecycle !== "published") {
                setError("请先发布 Skill，再添加到 Agent。");
                return;
              }
              openRouteModal("agent");
            }}
            onAdvanced={() => openRouteModal("versions")}
          />
        ) : (
          <div className="kw-empty-page">
            {draftResourceError ? (
              <div className="kw-state-card is-failed" role="alert">
                <strong>无法加载当前资源</strong>
                <span>{draftResourceError.message}</span>
                <button type="button" onClick={() => {
                  setError("");
                  setDraftLoadAttempt((current) => current + 1);
                }}>重新加载资源</button>
              </div>
            ) : "正在从 BFF 恢复草稿…"}
          </div>
        )}
        </main>

      </div>
      <DataToolDrawer
        open={showDataToolDrawer}
        connections={connections}
        resources={resources}
        selectedConnectionIds={selectedConnectionIds}
        selectedResourceIds={selectedResourceIds}
        onClose={() => setShowDataToolDrawer(false)}
        onConfirm={(connectionIds, resourceIds) => {
          void updateDraftContext(connectionIds, resourceIds)
            .then(() => setShowDataToolDrawer(false))
            .catch(() => undefined);
        }}
        onConfigureConnection={(connection) => {
          contextReturnRouteRef.current = route.file === "draft" || route.file === "published"
            ? route
            : { ...route, file: "skill_new" };
          setShowDataToolDrawer(false);
          setRoute("connection", "", connection.connection_id);
        }}
        onInspectResource={(resource) => {
          contextReturnRouteRef.current = route.file === "draft" || route.file === "published"
            ? route
            : { ...route, file: "skill_new" };
          setShowDataToolDrawer(false);
          setRoute("resource", "", "", resource.resource_id);
        }}
      />
      {showConnectionForm ? (
        <ConnectionForm
          connectors={connectors}
          initialScope={connectionFormScope}
          onClose={() => setShowConnectionForm(false)}
          onUpload={(file) => knowledgeApi.uploadFile(file, "context").then((value) => value.data)}
          onCreated={async (created) => {
            setShowConnectionForm(false);
            setSelectedConnectionIds([created.connection_id]);
            await reloadDirectory();
            setRoute("connection", "", created.connection_id);
          }}
          onResourceCreated={async (resource) => {
            setShowConnectionForm(false);
            setSelectedResourceIds([resource.resource_id]);
            await reloadDirectory();
            setRoute("resource", "", "", resource.resource_id);
          }}
        />
      ) : null}
      {showVersions ? (
        <Modal title="版本历史" onClose={() => setShowVersions(false)}>
          {revisions.length ? revisions.map((revision) => (
            <div className="kw-version-row" key={revision.revision_id}>
              <span>v{revision.number} · {templateLabel(revision.template_key)} · {revision.skill_name}</span>
              <code>{revision.sha256.slice(0, 16)}…</code>
            </div>
          )) : <p className="kw-muted">暂无已固化版本。</p>}
        </Modal>
      ) : null}
      {showPublish ? (
        <Modal title="发布 Skill" onClose={() => setShowPublish(false)}>
          <p className="kw-muted">发布会固定当前不可变 Revision，后续修改将创建新版本。</p>
          <div className="kw-publish-actions">
            <button type="button" onClick={() => void publish("personal")} disabled={busy === "publish"}>发布到个人</button>
            <button type="button" className="kw-primary-small" onClick={() => void publish("team")} disabled={busy === "publish"}>发布到团队</button>
          </div>
        </Modal>
      ) : null}
      {routeModal && routeModal !== "publish" ? (
        <WorkspaceStateModal
          kind={routeModal}
          draft={selectedDraft}
          revision={selectedRevision}
          revisions={revisions}
          connections={availableConnections}
          onClose={closeRouteModal}
        />
      ) : null}
      {routeModal === "publish" ? (
        <PublishGateModal
          draft={selectedDraft}
          revision={selectedRevision}
          connections={availableConnections}
          busy={busy === "publish"}
          onClose={closeRouteModal}
          onPublish={publish}
        />
      ) : null}
    </div>
  );
}

export function SkillNewView({
  connections,
  resources,
  selectedIds,
  selectedResourceIds,
  onSelectedIdsChange,
  templateKey,
  onTemplateKeyChange,
  onCreate,
  onUpload,
  onAddConnection,
  busy,
  initialGoal,
  onBack,
}: {
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  selectedIds: string[];
  selectedResourceIds: string[];
  onSelectedIdsChange: (ids: string[]) => void;
  templateKey: TemplateKey;
  onTemplateKeyChange: (templateKey: TemplateKey) => void;
  onCreate: (goal: string, templateKey: TemplateKey, templateConfig: JsonObject, connectionIds: string[], resourceIds: string[], trialTask: string, uploadIds: string[]) => Promise<void>;
  onUpload: (file: File, onProgress: (percent: number) => void) => Promise<UploadResult>;
  onAddConnection: () => void;
  busy: boolean;
  initialGoal?: string;
  onBack: () => void;
}) {
  const [goal, setGoal] = useState(initialGoal || "");
  const [trialTask, setTrialTask] = useState("");
  const [uploads, setUploads] = useState<UploadResult[]>([]);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [resourceIds, setResourceIds] = useState<string[]>(selectedResourceIds);
  const activeTemplate = templateDefinition(templateKey);
  useEffect(() => {
    setResourceIds(selectedResourceIds);
  }, [selectedResourceIds]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (goal.trim() && (selectedIds.length || resourceIds.length)) {
      void onCreate(
        goal,
        templateKey,
        activeTemplate?.config || {},
        selectedIds,
        resourceIds,
        trialTask,
        uploads.map((upload) => upload.upload_id),
      );
    }
  };
  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setUploadError("");
    setUploadProgress(0);
    try {
      const upload = await onUpload(file, setUploadProgress);
      setUploads((current) => [...current, upload]);
      setUploadProgress(100);
    } catch (cause) {
      setUploadError(errorMessage(cause));
    } finally {
      setUploading(false);
    }
  };
  return (
    <section className="kw-create">
      <div className="kw-create-copy">
        <div className="kw-skill-new-heading">
          <button type="button" className="kw-icon-button kw-skill-new-back" onClick={onBack} aria-label="返回工作台">
            <ArrowLeft size={18} />
          </button>
          <h1>生成第一版 Skill</h1>
        </div>
      </div>
      <form className="kw-create-form" onSubmit={submit}>
        <div className="kw-form-section">
          <div className="kw-form-section-title">
            <span>1. 选择模板</span>
            <span className="kw-muted">最终产物仍是一个 Skill</span>
          </div>
          <div className="kw-template-selector" role="radiogroup" aria-label="Skill 模板">
            {TEMPLATE_DEFINITIONS.map((item) => (
              <label
                className={`kw-template-choice${templateKey === item.key ? " is-selected" : ""}`}
                key={item.key}
              >
                <input
                  type="radio"
                  name="template_key"
                  value={item.key}
                  checked={templateKey === item.key}
                  onChange={() => onTemplateKeyChange(item.key)}
                />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
                {templateKey === item.key ? <Check size={16} /> : null}
              </label>
            ))}
          </div>
        </div>
        <label>
          <span className="kw-form-step-label">2. 谁会使用，希望解决什么问题</span>
          <textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="例如：让售后工程师排查最近的蓝牙断连并给出处置建议"
            aria-label="谁使用，解决什么问题？"
            rows={4}
            required
          />
        </label>
        <div className="kw-form-section">
          <div className="kw-form-section-title">
            <span>3. 接入数据与工具</span>
            <button type="button" className="kw-link-button" onClick={onAddConnection}><CirclePlus size={14} /> 添加连接</button>
          </div>
          {connections.length ? connections.map((connection) => (
            <label className={`kw-connection-choice${selectedIds.includes(connection.connection_id) ? " is-selected" : ""}`} key={connection.connection_id}>
              <input
                type="checkbox"
                checked={selectedIds.includes(connection.connection_id)}
                disabled={connection.status !== "ready"}
                onChange={(event) => onSelectedIdsChange(
                  event.target.checked
                    ? [...selectedIds, connection.connection_id]
                    : selectedIds.filter((id) => id !== connection.connection_id),
                )}
              />
              <span className="kw-choice-copy">
                <strong>{connection.display_name}</strong>
                <small>{connection.scope === "team" ? "团队" : "个人"} · {idempotentLabel(connection.status)}</small>
              </span>
              {connection.status === "ready" ? <Check size={16} /> : <span className="kw-disabled-label">不可用</span>}
            </label>
          )) : (
            <div className="kw-inline-empty">暂无可用连接，请先添加并验证连接。</div>
          )}
          {resources.map((resource) => (
            <label className={`kw-connection-choice${resourceIds.includes(resource.resource_id) ? " is-selected" : ""}`} key={resource.resource_id}>
              <input
                type="checkbox"
                checked={resourceIds.includes(resource.resource_id)}
                onChange={(event) => setResourceIds((current) => (
                  event.target.checked
                    ? [...current, resource.resource_id]
                    : current.filter((id) => id !== resource.resource_id)
                ))}
              />
              <span className="kw-choice-copy">
                <strong>{resource.display_name}</strong>
                <small>{resource.kind} · {resource.status} · 专用资源</small>
              </span>
              <Check size={16} />
            </label>
          ))}
        </div>
        <label>
          <span className="kw-form-step-label">4. 先试一句任务（可选）</span>
          <textarea value={trialTask} onChange={(event) => setTrialTask(event.target.value)} placeholder="生成后直接用什么输入试跑？" aria-label="可选：先试一句真实任务" rows={3} />
        </label>
        <div className="kw-form-section">
          <div className="kw-form-section-title"><span>可选：上传任务输入</span><span className="kw-muted">文件由 BFF 隔离存储</span></div>
          <label className="kw-upload-box">
            <Upload size={16} />
            <span>{uploading ? `正在上传 ${uploadProgress}%` : "选择文件并显示真实上传进度"}</span>
            <input type="file" onChange={(event) => void handleUpload(event)} disabled={uploading} />
          </label>
          {uploading ? <progress className="kw-upload-progress" max={100} value={uploadProgress}>{uploadProgress}%</progress> : null}
          {uploads.map((upload) => <div className="kw-uploaded-file" key={upload.upload_id}>{upload.filename} · sha256:{upload.sha256.slice(0, 12)}…</div>)}
          {uploadError ? <div className="kw-form-error" role="alert">{uploadError}</div> : null}
        </div>
        <button className="kw-primary" type="submit" disabled={busy || !goal.trim() || (!selectedIds.length && !resourceIds.length)}>
          {busy ? <Loader2 className="kw-spin" size={16} /> : <Play size={16} />}
          生成并试用 Skill
        </button>
      </form>
    </section>
  );
}

// CreationRail remains a migration boundary marker; the source-aligned flow
// is represented by the numbered form sections in SkillNewView.

function ConnectionDetailView({
  connection,
  connector,
  onBack,
  onValidate,
  onDiscover,
  busy,
  job,
}: {
  connection: ConnectionProfile | null;
  connector?: ConnectorDefinition;
  onBack?: () => void;
  onValidate: (id: string) => Promise<void>;
  onDiscover: (id: string) => Promise<void>;
  busy: boolean;
  job: { kind: "validate" | "discover"; status: JobResult["status"] } | null;
}) {
  if (!connection) return <div className="kw-empty-page">请选择一个连接。</div>;
  return (
    <section className="kw-detail">
      {onBack ? <button type="button" className="kw-detail-back" onClick={onBack}><ArrowLeft size={16} /> 返回选择</button> : null}
      <div className="kw-detail-heading">
        <div>
          <span className="kw-eyebrow">CONNECTION</span>
          <h1>{connection.display_name}</h1>
          <p>{connector?.display_name || connection.connector_key} · {connection.scope === "team" ? "团队连接" : "个人连接"}</p>
        </div>
        <span className={`kw-pill is-${connection.status}`}>{idempotentLabel(connection.status)}</span>
      </div>
      <div className="kw-detail-card">
        <h2>连接状态</h2>
        <p>状态由 Connection Service 返回，前端不会预设“已支持”或“验证成功”。</p>
        {job ? (
          <p className="kw-state-card" role="status">
            {job.kind === "validate" ? "验证任务" : "能力发现任务"}状态：
            {job.status === "queued" ? "排队中" : job.status === "running" ? "运行中" : job.status === "succeeded" ? "已完成" : "失败"}。
          </p>
        ) : null}
        <div className="kw-detail-actions">
          <button type="button" onClick={() => void onValidate(connection.connection_id)} disabled={busy}><RefreshCw size={15} /> {job?.kind === "validate" && job.status === "failed" ? "重试验证" : "验证连接"}</button>
          <button type="button" onClick={() => void onDiscover(connection.connection_id)} disabled={busy}><Settings2 size={15} /> {job?.kind === "discover" && job.status === "failed" ? "重试发现" : "发现能力"}</button>
        </div>
      </div>
      <pre className="kw-safe-profile">{JSON.stringify(connection.profile || {}, null, 2)}</pre>
    </section>
  );
}

function WorkspaceResourceDetail({
  resource,
  onBack,
  onUse,
}: {
  resource: WorkspaceResource | null;
  onBack?: () => void;
  onUse: () => void;
}) {
  const [preview, setPreview] = useState<JsonObject | null>(null);
  const [toolResults, setToolResults] = useState<Record<string, JsonObject>>({});
  const [busyTool, setBusyTool] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    setError("");
    if (resource?.kind !== "files") return () => { cancelled = true; };
    const uploadId = resource.metadata?.upload_id;
    if (typeof uploadId !== "string" || !uploadId) {
      setError("文件资源缺少 BFF 上传引用，无法预览。");
      return () => { cancelled = true; };
    }
    void knowledgeApi.previewAdapterFile(uploadId)
      .then((result) => {
        if (!cancelled) setPreview(result.data);
      })
      .catch((cause) => {
        if (!cancelled) setError(errorMessage(cause));
      });
    return () => { cancelled = true; };
  }, [resource?.kind, resource?.resource_id, resource?.metadata?.upload_id]);

  if (!resource) return <div className="kw-empty-page">请选择一个资源。</div>;
  const metadata = resource.metadata || {};
  const discovery = metadata.discovery;
  const discoveryObject = discovery
    && typeof discovery === "object"
    && !Array.isArray(discovery)
    ? discovery as JsonObject
    : null;
  const tools: JsonObject[] = discoveryObject && Array.isArray(discoveryObject.tools)
    ? discoveryObject.tools.filter(
      (tool): tool is JsonObject => Boolean(tool) && typeof tool === "object" && !Array.isArray(tool),
    )
    : [];
  const oracleSchemas = resource.kind === "oracle_database"
    && discoveryObject
    && Array.isArray(discoveryObject.schemas)
    ? discoveryObject.schemas.map(String)
    : [];
  const oracleTables = resource.kind === "oracle_database"
    && discoveryObject
    && Array.isArray(discoveryObject.tables)
    ? discoveryObject.tables.map(String)
    : [];
  const definitionId = typeof metadata.definition_id === "string" ? metadata.definition_id : "";
  return (
    <section className="kw-detail">
      {onBack ? <button type="button" className="kw-detail-back" onClick={onBack}><ArrowLeft size={16} /> 返回选择</button> : null}
      <div className="kw-detail-heading">
        <div>
          <span className="kw-eyebrow">RESOURCE</span>
          <h1>{resource.display_name}</h1>
          <p>{resource.kind} · {resource.scope === "team" ? "团队资源" : "个人资源"}</p>
        </div>
        <span className={`kw-pill is-${resource.status}`}>{resource.status}</span>
      </div>
      <div className="kw-detail-card">
        <h2>真实资源详情</h2>
        <p>该资源由 BFF 持久化，并由 Connection Service adapter 提供能力。</p>
        {error ? <div className="kw-form-error" role="alert">{error}</div> : null}
        {resource.kind === "files" ? (
          <div className="kw-resource-preview" data-testid="resource-preview">
            <strong>真实文件预览</strong>
            {preview ? <pre className="kw-safe-profile">{JSON.stringify(preview, null, 2)}</pre> : <span>正在读取预览…</span>}
          </div>
        ) : null}
        {resource.kind === "oracle_database" ? (
          <div className="kw-oracle-discovery" data-testid="oracle-resource-discovery">
            <strong>真实 Oracle Schema / Table discovery</strong>
            <div><span>Schemas</span><b>{oracleSchemas.length ? oracleSchemas.join("、") : "由服务返回为空"}</b></div>
            <div><span>Tables</span><b>{oracleTables.length ? oracleTables.join("、") : "由服务返回为空"}</b></div>
          </div>
        ) : null}
        {resource.kind === "mcp" && tools.length ? (
          <div className="kw-resource-tools" data-testid="mcp-tools">
            <strong>已发现 MCP 工具</strong>
            {tools.map((tool) => {
              const name = typeof tool.name === "string" ? tool.name : "";
              return (
                <div className="kw-tool-row" key={name}>
                  <span>{name}</span>
                  <button
                    type="button"
                    disabled={!definitionId || busyTool === name}
                    onClick={async () => {
                      setBusyTool(name);
                      setError("");
                      try {
                        const result = await knowledgeApi.callMcpAdapter(definitionId, name, {});
                        setToolResults((current) => ({ ...current, [name]: result.data }));
                      } catch (cause) {
                        setError(errorMessage(cause));
                      } finally {
                        setBusyTool("");
                      }
                    }}
                  >
                    {busyTool === name ? "调用中…" : "真实调用"}
                  </button>
                  {toolResults[name] ? <pre className="kw-safe-profile">{JSON.stringify(toolResults[name], null, 2)}</pre> : null}
                </div>
              );
            })}
          </div>
        ) : null}
        <pre className="kw-safe-profile">{JSON.stringify(metadata, null, 2)}</pre>
        <div className="kw-detail-actions">
          <button
            type="button"
            className="kw-primary-small"
            onClick={onUse}
            disabled={resource.status !== "verified"}
          >
            {resource.status === "verified" ? "加入 Skill 上下文" : "当前状态不可用"}
          </button>
        </div>
      </div>
    </section>
  );
}

export function DraftWorkspace({
  draft,
  revisions,
  artifact,
  connections,
  resources,
  turns,
  busy,
  resourceError,
  onSend,
  onCancel,
  onReconnect,
  onRetry,
  onRun,
  onRetryLoad,
}: {
  draft: Draft | null;
  revisions: Revision[];
  artifact: Artifact | null;
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  turns: ConversationTurnModel[];
  busy: string;
  resourceError: { code: string; message: string } | null;
  onSend: (message: string, intent: "update" | "run") => Promise<void>;
  onCancel: () => Promise<void>;
  onReconnect: (turn: ConversationTurnModel) => void;
  onRetry: (turn: ConversationTurnModel) => void;
  onRun: (message: string) => Promise<void>;
  onRetryLoad: () => void;
}) {
  const [task, setTask] = useState(draft?.trial_task || draft?.goal || "");
  const [elapsedNow, setElapsedNow] = useState(Date.now());
  useEffect(() => {
    setTask(draft?.trial_task || draft?.goal || "");
  }, [draft?.draft_id, draft?.trial_task, draft?.goal]);
  const activeTurn = [...turns].reverse().find(
    (turn) => turn.status === "queued" || turn.status === "running",
  );
  useEffect(() => {
    if (!activeTurn) return;
    const timer = window.setInterval(() => setElapsedNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [activeTurn?.invocationId]);
  if (!draft) {
    return (
      <div className="kw-empty-page">
        {resourceError ? (
          <div className="kw-state-card is-failed" role="alert">
            <strong>无法加载当前资源</strong>
            <span>{resourceError.message}</span>
            <button type="button" onClick={onRetryLoad}>重新加载资源</button>
          </div>
        ) : "正在从 BFF 恢复草稿…"}
      </div>
    );
  }
  const errorState = resourceError?.code === "FORBIDDEN"
    ? "permission"
    : resourceError?.code === "CONNECTION_NOT_READY"
      ? "connection_error"
      : resourceError?.code === "PUBLISH_GATE_FAILED"
        ? "upgrade"
        : "";
  const currentRevision = draft.current_revision_id
    ? revisions.find((item) => item.revision_id === draft.current_revision_id) || null
    : revisions.at(-1) || null;
  const boundConnections = connections.filter((connection) => draft.connection_ids.includes(connection.connection_id));
  const boundResources = resources.filter((resource) => draft.resource_ids.includes(resource.resource_id));
  return (
    <section className="kw-draft-layout">
      <div className="kw-draft-center">
        {draft.lifecycle === "failed" ? (
          <div className="kw-run-state-card is-failed" role="status">
            <div className="kw-run-state-icon"><AlertCircle size={18} /></div>
            <div>
              <strong>运行失败</strong>
              <span>上一次试跑没有完成，可以检查连接后重试。</span>
            </div>
            <button type="button" onClick={() => {
              const latest = turns.at(-1);
              if (latest) onRetry(latest);
            }}>重试本次运行</button>
          </div>
        ) : null}
        {errorState === "upgrade" ? (
          <div className="kw-upgrade-banner" role="status">
            <div className="kw-upgrade-copy">
              <AlertCircle size={19} />
              <div><strong>发现基础模型或版本更新</strong><span>这可能导致当前排查方法或口径发生变化。</span></div>
            </div>
            <div className="kw-upgrade-actions"><button type="button" onClick={onRetryLoad}>继续使用原版本</button><button type="button" className="is-warning" onClick={onRetryLoad}>重新生成</button></div>
          </div>
        ) : null}
        {draft.lifecycle === "ready_to_publish" ? (
          <div className="kw-run-state-card is-success" role="status">
            <div className="kw-run-state-icon"><CheckCircle2 size={18} /></div>
            <div>
              <strong>已生成 Skill</strong>
              <span>当前版本已由 BFF 返回，可以继续试跑或发布。</span>
            </div>
            <span className="kw-success-revision">v{revisions.at(-1)?.number || "—"}</span>
          </div>
        ) : null}
        <div className="kw-draft-artifact-card">
          <div className="kw-draft-section-heading">
            <div>
              <h2>这次想完成什么？</h2>
              <p>描述一次真实业务任务，Skill 会基于已授权连接完成分析。</p>
            </div>
          </div>
          <textarea className="kw-draft-task-input" value={task} onChange={(event) => setTask(event.target.value)} rows={3} aria-label="真实业务任务" />
          <div className="kw-draft-task-footer">
            <span><Database size={13} /> 已连接 {draft.connection_ids.length} 个数据源</span>
            {activeTurn ? <span>已耗时 {formatElapsed(activeTurn.startedAt, elapsedNow)}</span> : null}
            <button type="button" className="kw-primary-small" onClick={() => void onRun(task)} disabled={busy === "message" || !task.trim()}><Play size={13} /> 开始</button>
          </div>
          {!artifact ? (
            <div className="kw-draft-waiting"><FileText size={22} /><span>等待运行</span></div>
          ) : null}
        </div>
        <SkillPackagePanel
          draft={draft}
          revision={currentRevision}
          artifact={artifact}
          connections={boundConnections}
          resources={boundResources}
          onRun={() => void onRun(task)}
        />
        {artifact ? <ArtifactViewer artifact={artifact} /> : null}
        {errorState && errorState !== "upgrade" ? (
          <div className="kw-state-overlay" role="alert">
            <div className={`kw-state-dialog is-${errorState}`}>
              <div className="kw-state-dialog-icon">{errorState === "permission" ? <ShieldCheck size={27} /> : <AlertCircle size={27} />}</div>
              <h2>{errorState === "permission" ? "无数据访问权限" : "底层连接已断开"}</h2>
              <p>{errorState === "permission" ? "您没有相关数据源的读写权限。" : "数据源连接失败，可能是网络异常。"}</p>
              <button type="button" onClick={onRetryLoad}>{errorState === "permission" ? "提交申请" : "测试并重连"}</button>
            </div>
          </div>
        ) : null}
      </div>
      <AssistantPanel
        turns={turns}
        busy={busy === "message" || busy === "retry" || busy === "cancel"}
        onSend={onSend}
        onCancel={onCancel}
        onReconnect={onReconnect}
        onRetry={onRetry}
      />
    </section>
  );
}

export function PublishedWorkspace({
  draft,
  revision,
  connections,
  resources,
  onBack,
  onOpenAgent,
  onOpenModal,
  onRun,
}: {
  draft: Draft | null;
  revision: Revision | null;
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  onBack: () => void;
  onOpenAgent: () => void;
  onOpenModal: (kind: string) => void;
  onRun: (message: string) => Promise<void>;
}) {
  if (!draft || !revision) return <div className="kw-empty-page">正在从 BFF 恢复已发布版本…</div>;
  const boundConnections = connections.filter((connection) => draft.connection_ids.includes(connection.connection_id));
  const boundResources = resources.filter((resource) => draft.resource_ids.includes(resource.resource_id));
  return (
    <section className="kw-published">
      <div className="kw-published-header">
        <div><span className="kw-section-kicker">PUBLISHED SKILL</span><h1>{revision.skill_name}</h1><p>{draft.goal}</p></div>
        <span className="kw-published-badge"><CheckCircle2 size={14} /> 已发布</span>
      </div>
      <div className="kw-published-grid">
        <div className="kw-published-card"><span className="kw-card-label">当前版本</span><strong>v{revision.number}</strong><code>sha256:{revision.sha256.slice(0, 18)}…</code></div>
        <div className="kw-published-card"><span className="kw-card-label">调用范围</span><strong>由 BFF 返回</strong><span>发布状态和可见范围由 BFF 返回。</span></div>
      </div>
      <SkillPackagePanel
        draft={draft}
        revision={revision}
        artifact={null}
        connections={boundConnections}
        resources={boundResources}
        onRun={() => void onRun(draft.trial_task || draft.goal)}
        compact
      />
      <div className="kw-published-actions">
        <button type="button" onClick={onBack}>返回工作台</button>
        <button type="button" onClick={() => onOpenModal("share_run")}><Share2 size={14} /> 分享本次结果</button>
        <button type="button" onClick={() => onOpenModal("instructions")}><FileText size={14} /> 调用说明</button>
        <button type="button" onClick={() => onOpenModal("versions")}><History size={14} /> 版本记录</button>
        <button type="button" className="kw-primary-small" onClick={onOpenAgent}><ToyBrick size={14} /> 在 Agent 中使用</button>
      </div>
    </section>
  );
}

function SkillPackagePanel({
  draft,
  revision,
  artifact,
  connections,
  resources,
  onRun,
  compact = false,
}: {
  draft: Draft;
  revision: Revision | null;
  artifact: Artifact | null;
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  onRun: () => void;
  compact?: boolean;
}) {
  const files = previewSkillFiles(revision);
  const skillMd = manifestSkillMarkdown(revision);
  const root = manifestBundleRoot(revision) || MISSING_SKILL_SOURCE;
  const artifactLineage = artifact?.lineage;
  const sourceRefs = artifactLineage?.source_refs;
  const artifactConnectionCount = sourceRefs
    && typeof sourceRefs === "object"
    && !Array.isArray(sourceRefs)
    && Array.isArray(sourceRefs.connection_ids)
      ? sourceRefs.connection_ids.length
      : draft.connection_ids.length;
  return (
    <section className={`kw-skill-package${compact ? " is-compact" : ""}`} data-testid="skill-package">
      <div className="kw-skill-package-header">
        <div>
          <span className="kw-section-kicker">GENERATED SKILL</span>
          <h2>{revision?.skill_name || "等待生成 Skill"}</h2>
          <p>{templateLabel(revision?.template_key || draft.template_key)} · {draft.goal}</p>
        </div>
        <div className="kw-skill-revision">
          <span>Revision</span>
          <strong>{revision ? `v${revision.number}` : "未生成"}</strong>
        </div>
      </div>
      <div className="kw-skill-package-grid">
        <div className="kw-skill-card">
          <div className="kw-skill-card-title"><FileText size={15} /> SKILL.md</div>
          {skillMd
            ? <pre>{skillMd}</pre>
            : <div className="kw-skill-empty">{MISSING_SKILL_SOURCE}</div>}
        </div>
        <div className="kw-skill-card">
          <div className="kw-skill-card-title"><ToyBrick size={15} /> scripts / tests</div>
          {files.length ? (
            <div className="kw-skill-file-list">
              {files.map((file) => (
                <span className={`is-${file.kind}`} key={file.path}>{file.path}</span>
              ))}
            </div>
          ) : <div className="kw-skill-empty">{MISSING_SKILL_SOURCE}</div>}
        </div>
        <div className="kw-skill-card">
          <div className="kw-skill-card-title"><Database size={15} /> 绑定 Connection</div>
          <div className="kw-skill-binding-list">
            {connections.length ? connections.map((connection) => (
              <span key={connection.connection_id}>{connection.display_name} · {idempotentLabel(connection.status)}</span>
            )) : <span>未绑定连接</span>}
            {resources.map((resource) => (
              <span key={resource.resource_id}>{resource.display_name} · {resource.kind}</span>
            ))}
          </div>
        </div>
        <div className="kw-skill-card">
          <div className="kw-skill-card-title"><ShieldCheck size={15} /> 当前包</div>
          <dl className="kw-skill-meta">
            <div><dt>Template</dt><dd>{templateLabel(revision?.template_key || draft.template_key)}</dd></div>
            <div><dt>Root</dt><dd>{root}</dd></div>
            <div><dt>sha256</dt><dd>{revision?.sha256.slice(0, 18) || "等待生成"}{revision ? "…" : ""}</dd></div>
            <div><dt>HTML Artifact</dt><dd>{artifact ? `${artifact.media_type} · ${artifact.sha256.slice(0, 18)}…` : "运行后生成，不覆盖历史"}</dd></div>
            <div><dt>Lineage</dt><dd>{artifact ? `revision ${artifact.revision_id.slice(0, 12)}… / invocation ${artifact.invocation_id.slice(0, 12)}… / sources ${artifactConnectionCount}` : "等待真实运行"}</dd></div>
            <div><dt>验收问题</dt><dd>{draft.trial_task || "未填写"}</dd></div>
          </dl>
        </div>
      </div>
      <div className="kw-skill-package-actions">
        <button type="button" onClick={onRun} disabled={!revision}><Play size={14} /> 试跑</button>
        <span>右侧 Assistant 可继续修改并生成新 Revision。</span>
      </div>
    </section>
  );
}

function WorkspaceStateModal({
  kind,
  draft,
  revision,
  revisions,
  connections,
  onClose,
}: {
  kind: string;
  draft: Draft | null;
  revision: Revision | null;
  revisions: Revision[];
  connections: ConnectionProfile[];
  onClose: () => void;
}) {
  const [agents, setAgents] = useState<CloudRuntime[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [agentsError, setAgentsError] = useState("");
  useEffect(() => {
    if (kind !== "agent") return;
    const controller = new AbortController();
    setAgentsLoading(true);
    setAgentsError("");
    void getRuntimes({
      pageSize: 30,
      region: "all",
      scope: "all",
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setAgents(result.runtimes);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) {
          setAgents([]);
          setAgentsError(cause instanceof Error ? cause.message : "Agent 目录加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setAgentsLoading(false);
      });
    return () => controller.abort();
  }, [kind]);
  const skillName = revision?.skill_name || "当前 Skill";
  const goal = draft?.goal || "当前目标由 BFF 返回。";
  const selectedConnections = draft?.connection_ids.length
    ? connections.filter((connection) => draft.connection_ids.includes(connection.connection_id))
    : [];
  const toolName = selectedConnections[0]?.display_name || "数据源由 BFF 返回";
  const shareRunId = draft?.active_invocation_id
    || new URLSearchParams(window.location.search).get("share_run_id")
    || "未绑定";
  const wrap = (children: ReactNode, className = "") => (
    <div className={`kw-state-modal-overlay${kind === "share_run" || kind === "instructions" ? " is-published" : ""}`} data-state-overlay={kind} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className={`kw-state-modal ${className}`} data-state-modal={kind} role="dialog" aria-modal="true" aria-label={skillName} onMouseDown={(event) => event.stopPropagation()}>
        {children}
      </section>
    </div>
  );
  if (kind === "agent") return (
    <div className="kw-state-modal-overlay is-published" data-state-overlay="agent" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="kw-state-modal kw-agent-modal" data-state-modal="agent" role="dialog" aria-modal="true" aria-label={skillName} onMouseDown={(event) => event.stopPropagation()}>
        <div className="kw-agent-layout">
          <div className="kw-agent-picker">
            <div className="kw-agent-heading"><h2><GlobeIcon /> 选择绑定目标 Agent</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></div>
            {agentsLoading ? (
              <div className="kw-agent-empty kw-agent-empty-inline" role="status">
                <Loader2 className="kw-spin" size={28} />
                <strong>正在加载 Agent 目录</strong>
              </div>
            ) : agentsError ? (
              <div className="kw-agent-empty kw-agent-empty-inline" role="alert">
                <AlertCircle size={28} />
                <strong>Agent 目录加载失败</strong>
                <span>{agentsError}</span>
              </div>
            ) : agents.length ? (
              <div className="kw-agent-directory" role="list" aria-label="Agent 目录">
                {agents.map((agent) => (
                  <div role="listitem" className="kw-agent-directory-row" key={agent.runtimeId}>
                    <ToyBrick size={20} />
                    <span><strong>{agent.name}</strong><small>{agent.region} · {agent.status}</small></span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="kw-agent-empty kw-agent-empty-inline">
                <ToyBrick size={28} />
                <strong>暂无可绑定的 Agent</strong>
                <span>当前账号的真实 Agent 目录为空。</span>
              </div>
            )}
            <div className="kw-agent-footer">
              <button type="button" onClick={onClose} className="kw-agent-cancel">取消</button>
              <button type="button" className="kw-agent-bind" disabled><Play size={14} /> 绑定 API 未开放</button>
            </div>
          </div>
          <div className="kw-agent-empty"><ToyBrick size={48} /><strong>暂不能完成绑定</strong><span>当前服务尚未提供 Skill-to-Agent 绑定 API；目录仅用于展示真实可见 Agent。</span></div>
        </div>
      </section>
    </div>
  );
  if (kind === "share_run") return wrap(
    <><header className="kw-state-modal-header"><h2><Share2 size={21} /> 分享本次结果</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="kw-state-modal-body"><div className="kw-share-warning"><AlertCircle size={18} /><span>当前运行 (RunID: <span className="kw-run-id">{shareRunId}</span>) 尚无服务端快照分享 API。为避免生成无法访问或越权的假链接，分享功能暂不可用。</span></div><button type="button" className="kw-share-create" disabled>分享 API 未开放</button><div className="kw-share-empty">待 BFF 提供受权限保护的结果快照与撤销接口后启用。</div></div></>
  , "is-share");
  if (kind === "instructions") return wrap(
    <><header className="kw-state-modal-header"><h2><FileText size={21} /> 调用说明</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="kw-state-modal-body kw-instructions"><InfoField label="业务用途" value={goal} /><InfoField label="自然语言任务" value={draft?.trial_task || "由调用方提交的任务由 BFF 传递。"} /><InfoField label="业务输出" value="输出内容由已发布 Revision 和真实运行结果决定。" /><InfoField label="发布版本" value={revision ? `v${revision.number}` : "未返回"} mono /><InfoField label="权限范围" value="由 BFF 返回的连接与 Agent 授权范围决定。" /><InfoField label="已绑定 Agent" value="由 BFF 返回" /></div></>
  , "is-instructions");
  if (kind === "versions") return <div className="kw-state-modal-overlay is-published kw-drawer-overlay" data-state-overlay="versions" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="kw-state-modal kw-version-drawer" data-state-modal="versions" role="dialog" aria-modal="true" aria-label="版本记录"><header className="kw-state-modal-header"><h2><History size={21} /> 来源与版本历史</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="kw-version-source"><h3><FileText size={15} /> 数据来源</h3><div><strong>{toolName}</strong><span>{selectedConnections[0] ? `更新时间：${formatServerTimestamp(selectedConnections[0].updated_at)}` : "更新时间由 BFF 返回"}</span></div></div><div className="kw-version-content"><h3><History size={15} /> 版本记录</h3>{revisions.length ? revisions.map((item) => <div className="kw-version-timeline-row" key={item.revision_id}><i /><div><div><strong>v{item.number}</strong><span>{formatServerTimestamp(item.created_at)}</span></div><p>{item.skill_name || skillName}</p><small>sha256:{item.sha256.slice(0, 16)}…</small></div></div>) : <div className="kw-inline-empty">暂无 BFF 返回的版本记录。</div>}</div></section></div>;
  if (kind === "advanced") return wrap(<><header className="kw-state-modal-header"><h2><Settings2 size={21} /> 高级设置 / 诊断</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="kw-state-modal-body kw-advanced"><h3><ShieldCheck size={16} /> 权限审计日志 (Audit Log)</h3><pre>审计明细由 BFF 返回；当前页面未收到可展示的审计记录。</pre><h3><Activity size={16} /> 连接诊断</h3><div className="kw-diagnostic-ok"><Activity size={18} /> 诊断状态由 Connection Service 返回。</div></div></>, "is-advanced");
  if (kind === "tools") return wrap(<><header className="kw-state-modal-header"><h2><Database size={21} /> 数据与工具</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="kw-state-modal-body kw-tools">{selectedConnections.length ? selectedConnections.map((connection) => <div className="kw-tool-row" key={connection.connection_id}><div><strong>{connection.display_name}</strong><span>{connection.connector_key} · {idempotentLabel(connection.status)}</span></div><span className={`kw-tool-ready is-${connection.status}`}>{idempotentLabel(connection.status)}</span></div>) : <div className="kw-inline-empty">暂无 BFF 返回的数据与工具。</div>}<div className="kw-add-tool"><strong>新增资源</strong><span>资源目录由 BFF 返回。</span><button type="button"><CirclePlus size={15} /> 添加新资源</button></div></div></>, "is-tools");
  if (kind === "test_records") return wrap(<><header className="kw-state-modal-header"><h2><History size={21} /> 测试记录</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="kw-records"><table><thead><tr><th>真实任务</th><th>结果摘要</th><th>结果状态</th><th>验证结论</th><th>版本</th></tr></thead><tbody><tr><td>{draft?.trial_task || goal}</td><td>测试记录由 BFF 返回。</td><td><span className="kw-record-neutral">{draft ? DRAFT_LIFECYCLE_LABELS[draft.lifecycle] : "未返回"}</span></td><td>由 BFF 返回</td><td>{revision ? `v${revision.number}` : "未返回"}</td></tr></tbody></table></div></>, "is-records");
  return null;
}

function GlobeIcon() {
  return <span className="kw-title-icon is-purple"><Globe size={20} /></span>;
}

function InfoField({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="kw-info-field"><span>{label}</span><div className={mono ? "is-mono" : ""}>{value}</div></div>;
}

function PublishGateModal({
  draft,
  revision,
  connections,
  busy,
  onClose,
  onPublish,
}: {
  draft: Draft | null;
  revision: Revision | null;
  connections: ConnectionProfile[];
  busy: boolean;
  onClose: () => void;
  onPublish: (target: "personal" | "team") => Promise<void>;
}) {
  const checks = [
    ["数据与工具连接可用", connections.length > 0],
    ["权限范围明确", Boolean(draft?.connection_ids.length)],
    ["无待确认修改", true],
    ["当前 Revision 可发布", Boolean(revision)],
    ["运行状态由 BFF 校验", true],
  ] as const;
  return (
    <div className="kw-state-modal-overlay" data-state-overlay="publish" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="kw-state-modal kw-publish-gate" data-state-modal="publish" role="dialog" aria-modal="true" aria-label="发布门禁检查" onMouseDown={(event) => event.stopPropagation()}>
        <header className="kw-state-modal-header"><h2><ShieldCheck size={22} /> 发布门禁检查</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
        <div className="kw-publish-checks">{checks.map(([label, passed]) => <div className={passed ? "is-passed" : "is-blocked"} key={label}>{passed ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}<span>{label}</span><small>{passed ? "已通过" : "待处理"}</small></div>)}</div>
        <footer className="kw-publish-footer"><span>将固定当前不可变 Revision v{revision?.number || "—"}。</span><div><button type="button" onClick={onClose}>取消</button><button type="button" className="kw-primary-small" onClick={() => void onPublish("team")} disabled={busy || !revision}>确认发布</button></div></footer>
      </section>
    </div>
  );
}

function ConnectionForm({
  connectors,
  initialScope,
  onClose,
  onCreated,
  onResourceCreated,
  onUpload,
}: {
  connectors: ConnectorDefinition[];
  initialScope: "personal" | "team";
  onClose: () => void;
  onCreated: (connection: ConnectionProfile) => Promise<void>;
  onResourceCreated: (resource: WorkspaceResource) => Promise<void>;
  onUpload: (file: File) => Promise<UploadResult>;
}) {
  const [connectorKey, setConnectorKey] = useState(connectors[0]?.connector_key || "");
  const [displayName, setDisplayName] = useState("");
  const [scope, setScope] = useState<"personal" | "team">(initialScope);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [values, setValues] = useState<JsonObject>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<JsonObject | null>(null);
  const [oauthStage, setOauthStage] = useState<
    "idle" | "configuring" | "waiting" | "completing" | "connected" | "cancelled" | "timeout" | "provider_error"
  >("idle");
  const [fileResult, setFileResult] = useState<UploadResult | null>(null);
  const oauthPopupRef = useRef<Window | null>(null);
  useEffect(() => {
    setScope(initialScope);
  }, [initialScope]);
  const categoryOptions = useMemo(() => {
    const values = new Set(connectors.map((item) => readableConnectorCategory(item.category)).filter(Boolean));
    return ["all", ...values];
  }, [connectors]);
  const filteredConnectors = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return connectors.filter((item) => {
      const matchesQuery = !normalizedQuery || connectorSearchText(item).includes(normalizedQuery);
      const matchesCategory = categoryFilter === "all"
        || readableConnectorCategory(item.category) === categoryFilter;
      return matchesQuery && matchesCategory;
    });
  }, [categoryFilter, connectors, query]);
  useEffect(() => {
    if (!connectors.length) return;
    if (!connectors.some((item) => item.connector_key === connectorKey)) {
      setConnectorKey(connectors[0]?.connector_key || "");
    }
  }, [connectorKey, connectors]);
  useEffect(() => {
    if (!filteredConnectors.length) {
      if (query || categoryFilter !== "all") setConnectorKey("");
      return;
    }
    if (connectorKey && filteredConnectors.some((item) => item.connector_key === connectorKey)) return;
    setConnectorKey(filteredConnectors[0].connector_key);
    setValues({});
    setResult(null);
  }, [categoryFilter, connectorKey, filteredConnectors, query]);
  const connector = connectors.find((item) => item.connector_key === connectorKey);
  const isAdapter = connector?.category === "adapter";
  const authOptions = authSchemaOptions(connector?.auth_schema);
  const selectedAuthType = typeof values._auth_type === "string"
    ? values._auth_type
    : authOptions[0]?.value || "";
  const selectedConfigSchema = schemaForAuth(connector?.config_schema, selectedAuthType);
  const selectedAuthSchema = schemaForAuth(connector?.auth_schema, selectedAuthType);
  const fields = [
    ...schemaProperties(selectedConfigSchema).map(([name, schema]) => [
      name,
      schema,
      "config",
      Array.isArray(selectedConfigSchema?.required)
        && selectedConfigSchema.required.includes(name),
    ] as const),
    ...schemaProperties(selectedAuthSchema).map(([name, schema]) => [
      name,
      schema,
      "credential",
      Array.isArray(selectedAuthSchema?.required)
        && selectedAuthSchema.required.includes(name),
    ] as const),
  ];
  useEffect(() => () => {
    oauthPopupRef.current?.close();
    oauthPopupRef.current = null;
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setOauthStage("idle");
    const config: JsonObject = {};
    const credential: JsonObject = selectedAuthType
      ? { _auth_type: selectedAuthType }
      : {};
    for (const [name, , group] of fields) {
      if (group === "config") config[name] = values[name] ?? "";
      else credential[name] = values[name] ?? "";
    }
    const input: CreateConnectionInput = {
      connector_key: connectorKey,
      display_name: displayName.trim(),
      scope,
      config,
      credential,
    };
    try {
      if (connectorKey === "oracle_database") {
        const oracle = oracleBody(values);
        const validation = await knowledgeApi.validateOracleAdapter(oracle);
        const schemaDiscovery = await knowledgeApi.discoverOracleAdapter(oracle);
        const schemas = Array.isArray(schemaDiscovery.data.schemas)
          ? schemaDiscovery.data.schemas.map(String).filter(Boolean)
          : [];
        const selectedSchema = schemas[0];
        const tableDiscovery = selectedSchema
          ? await knowledgeApi.discoverOracleAdapter({
            ...oracle,
            schema: selectedSchema,
          })
          : null;
        const discovery: AdapterCapabilityResult = {
          ...schemaDiscovery.data,
          ...(tableDiscovery?.data || {}),
        };
        const saved = await knowledgeApi.saveOracleResource({
          display_name: displayName.trim() || "Oracle Database",
          scope,
          ...oracle,
          ...(selectedSchema ? { schema: selectedSchema } : {}),
        });
        setResult({
          validation: validation.data as unknown as JsonValue,
          discovery: discovery.data as unknown as JsonValue,
          resource: saved.data as unknown as JsonValue,
        });
        await onResourceCreated(saved.data);
        return;
      }
      if (isAdapter) {
        const adapterResult = connectorKey === "rest_openapi"
          ? await knowledgeApi.saveRestResource({
            display_name: displayName.trim() || "REST / OpenAPI",
            scope,
            baseUrl: values.baseUrl,
            spec: parseJsonObject(values.spec, "OpenAPI JSON"),
            confirmed: values.confirmed === true || values.confirmed === "true",
            auth: {
              type: values.authType || "none",
              header: values.header,
              value: values.value,
              token: values.token,
            },
          })
          : connectorKey === "mcp"
              ? await knowledgeApi.saveMcpResource({
                display_name: displayName.trim() || "MCP Server",
                scope,
                definition: {
                  transport: values.transport || "streamable_http",
                  endpoint: values.endpoint,
                  command: values.command,
                  args: parseStringList(values.args),
                  allowedCommands: values.command ? [String(values.command)] : [],
                  allowedTools: parseStringList(values.allowedTools),
                  allowedLocalhostPorts: parseStringList(values.allowedLocalhostPorts).map(Number),
                  allowLocalhostDev: values.allowLocalhostDev === true
                    || values.allowLocalhostDev === "true",
                  allowPrivateNetwork: values.allowPrivateNetwork === true
                    || values.allowPrivateNetwork === "true",
                },
              })
              : await knowledgeApi.listAdapterFiles();
        if (connectorKey === "files") {
          if (!fileResult) throw new Error("请先选择并上传文件");
          const resources = await knowledgeApi.listResources();
          const resource = resources.data.find(
            (item) =>
              item.kind === "files"
              && item.metadata?.upload_id === fileResult.upload_id,
          );
          if (!resource) throw new Error("文件已上传，但 BFF 未返回可复用的资源记录");
          await onResourceCreated(resource);
          return;
        }
        setResult(Array.isArray(adapterResult.data)
          ? { items: adapterResult.data }
          : adapterResult.data as unknown as JsonObject);
        if (adapterResult.data && typeof adapterResult.data === "object" && !Array.isArray(adapterResult.data) && "resource_id" in adapterResult.data) {
          await onResourceCreated(adapterResult.data as unknown as WorkspaceResource);
        }
        return;
      }
      if (selectedAuthType === "oauth2") {
        const popup = window.open(
          "about:blank",
          "_blank",
          "popup,width=520,height=720",
        );
        if (!popup) {
          throw new OAuthFlowPollError(
            "浏览器阻止了授权窗口，请允许弹窗后重试。",
            "OAUTH_POPUP_BLOCKED",
            false,
          );
        }
        oauthPopupRef.current = popup;
        setOauthStage("configuring");
        const requestedConnectionName = displayName.trim() || connectorKey;
        let authorization: OAuthAuthorizeResult;
        try {
          authorization = (
            await knowledgeApi.authorizeOAuth({
              service: connectorKey,
              client_id: String(values.client_id || ""),
              client_secret: String(values.client_secret || ""),
              connection_name: requestedConnectionName,
            })
          ).data;
          const authorizationUrl = new URL(authorization.authorizationUrl);
          if (!["http:", "https:"].includes(authorizationUrl.protocol)) {
            throw new Error("授权地址无效，请检查 Connection Service 配置。");
          }
          popup.location.replace(authorizationUrl.toString());
        } catch (cause) {
          popup.close();
          oauthPopupRef.current = null;
          throw cause;
        }
        setOauthStage("waiting");
        const connected = await waitForOAuthConnection(
          connectorKey,
          authorization.connectionName,
          async () => (await knowledgeApi.getOAuthStatus(authorization.state)).data,
          async () => (await knowledgeApi.listConnections()).data,
          {
            isPopupClosed: () => popup.closed,
            onStatus: (status) => {
              if (status.status === "connected") setOauthStage("completing");
              else if (status.status === "provider_error") setOauthStage("provider_error");
            },
          },
        );
        setOauthStage("connected");
        setValues((current) => {
          const next = { ...current };
          delete next.client_secret;
          return next;
        });
        setResult({
          status: "connected",
          connection_id: connected.connection_id,
          connector_key: connected.connector_key,
          display_name: connected.display_name,
        });
        popup.close();
        oauthPopupRef.current = null;
        await onCreated(connected);
        return;
      }
      const created = await knowledgeApi.createConnection(input);
      const started = await knowledgeApi.validateConnection(created.data.connection_id);
      await knowledgeApi.waitForConnectionJob(started);
      await onCreated(created.data);
    } catch (cause) {
      if (cause instanceof OAuthFlowPollError) {
        if (cause.code === "OAUTH_CANCELLED") setOauthStage("cancelled");
        if (cause.code === "OAUTH_TIMEOUT") setOauthStage("timeout");
        if (cause.code === "OAUTH_PROVIDER_ERROR") setOauthStage("provider_error");
      }
      oauthPopupRef.current?.close();
      oauthPopupRef.current = null;
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="添加连接或资源" onClose={onClose}>
      <form className="kw-connection-form" onSubmit={submit}>
        <div className="kw-connector-filter">
          <label>
            <span>搜索 Connection</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="按名称、能力、配置字段搜索"
              aria-label="搜索 Connection"
            />
          </label>
          <label>
            <span>分类</span>
            <select
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value)}
              aria-label="Connection 分类"
            >
              {categoryOptions.map((option) => (
                <option value={option} key={option}>{option === "all" ? "全部" : option}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="kw-connector-cards" role="list" aria-label="连接类型">
          {connectorGroups(filteredConnectors).map(([group, items]) => (
            <section key={group} className="kw-connector-group">
              <h3>{group}</h3>
              <div className="kw-connector-grid">
                {items.map((item) => (
                  <button
                    type="button"
                    role="listitem"
                    key={item.connector_key}
                    className={`kw-connector-card${item.connector_key === connectorKey ? " is-selected" : ""}`}
                    onClick={() => { setConnectorKey(item.connector_key); setValues({}); setResult(null); }}
                  >
                    <span className="kw-connector-card-top">
                      <strong>{item.display_name}</strong>
                      <span className={`kw-connector-status is-${item.status}`}>{item.status}</span>
                    </span>
                    <small>{item.category === "adapter" ? "专用适配器" : readableConnectorCategory(item.category)} · {item.capabilities.join(" / ") || "能力由 catalog 返回"}</small>
                    <span>{connectorCredentialLabel(item)}</span>
                    <em>{connectorSchemaSummary(item)}</em>
                  </button>
                ))}
              </div>
            </section>
          ))}
          {!filteredConnectors.length ? (
            <div className="kw-inline-empty">当前 catalog 没有匹配的 Connection。</div>
          ) : null}
        </div>
        <label>显示名称<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></label>
        <label>归属<select value={scope} onChange={(event) => setScope(event.target.value as "personal" | "team")}><option value="personal">个人</option><option value="team">团队</option></select></label>
        {authOptions.length > 1 ? (
          <label>认证方式
            <select
              value={selectedAuthType}
              onChange={(event) => setValues({ _auth_type: event.target.value })}
            >
              {authOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
            </select>
          </label>
        ) : null}
        {fields.map(([name, schema, group, required]) => (
          <label key={`${group}:${name}`}>{String(schema.title || name)}
            {schema.type === "boolean" ? (
              <input
                type="checkbox"
                checked={values[name] === true || values[name] === "true"}
                onChange={(event) => setValues((current) => ({ ...current, [name]: event.target.checked }))}
                required={required}
              />
            ) : (
              <input
                type={schema.format === "password" || group === "credential" ? "password" : "text"}
                value={String(values[name] || "")}
                onChange={(event) => setValues((current) => ({ ...current, [name]: event.target.value }))}
                required={required}
              />
            )}
          </label>
        ))}
        {selectedAuthType === "oauth2" ? (
          <div className="kw-oauth-box">
            <strong>需要配置 OAuth 应用并发起授权</strong>
            <span>Connection Service 会返回真实授权入口；不会提交 no_auth。</span>
            <label>OAuth Client ID<input value={String(values.client_id || "")} onChange={(event) => setValues((current) => ({ ...current, client_id: event.target.value }))} required /></label>
            <label>OAuth Client Secret<input type="password" value={String(values.client_secret || "")} onChange={(event) => setValues((current) => ({ ...current, client_secret: event.target.value }))} required /></label>
          </div>
        ) : null}
        {connectorKey === "mcp" && (
          <div className="kw-oauth-box">
            <strong>本地 MCP 仅限开发模式</strong>
            <span>默认拒绝 localhost / 私网；如确为本地自建服务，请勾选确认并填写明确端口。</span>
            <label><input type="checkbox" checked={values.allowLocalhostDev === true} onChange={(event) => setValues((current) => ({ ...current, allowLocalhostDev: event.target.checked }))} /> 我确认这是本地开发 MCP</label>
            <label>允许的本地端口<input value={String(values.allowedLocalhostPorts || "")} onChange={(event) => setValues((current) => ({ ...current, allowedLocalhostPorts: event.target.value }))} placeholder="例如 3000" /></label>
          </div>
        )}
        {isAdapter ? (
          <div className="kw-form-note">
            专用适配器不创建普通 provider connection，会保存为可加入 Skill 上下文的真实资源。请使用 BFF 暴露的真实 adapter API：
            {connector?.endpoints?.join("、") || "Connection Service adapter endpoints"}。
          </div>
        ) : null}
        {connectorKey === "rest_openapi" ? (
          <div className="kw-form-note">
            当前入口是粘贴 OpenAPI JSON 创建真实 API 资源；网页解析生成 OpenAPI 属于后续能力，不会在此处伪造成功。
          </div>
        ) : null}
        {selectedAuthType === "oauth2" && oauthStage !== "idle" ? (
          <div className="kw-oauth-box" role="status" aria-live="polite">
            <strong>
              {oauthStage === "configuring" ? "正在配置 OAuth 应用"
                : oauthStage === "waiting" ? "等待飞书授权"
                : oauthStage === "completing" ? "正在完成连接"
                : oauthStage === "connected" ? "已连接"
                : oauthStage === "cancelled" ? "用户取消/窗口关闭"
                : oauthStage === "timeout" ? "授权超时"
                : oauthStage === "provider_error" ? "飞书返回错误"
                : "正在配置 OAuth 应用"}
            </strong>
            <span>连接状态以 Connection Service 返回和连接列表为准。</span>
          </div>
        ) : null}
        {result ? (
          <>
            {connectorKey === "oracle_database" ? (
              <OracleDiscoveryResult result={result} />
            ) : null}
            <pre className="kw-safe-profile">{JSON.stringify(result, null, 2)}</pre>
          </>
        ) : null}
        {isAdapter && connectorKey === "files" ? (
          <label>上传文件
            <input
              type="file"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                try {
                  const uploaded = await onUpload(file);
                  setFileResult(uploaded);
                  if (uploaded.upload_id) {
                    const preview = await knowledgeApi.previewAdapterFile(uploaded.upload_id);
                    setResult(preview.data);
                  }
                } catch (cause) {
                  setError(errorMessage(cause));
                }
              }}
            />
          </label>
        ) : null}
        {fileResult ? (
          <div className="kw-form-note">
            已通过 Connection Service 上传并创建文件资源：{fileResult.filename}
          </div>
        ) : null}
        {error ? <div className="kw-form-error" role="alert">{error}</div> : null}
        <div className="kw-modal-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button type="submit" className="kw-primary-small" disabled={busy || !connectorKey}>{busy ? <Loader2 className="kw-spin" size={14} /> : <Upload size={14} />} {selectedAuthType === "oauth2" ? "配置并发起 OAuth" : isAdapter ? "保存专用资源" : "保存并验证"}</button>
        </div>
      </form>
    </Modal>
  );
}

function OracleDiscoveryResult({ result }: { result: JsonObject }) {
  const discovery = result.discovery;
  const record = discovery && typeof discovery === "object" && !Array.isArray(discovery)
    ? discovery as JsonObject
    : {};
  const schemas = Array.isArray(record.schemas) ? record.schemas.map(String) : [];
  const tables = Array.isArray(record.tables) ? record.tables.map(String) : [];
  return (
    <div className="kw-oracle-discovery" data-testid="oracle-discovery-result">
      <strong>真实 Oracle Schema / Table discovery</strong>
      <div><span>Schemas</span><b>{schemas.length ? schemas.join("、") : "由服务返回为空"}</b></div>
      <div><span>Tables</span><b>{tables.length ? tables.join("、") : "由服务返回为空"}</b></div>
    </div>
  );
}

function oracleBody(values: JsonObject): JsonObject {
  return {
    config: {
      host: values.host,
      port: Number(values.port || 1521),
      serviceName: values.serviceName,
      sid: values.sid,
      allowedSchemas: parseStringList(values.allowedSchemas),
    },
    user: values.user,
    password: values.password,
  };
}

function connectorCredentialLabel(connector: ConnectorDefinition): string {
  const authOptions = authSchemaOptions(connector.auth_schema);
  if (authOptions.length) {
    return authOptions.map((option) => option.label).join("、");
  }
  const properties = connector.auth_schema.properties;
  const required = Array.isArray(connector.auth_schema.required)
    ? connector.auth_schema.required.filter((name): name is string => typeof name === "string")
    : [];
  if (required.length) {
    const labels = required.map((name) => {
      const schema = properties && typeof properties === "object" && !Array.isArray(properties)
        ? properties[name]
        : undefined;
      return schema && typeof schema === "object" && !Array.isArray(schema)
        && typeof schema.title === "string"
        ? schema.title
        : name;
    });
    return labels.join(" / ");
  }
  if (properties && typeof properties === "object" && !Array.isArray(properties)
    && Object.keys(properties).length > 0) {
    return "可选 API 凭据";
  }
  return "无需凭据";
}

function connectorGroups(
  connectors: ConnectorDefinition[],
): Array<[string, ConnectorDefinition[]]> {
  const groups = new Map<string, ConnectorDefinition[]>();
  for (const connector of connectors) {
    const label = readableConnectorCategory(connector.category);
    groups.set(label, [...(groups.get(label) || []), connector]);
  }
  return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right, "zh-CN"));
}
