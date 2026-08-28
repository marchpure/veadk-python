import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
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
  MoreHorizontal,
  PanelRight,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Settings2,
  Share2,
  Square,
  ToyBrick,
  Upload,
  User,
  X,
} from "lucide-react";
import { login, resolveIdentity, type AuthStatus } from "../../../adk/identity";
import { ArtifactViewer } from "../artifact/ArtifactViewer";
import {
  knowledgeApi,
  KnowledgeApiError,
  type CreateConnectionInput,
  type JobResult,
  type UploadResult,
} from "../api/client";
import { readQuery, writeQuery } from "../application/cache";
import type {
  ArchivedInvocationEvent,
  Artifact,
  ConnectorDefinition,
  ConnectionProfile,
  Draft,
  Invocation,
  JsonObject,
  KnowledgeInvocationEvent,
  PlanStep,
  Revision,
} from "../domain/types";
import "./knowledge-workspace.css";

type WorkspaceFile =
  | "welcome"
  | "connection"
  | "skill_new"
  | "draft"
  | "published";

interface WorkspaceRoute {
  file: WorkspaceFile;
  draftId: string;
  connectionId: string;
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
  if (error instanceof KnowledgeApiError) {
    return ERROR_LABELS[error.code] || error.message;
  }
  return error instanceof Error ? error.message : "操作失败，请重试。";
}

function invocationErrorMessage(error: { code: string; message: string }): string {
  return ERROR_LABELS[error.code] || error.message;
}

function formatServerTimestamp(value?: string): string {
  if (!value) return "时间由 BFF 返回";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间不可用"
    : date.toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" });
}

function routeFromLocation(): WorkspaceRoute {
  const query = new URLSearchParams(window.location.search);
  const requestedFile = query.get("file") || "welcome";
  const file: WorkspaceFile =
    requestedFile === "welcome"
      ? "welcome"
      : requestedFile === "skill_new"
        ? "skill_new"
        : requestedFile === "connection"
          ? "connection"
          : requestedFile === "draft"
            ? "draft"
            : requestedFile === "published"
              ? "published"
        : requestedFile.startsWith("pub_")
          ? "published"
          : requestedFile.startsWith("draft_")
            ? "draft"
            : "welcome";
  return {
    file,
    draftId: query.get("draftId") || "",
    connectionId: query.get("connectionId") || "",
    modal: query.get("modal") || "",
  };
}

function setRoute(file: WorkspaceFile, draftId = "", connectionId = "") {
  const query = new URLSearchParams();
  query.set("view", "knowledge-workspace");
  query.set("file", file);
  if (draftId) query.set("draftId", draftId);
  if (connectionId) query.set("connectionId", connectionId);
  window.history.pushState({}, "", `${window.location.pathname}?${query}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function idempotentLabel(status: ConnectionProfile["status"]): string {
  return STATUS_LABELS[status] || status;
}

function schemaProperties(schema: JsonObject | undefined): Array<[string, JsonObject]> {
  const properties = schema?.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
  return Object.entries(properties).flatMap(([name, value]) => (
    value && typeof value === "object" && !Array.isArray(value)
      ? [[name, value as JsonObject]]
      : []
  ));
}

export function KnowledgeWorkspacePage() {
  const [route, setRouteState] = useState(routeFromLocation);
  const [connections, setConnections] = useState<ConnectionProfile[]>(
    () => readQuery<ConnectionProfile[]>("connections") || [],
  );
  const [connectors, setConnectors] = useState<ConnectorDefinition[]>(
    () => readQuery<ConnectorDefinition[]>("connector-definitions") || [],
  );
  const [drafts, setDrafts] = useState<Draft[]>(
    () => readQuery<Draft[]>("drafts") || [],
  );
  const [draft, setDraft] = useState<Draft | null>(null);
  const [etag, setEtag] = useState("");
  const [draftLoadAttempt, setDraftLoadAttempt] = useState(0);
  const [draftResourceError, setDraftResourceError] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [selectedConnectionIds, setSelectedConnectionIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showConnectionForm, setShowConnectionForm] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [showPublish, setShowPublish] = useState(false);
  const [welcomeGoal, setWelcomeGoal] = useState("");
  const [connectionJob, setConnectionJob] = useState<{
    kind: "validate" | "discover";
    status: JobResult["status"];
  } | null>(null);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const popstate = useCallback(() => setRouteState(routeFromLocation()), []);

  useEffect(() => {
    void resolveIdentity()
      .then((identity) => setAuthStatus(identity.status))
      .catch(() => setAuthStatus("unauthenticated"));
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated") return;
    window.addEventListener("popstate", popstate);
    return () => window.removeEventListener("popstate", popstate);
  }, [authStatus, popstate]);

  const reloadDirectory = useCallback(async (signal?: AbortSignal) => {
    const [connectionResult, connectorResult, draftResult] = await Promise.all([
      knowledgeApi.listConnections(signal),
      knowledgeApi.listConnectorDefinitions(signal),
      knowledgeApi.listDrafts(signal),
    ]);
    setConnections(writeQuery("connections", connectionResult.data));
    setConnectors(writeQuery("connector-definitions", connectorResult.data));
    setDrafts(writeQuery("drafts", draftResult.data));
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
        setSelectedConnectionIds([result.value.data.connection_id]);
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
      setDraftResourceError(null);
      return;
    }
    const controller = new AbortController();
    setBusy("load-draft");
    setDraftResourceError(null);
    void knowledgeApi.getDraft(route.draftId, controller.signal)
      .then(async (result) => {
        if (controller.signal.aborted) return;
        setDraft(result.value.data);
        setEtag(result.etag);
        setSelectedConnectionIds(result.value.data.connection_ids);
        const revisionResult = await knowledgeApi.listRevisions(route.draftId, controller.signal);
        setRevisions(revisionResult.data);
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

  const createAndGenerate = useCallback(async (
    goal: string,
    connectionIds: string[],
    trialTask: string,
    uploadIds: string[],
  ) => {
    setBusy("generate");
    setError("");
    try {
      const created = await knowledgeApi.createDraft({
        goal,
        connection_ids: connectionIds,
        ...(trialTask.trim() ? { trial_task: trialTask.trim() } : {}),
        ...(uploadIds.length ? { upload_ids: uploadIds } : {}),
      });
      setDraft(created.value.data);
      setEtag(created.etag);
      setSelectedConnectionIds(connectionIds);
      setDrafts((current) => [
        ...current.filter((item) => item.draft_id !== created.value.data.draft_id),
        created.value.data,
      ]);
      setRoute("draft", created.value.data.draft_id);
      const invocation = await knowledgeApi.generateDraft(
        created.value.data.draft_id,
        created.etag,
        trialTask.trim() || undefined,
      );
      setActiveInvocation(invocation.data);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, []);

  const uploadSkillInput = useCallback(async (
    file: File,
    onProgress: (percent: number) => void,
  ): Promise<UploadResult> => {
    const result = await knowledgeApi.uploadFile(file, "skill_input", onProgress);
    return result.data;
  }, []);

  const [activeInvocation, setActiveInvocation] = useState<Invocation | null>(null);
  const [events, setEvents] = useState<KnowledgeInvocationEvent[]>([]);
  const [unknownEvents, setUnknownEvents] = useState<ArchivedInvocationEvent[]>([]);
  const [assistantText, setAssistantText] = useState("");
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [streamState, setStreamState] = useState<"idle" | "connected" | "disconnected" | "done">("idle");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const lastEventIdRef = useRef("");
  const terminalInvocationRef = useRef(false);
  const seenEventIdsRef = useRef(new Set<string>());

  const applyEvent = useCallback((event: KnowledgeInvocationEvent) => {
    if (seenEventIdsRef.current.has(event.id)) return;
    seenEventIdsRef.current.add(event.id);
    setEvents((current) => [...current, event]);
    lastEventIdRef.current = event.id;
    if (event.type === "assistant.delta") {
      setAssistantText((current) => current + event.data.text);
    } else if (event.type === "plan.updated") {
      setPlan(event.data.steps);
    } else if (event.type === "artifact.created") {
      void knowledgeApi.getArtifact(event.data.artifact_id)
        .then((result) => setArtifact(result.value.data))
        .catch((cause) => setError(errorMessage(cause)));
    } else if (event.type === "revision.created" && draft) {
      void knowledgeApi.listRevisions(draft.draft_id)
        .then((result) => setRevisions(result.data))
        .catch((cause) => setError(errorMessage(cause)));
    }
    if (
      event.type === "run.completed"
      || event.type === "run.failed"
      || event.type === "run.cancelled"
    ) {
      terminalInvocationRef.current = true;
      setStreamState("done");
    }
  }, [draft]);

  const stream = useCallback(async () => {
    if (!activeInvocation) return;
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    terminalInvocationRef.current = false;
    setStreamState("connected");
    if (!startedAt) setStartedAt(Date.now());
    try {
      for await (const event of knowledgeApi.streamInvocationEvents(activeInvocation, {
        signal: controller.signal,
        lastEventId: lastEventIdRef.current || undefined,
        onUnknown: (unknown) => setUnknownEvents((current) => [...current, unknown]),
      })) {
        applyEvent(event);
      }
      if (!controller.signal.aborted && !terminalInvocationRef.current) {
        setStreamState("disconnected");
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        setStreamState("disconnected");
        setError(errorMessage(cause));
      }
    }
  }, [activeInvocation, applyEvent, startedAt]);

  useEffect(() => {
    if (activeInvocation) {
      setEvents([]);
      setUnknownEvents([]);
      setAssistantText("");
      setPlan([]);
      lastEventIdRef.current = "";
      seenEventIdsRef.current = new Set();
      void stream();
    }
    return () => streamAbortRef.current?.abort();
    // A new invocation starts one subscription. Reconnect is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeInvocation]);

  const cancel = useCallback(async () => {
    if (!activeInvocation) return;
    setBusy("cancel");
    try {
      await knowledgeApi.cancelInvocation(activeInvocation.invocation_id);
      streamAbortRef.current?.abort();
      setStreamState("done");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [activeInvocation]);

  const sendMessage = useCallback(async (message: string, intent: "update" | "run") => {
    if (!draft || !message.trim()) return;
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
      setAssistantText("");
      setPlan([]);
      setEvents([]);
      setUnknownEvents([]);
      lastEventIdRef.current = "";
      seenEventIdsRef.current = new Set();
      setStartedAt(Date.now());
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [draft, etag]);

  const retryInvocation = useCallback(async () => {
    if (!draft || !activeInvocation) return;
    setBusy("retry");
    setError("");
    try {
      const result = activeInvocation.kind === "generate"
        ? await knowledgeApi.generateDraft(draft.draft_id, etag, draft.trial_task)
        : await knowledgeApi.sendDraftMessage(
          draft.draft_id,
          draft.trial_task || "请重新试跑当前 Skill。",
          "run",
          etag,
      );
      setActiveInvocation(result.data);
      setStartedAt(Date.now());
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
      await knowledgeApi.publishRevision(revision.revision_id, target);
      setShowPublish(false);
      setRoute("published", draft?.draft_id);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy("");
    }
  }, [draft?.current_revision_id, draft?.draft_id, revisions]);

  // Keep the directory snapshot as the underlying document when a detail
  // request fails. This lets the UI render a real, actionable state overlay
  // instead of collapsing to a URL-only error page.
  const selectedDraft = draft || drafts.find((item) => item.draft_id === route.draftId) || null;
  const selectedConnection = connections.find(
    (item) => item.connection_id === route.connectionId
      || selectedConnectionIds.includes(item.connection_id),
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
        <button type="button" className="kw-primary-small" onClick={login}>登录</button>
      </div>
    );
  }
  return (
    <div className={`kw-shell${selectedDraft ? " has-draft" : ""}${route.file === "draft" ? " is-draft-route" : ""}`}>
      <header className="kw-studio-nav">
        <button className="kw-studio-brand" type="button" onClick={() => setRoute("welcome")}>
          <span className="kw-studio-mark"><Database size={15} /></span>
          <span>Knowledge Asset</span>
        </button>
        <nav className="kw-studio-links" aria-label="Studio">
          <button className="is-active" type="button" onClick={() => setRoute("welcome")}>工作台</button>
          <button type="button" onClick={() => setRoute("skill_new")}>创建</button>
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
          <button className="kw-new-resource" type="button" aria-label="新建 Skill" onClick={() => setRoute("skill_new")}>
            <CirclePlus size={16} /> 新建 Skill
          </button>
          <div className="kw-tree-label">个人工作区</div>
          <button
            className={`kw-tree-item${route.file === "welcome" ? " is-selected" : ""}`}
            type="button"
            onClick={() => setRoute("welcome")}
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
              onClick={() => {
                setSelectedConnectionIds([connection.connection_id]);
                setRoute("connection", "", connection.connection_id);
              }}
            >
              <Settings2 size={15} />
              <span>{connection.display_name}</span>
              <span className={`kw-status-dot is-${connection.status}`} title={idempotentLabel(connection.status)} />
            </button>
          ))}
          <button className="kw-tree-item kw-tree-add" type="button" onClick={() => setShowConnectionForm(true)}>
            <CirclePlus size={15} /> 添加连接
          </button>
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
          <div className="kw-tree-label">团队工作区</div>
          {teamConnections.length ? teamConnections.map((connection) => (
            <button
              className={`kw-tree-item${selectedConnectionIds.includes(connection.connection_id) ? " is-selected" : ""}`}
              type="button"
              key={connection.connection_id}
              onClick={() => {
                setSelectedConnectionIds([connection.connection_id]);
                setRoute("connection", "", connection.connection_id);
              }}
            >
              <Settings2 size={15} />
              <span>{connection.display_name}</span>
              <span className={`kw-status-dot is-${connection.status}`} title={idempotentLabel(connection.status)} />
            </button>
          )) : <div className="kw-tree-muted">团队目录由当前 BFF 权限返回。</div>}
          <div className="kw-sidebar-footer">通过 Studio BFF 连接</div>
        </aside>

        <main className="kw-main">
        {route.file === "draft" && selectedDraft ? (
          <header className="kw-topbar kw-draft-topbar">
            <div className="kw-draft-topbar-heading">
              <button type="button" className="kw-icon-button" onClick={() => setRoute("welcome")} aria-label="返回工作台">
                <ArrowLeft size={18} />
              </button>
              <h1>{selectedRevision?.skill_name || selectedDraft.goal}</h1>
              <span className="kw-draft-status">草稿</span>
              <span className="kw-draft-autosave">已自动保存</span>
            </div>
            <div className="kw-top-actions kw-draft-top-actions">
              <button type="button" onClick={() => {
                const query = new URLSearchParams(window.location.search);
                query.set("modal", "tools");
                window.history.pushState({}, "", `${window.location.pathname}?${query}`);
                window.dispatchEvent(new PopStateEvent("popstate"));
              }}><Database size={14} />数据与工具 ({selectedDraft.connection_ids.length})</button>
              <button type="button" onClick={() => {
                const query = new URLSearchParams(window.location.search);
                query.set("modal", "test_records");
                window.history.pushState({}, "", `${window.location.pathname}?${query}`);
                window.dispatchEvent(new PopStateEvent("popstate"));
              }}><History size={14} />测试记录</button>
              <button type="button" onClick={() => setShowVersions(true)}>版本</button>
              <button type="button" className="kw-primary-small" onClick={() => setShowPublish(true)} disabled={!revisions.length}>
                发布
              </button>
              <button type="button" className="kw-icon-button" aria-label="更多操作"><MoreHorizontal size={18} /></button>
            </div>
          </header>
        ) : route.file === "connection" ? (
          <header className="kw-topbar">
            <div className="kw-breadcrumb">
              <button type="button" onClick={() => setRoute("welcome")}>知识资产</button>
              {selectedConnection ? <><ChevronRight size={14} /><span>{selectedConnection.display_name}</span></> : null}
            </div>
          </header>
        ) : null}
        {error && !draftResourceError ? (
          <div className="kw-error" role="alert">
            <AlertCircle size={16} /> <span>{error}</span>
            <button type="button" onClick={() => setError("")} aria-label="关闭错误"><X size={14} /></button>
          </div>
        ) : null}
        {route.file === "welcome" && !selectedDraft ? (
          <WelcomeEntryView
            drafts={drafts}
            onOpen={openDraft}
            onCreate={(goal) => { setWelcomeGoal(goal); setRoute("skill_new"); }}
          />
        ) : route.file === "skill_new" ? (
          <section className="kw-create-layout is-skill-new">
            <SkillNewView
              connections={personalConnections}
              selectedIds={selectedConnectionIds}
              onSelectedIdsChange={setSelectedConnectionIds}
              onCreate={createAndGenerate}
              onUpload={uploadSkillInput}
              onAddConnection={() => setShowConnectionForm(true)}
              busy={busy === "generate"}
              initialGoal={welcomeGoal}
              onBack={() => setRoute("welcome")}
            />
          </section>
        ) : route.file === "connection" ? (
          <ConnectionDetailView
            connection={selectedConnection}
            connector={connectors.find((item) => item.connector_key === selectedConnection?.connector_key)}
            onValidate={async (id) => {
              setBusy("validate");
              try {
                const result = await knowledgeApi.validateConnection(id);
                setConnectionJob({ kind: "validate", status: result.data.status });
                await reloadDirectory();
              }
              catch (cause) { setError(errorMessage(cause)); }
              finally { setBusy(""); }
            }}
            onDiscover={async (id) => {
              setBusy("discover");
              try {
                const result = await knowledgeApi.discoverConnection(id);
                setConnectionJob({ kind: "discover", status: result.data.status });
                await reloadDirectory();
              }
              catch (cause) { setError(errorMessage(cause)); }
              finally { setBusy(""); }
            }}
            busy={busy === "validate" || busy === "discover"}
            job={connectionJob}
          />
        ) : route.file === "published" ? (
          <PublishedWorkspace
            draft={selectedDraft}
            revision={selectedRevision}
            onBack={() => setRoute("welcome")}
            onOpenAgent={() => openRouteModal("agent")}
            onOpenModal={openRouteModal}
          />
        ) : (
          <DraftWorkspace
            draft={selectedDraft}
            revisions={revisions}
            artifact={artifact}
            events={events}
            unknownEvents={unknownEvents}
            assistantText={assistantText}
            plan={plan}
            streamState={streamState}
            activeInvocation={activeInvocation}
            busy={busy}
            resourceError={draftResourceError}
            onSend={sendMessage}
            onCancel={cancel}
            onReconnect={() => void stream()}
            onRetry={() => void retryInvocation()}
            onRun={(message) => sendMessage(message, "run")}
            onRetryLoad={() => {
              setError("");
              setDraftLoadAttempt((current) => current + 1);
            }}
          />
        )}
        </main>

      </div>
      {showConnectionForm ? (
        <ConnectionForm
          connectors={connectors}
          onClose={() => setShowConnectionForm(false)}
          onCreated={async (created) => {
            setShowConnectionForm(false);
            setSelectedConnectionIds([created.connection_id]);
            await reloadDirectory();
            setRoute("connection", "", created.connection_id);
          }}
        />
      ) : null}
      {showVersions ? (
        <Modal title="版本历史" onClose={() => setShowVersions(false)}>
          {revisions.length ? revisions.map((revision) => (
            <div className="kw-version-row" key={revision.revision_id}>
              <span>v{revision.number} · {revision.skill_name}</span>
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

function SkillNewView({
  connections,
  selectedIds,
  onSelectedIdsChange,
  onCreate,
  onUpload,
  onAddConnection,
  busy,
  initialGoal,
  onBack,
}: {
  connections: ConnectionProfile[];
  selectedIds: string[];
  onSelectedIdsChange: (ids: string[]) => void;
  onCreate: (goal: string, connectionIds: string[], trialTask: string, uploadIds: string[]) => Promise<void>;
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
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (goal.trim() && selectedIds.length) {
      void onCreate(goal, selectedIds, trialTask, uploads.map((upload) => upload.upload_id));
    }
  };
  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
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
        <label>
          <span className="kw-form-step-label">1. 谁会使用，希望解决什么问题</span>
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
            <span>2. 接入数据与工具</span>
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
        </div>
        <label>
          <span className="kw-form-step-label">3. 先试一句任务（可选）</span>
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
        <button className="kw-primary" type="submit" disabled={busy || !goal.trim() || !selectedIds.length}>
          {busy ? <Loader2 className="kw-spin" size={16} /> : <Play size={16} />}
          生成并试用 Skill
        </button>
      </form>
    </section>
  );
}

function WelcomeEntryView({
  drafts,
  onOpen,
  onCreate,
}: {
  drafts: Draft[];
  onOpen: (draft: Draft) => void;
  onCreate: (goal: string) => void;
}) {
  return (
    <section className="kw-welcome-entry">
      <div className="kw-welcome-dashboard">
        <div className="kw-welcome-dashboard-heading">
          <h1>我的 Skill</h1>
          <button type="button" className="kw-primary-small" onClick={() => onCreate("")}><CirclePlus size={15} /> 新建 Skill</button>
        </div>
        <div className="kw-welcome-grid">
          {drafts.map((draft) => (
            <article className="kw-welcome-card" key={draft.draft_id}>
              <div className="kw-welcome-card-heading">
                <div className="kw-welcome-card-icon"><ToyBrick size={20} /></div>
                <div className="kw-welcome-card-copy">
                  <strong>{(draft as Draft & { display_name?: string }).display_name || draft.goal}</strong>
                  <span>{draft.goal}</span>
                </div>
                <span className={`kw-welcome-status is-${draft.lifecycle}`}>{draft.lifecycle === "published" ? "已发布" : "草稿"}</span>
              </div>
              <div className="kw-welcome-card-meta">
                <span>最新任务</span><strong>{draft.trial_task || "初次制作"}</strong>
                <span>Skill 状态</span><strong>{DRAFT_LIFECYCLE_LABELS[draft.lifecycle]}</strong>
                <span>已连接资源</span><strong>{draft.connection_ids.length} 项</strong>
              </div>
              <button type="button" onClick={() => onOpen(draft)}>{draft.lifecycle === "published" ? "试用" : "继续完善"}<ChevronRight size={14} /></button>
            </article>
          ))}
          {!drafts.length ? <div className="kw-welcome-empty"><MessageSquare size={30} /><span>暂无相关的 Skill</span></div> : null}
        </div>
      </div>
    </section>
  );
}

// CreationRail remains a migration boundary marker; the source-aligned flow
// is represented by the numbered form sections in SkillNewView.

function ConnectionDetailView({
  connection,
  connector,
  onValidate,
  onDiscover,
  busy,
  job,
}: {
  connection: ConnectionProfile | null;
  connector?: ConnectorDefinition;
  onValidate: (id: string) => Promise<void>;
  onDiscover: (id: string) => Promise<void>;
  busy: boolean;
  job: { kind: "validate" | "discover"; status: JobResult["status"] } | null;
}) {
  if (!connection) return <div className="kw-empty-page">请选择一个连接。</div>;
  return (
    <section className="kw-detail">
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
            {job.kind === "validate" ? "验证任务" : "能力发现任务"}已提交，当前状态：{job.status === "queued" ? "排队中" : "运行中"}。
          </p>
        ) : null}
        <div className="kw-detail-actions">
          <button type="button" onClick={() => void onValidate(connection.connection_id)} disabled={busy}><RefreshCw size={15} /> 验证连接</button>
          <button type="button" onClick={() => void onDiscover(connection.connection_id)} disabled={busy}><Settings2 size={15} /> 发现能力</button>
        </div>
      </div>
      <pre className="kw-safe-profile">{JSON.stringify(connection.profile || {}, null, 2)}</pre>
    </section>
  );
}

function DraftWorkspace({
  draft,
  revisions,
  artifact,
  events,
  unknownEvents,
  assistantText,
  plan,
  streamState,
  activeInvocation,
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
  events: KnowledgeInvocationEvent[];
  unknownEvents: ArchivedInvocationEvent[];
  assistantText: string;
  plan: PlanStep[];
  streamState: "idle" | "connected" | "disconnected" | "done";
  activeInvocation: Invocation | null;
  busy: string;
  resourceError: { code: string; message: string } | null;
  onSend: (message: string, intent: "update" | "run") => Promise<void>;
  onCancel: () => Promise<void>;
  onReconnect: () => void;
  onRetry: () => void;
  onRun: (message: string) => Promise<void>;
  onRetryLoad: () => void;
}) {
  const [message, setMessage] = useState("");
  const [task, setTask] = useState(draft?.trial_task || draft?.goal || "");
  const timelineEnd = useRef<HTMLDivElement>(null);
  useEffect(() => timelineEnd.current?.scrollIntoView({ block: "nearest" }), [events, assistantText]);
  useEffect(() => {
    setTask(draft?.trial_task || draft?.goal || "");
  }, [draft?.draft_id, draft?.trial_task, draft?.goal]);
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
  const failedEvent = [...events].reverse().find((event) => event.type === "run.failed");
  const errorState = resourceError?.code === "FORBIDDEN"
    ? "permission"
    : resourceError?.code === "CONNECTION_NOT_READY"
      ? "connection_error"
      : resourceError?.code === "PUBLISH_GATE_FAILED"
        ? "upgrade"
        : "";
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
            <button type="button" onClick={onRetry}>重试本次运行</button>
          </div>
        ) : null}
        {errorState === "upgrade" ? (
          <div className="kw-upgrade-banner" role="status">
            <div className="kw-upgrade-copy">
              <AlertCircle size={19} />
              <div><strong>发现基础模型或版本更新</strong><span>这可能导致当前排查步骤或口径发生变化。</span></div>
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
            <button type="button" className="kw-primary-small" onClick={() => void onRun(task)} disabled={busy === "message" || !task.trim()}><Play size={13} /> 开始</button>
          </div>
          {!artifact ? (
            <div className="kw-draft-waiting"><FileText size={22} /><span>等待运行</span></div>
          ) : null}
        </div>
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
      <aside className="kw-chat">
        <div className="kw-chat-heading">
          <div className="kw-chat-title"><PanelRight size={16} /> 分析助手 <span>{activeInvocation ? "· 实时" : ""}</span></div>
          {activeInvocation && streamState === "connected" ? <button type="button" onClick={() => void onCancel()}><Square size={13} /> 取消</button> : null}
          {activeInvocation && streamState === "disconnected" ? <button type="button" onClick={onReconnect}><RefreshCw size={13} /> 从 {events.at(-1)?.id || "起点"} 重连</button> : null}
        </div>
        <div className="kw-timeline" aria-live="polite">
          {!events.length && !assistantText ? (
            <div className="kw-chat-welcome">
              <div className="kw-chat-bot-avatar"><MessageSquare size={13} /></div>
              <div className="kw-chat-welcome-body">
                <div className="kw-chat-message">你好！正在为您提供关于 <strong>{revisions.at(-1)?.skill_name || "当前 Skill"}</strong> 的协助。</div>
                <div className="kw-chat-suggestions">
                  {["看看最近的经营异常", "补充历史数据证据", "调整 Skill 的判断逻辑"].map((suggestion) => (
                    <button key={suggestion} type="button" onClick={() => setMessage(suggestion)}>{suggestion}</button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
          {plan.length ? (
            <div className="kw-plan-card"><strong>执行计划</strong>{plan.map((step) => <div key={step.id}><span className={`kw-step-dot is-${step.status}`} />{step.label}</div>)}</div>
          ) : null}
          {assistantText ? <div className="kw-assistant-message">{assistantText}</div> : null}
          {failedEvent ? (
            <div className="kw-run-error" role="alert">
              <strong>本次运行失败</strong>
              <span>{invocationErrorMessage(failedEvent.data.error)}</span>
              {failedEvent.data.error.retryable ? <button type="button" onClick={onRetry} disabled={busy === "retry"}>重试本次运行</button> : null}
            </div>
          ) : null}
          {events
            .filter((event): event is KnowledgeInvocationEvent & { type: "tool.started" | "tool.completed" } =>
              event.type === "tool.started" || event.type === "tool.completed")
            .map((event) => (
              <div className="kw-tool-card" key={event.id}>
                <strong>{event.data.tool_name}</strong>
                <span>{event.type === "tool.started" ? "调用中…" : `${event.data.status || "完成"} · ${event.data.duration_ms ?? 0}ms`}</span>
              </div>
            ))}
          {unknownEvents.length ? <details className="kw-unknown-events"><summary>已归档 {unknownEvents.length} 个未知事件</summary><pre>{unknownEvents.map((event) => `${event.id} ${event.type}`).join("\n")}</pre></details> : null}
          <div ref={timelineEnd} />
        </div>
        <Composer value={message} onChange={setMessage} onSend={async (intent) => { await onSend(message, intent); setMessage(""); }} busy={busy === "message"} />
      </aside>
    </section>
  );
}

function PublishedWorkspace({
  draft,
  revision,
  onBack,
  onOpenAgent,
  onOpenModal,
}: {
  draft: Draft | null;
  revision: Revision | null;
  onBack: () => void;
  onOpenAgent: () => void;
  onOpenModal: (kind: string) => void;
}) {
  if (!draft || !revision) return <div className="kw-empty-page">正在从 BFF 恢复已发布版本…</div>;
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
  const skillName = revision?.skill_name || "当前 Skill";
  const goal = draft?.goal || "当前目标由 BFF 返回。";
  const selectedConnections = draft?.connection_ids.length
    ? connections.filter((connection) => draft.connection_ids.includes(connection.connection_id))
    : [];
  const toolName = selectedConnections[0]?.display_name || "数据源由 BFF 返回";
  const shareRunId = draft?.active_invocation_id
    || new URLSearchParams(window.location.search).get("share_run_id")
    || "未绑定";
  const wrap = (children: React.ReactNode, className = "") => (
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
            <div className="kw-agent-empty kw-agent-empty-inline">
              <ToyBrick size={28} />
              <strong>暂无可绑定的 Agent</strong>
              <span>可绑定目标由 BFF 权限与 Agent 目录返回。</span>
            </div>
            <div className="kw-agent-footer">
              <button type="button" onClick={onClose} className="kw-agent-cancel">取消</button>
              <button type="button" className="kw-agent-bind" disabled><Play size={14} /> 绑定并调用</button>
            </div>
          </div>
          <div className="kw-agent-empty"><ToyBrick size={48} /><strong>等待选择 Agent</strong><span>选择 Agent 并点击确认后，将在此展示真实调用与结果渲染。</span></div>
        </div>
      </section>
    </div>
  );
  if (kind === "share_run") return wrap(
    <><header className="kw-state-modal-header"><h2><Share2 size={21} /> 分享本次结果</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="kw-state-modal-body"><div className="kw-share-warning"><AlertCircle size={18} /><span>当前分享严格绑定在单次运行结果上 (RunID: <span className="kw-run-id">{shareRunId}</span>)。<br />该链接内容不会随着系统配置实时刷新，也无法对内容进行调整。</span></div><button type="button" className="kw-share-create">生成结果快照链接</button><h3>已生成的链接 (0)</h3><div className="kw-share-empty">暂无分享链接</div></div></>
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

function Composer({
  value,
  onChange,
  onSend,
  busy,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: (intent: "update" | "run") => Promise<void>;
  busy: boolean;
}) {
  return (
    <div className="kw-composer">
      <textarea value={value} onChange={(event) => onChange(event.target.value)} placeholder="描述修改，或输入任务试跑…" rows={3} />
      <div className="kw-composer-actions">
        <button type="button" onClick={() => void onSend("update")} disabled={busy || !value.trim()}><Send size={14} /> 修改</button>
        <button type="button" className="kw-primary-small" onClick={() => void onSend("run")} disabled={busy || !value.trim()}><Play size={14} /> 试跑</button>
      </div>
    </div>
  );
}

function ConnectionForm({
  connectors,
  onClose,
  onCreated,
}: {
  connectors: ConnectorDefinition[];
  onClose: () => void;
  onCreated: (connection: ConnectionProfile) => Promise<void>;
}) {
  const [connectorKey, setConnectorKey] = useState(connectors[0]?.connector_key || "");
  const [displayName, setDisplayName] = useState("");
  const [scope, setScope] = useState<"personal" | "team">("personal");
  const [values, setValues] = useState<JsonObject>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const connector = connectors.find((item) => item.connector_key === connectorKey);
  const fields = [
    ...schemaProperties(connector?.config_schema).map(([name, schema]) => [
      name,
      schema,
      "config",
      Array.isArray(connector?.config_schema.required)
        && connector.config_schema.required.includes(name),
    ] as const),
    ...schemaProperties(connector?.auth_schema).map(([name, schema]) => [
      name,
      schema,
      "credential",
      Array.isArray(connector?.auth_schema.required)
        && connector.auth_schema.required.includes(name),
    ] as const),
  ];
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const config: JsonObject = {};
    const credential: JsonObject = {};
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
      const created = await knowledgeApi.createConnection(input);
      await knowledgeApi.validateConnection(created.data.connection_id);
      await onCreated(created.data);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="添加连接" onClose={onClose}>
      <form className="kw-connection-form" onSubmit={submit}>
        <label>连接类型
          <select value={connectorKey} onChange={(event) => { setConnectorKey(event.target.value); setValues({}); }} required>
            <option value="" disabled>请选择后端已启用的连接</option>
            {connectors.map((item) => <option value={item.connector_key} key={item.connector_key}>{item.display_name} · {item.status}</option>)}
          </select>
        </label>
        <label>显示名称<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></label>
        <label>归属<select value={scope} onChange={(event) => setScope(event.target.value as "personal" | "team")}><option value="personal">个人</option><option value="team">团队</option></select></label>
        {fields.map(([name, schema, group, required]) => (
          <label key={`${group}:${name}`}>{String(schema.title || name)}
            <input
              type={schema.format === "password" || group === "credential" ? "password" : "text"}
              value={String(values[name] || "")}
              onChange={(event) => setValues((current) => ({ ...current, [name]: event.target.value }))}
              required={required}
            />
          </label>
        ))}
        {error ? <div className="kw-form-error" role="alert">{error}</div> : null}
        <div className="kw-modal-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button type="submit" className="kw-primary-small" disabled={busy || !connectorKey}>{busy ? <Loader2 className="kw-spin" size={14} /> : <Upload size={14} />} 保存并验证</button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="kw-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="kw-modal" role="dialog" aria-modal="true" aria-label={title}>
        <header><h2>{title}</h2><button type="button" onClick={onClose} aria-label="关闭"><X size={17} /></button></header>
        {children}
      </section>
    </div>
  );
}
