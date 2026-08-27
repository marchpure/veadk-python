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
  Bell,
  Check,
  ChevronRight,
  CirclePlus,
  Database,
  FileText,
  Loader2,
  MessageSquare,
  PanelRight,
  Play,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Square,
  Upload,
  User,
  X,
} from "lucide-react";
import { login } from "../../../adk/identity";
import { resolveIdentity, type AuthStatus } from "../../../adk/identity";
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
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    if (!startedAt || streamState === "done") return;
    const timer = window.setInterval(() => setElapsedMs(Date.now() - startedAt), 250);
    return () => window.clearInterval(timer);
  }, [startedAt, streamState]);

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
      setElapsedMs(0);
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
      setElapsedMs(0);
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

  const selectedDraft = draftResourceError
    ? null
    : draft || drafts.find((item) => item.draft_id === route.draftId) || null;
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
    <div className={`kw-shell${selectedDraft ? " has-draft" : ""}`}>
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
          <div className="kw-brand">
            <span className="kw-brand-mark">K</span>
            <span>知识资产</span>
          </div>
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
              <FileText size={15} />
              <span className="kw-truncate">{item.goal}</span>
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
        <header className="kw-topbar">
          <div className="kw-breadcrumb">
            <button type="button" onClick={() => setRoute("welcome")}>知识资产</button>
            {selectedDraft ? <><ChevronRight size={14} /><span>{selectedDraft.goal}</span></> : null}
          </div>
          <div className="kw-top-actions">
            {selectedDraft ? (
              <>
                <button type="button" onClick={() => setShowVersions(true)}>版本</button>
                <button type="button" className="kw-primary-small" onClick={() => setShowPublish(true)} disabled={!revisions.length}>
                  发布
                </button>
              </>
            ) : null}
          </div>
        </header>
        {error ? (
          <div className="kw-error" role="alert">
            <AlertCircle size={16} /> <span>{error}</span>
            <button type="button" onClick={() => setError("")} aria-label="关闭错误"><X size={14} /></button>
          </div>
        ) : null}
        {route.file === "welcome" && !selectedDraft ? (
          <WelcomeEntryView onCreate={(goal) => { setWelcomeGoal(goal); setRoute("skill_new"); }} />
        ) : route.file === "skill_new" ? (
          <section className="kw-create-layout">
            <SkillNewView
              connections={personalConnections}
              selectedIds={selectedConnectionIds}
              onSelectedIdsChange={setSelectedConnectionIds}
              onCreate={createAndGenerate}
              onUpload={uploadSkillInput}
              onAddConnection={() => setShowConnectionForm(true)}
              busy={busy === "generate"}
              initialGoal={welcomeGoal}
            />
            <CreationRail connectionCount={personalConnections.length} />
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
            elapsedMs={elapsedMs}
            activeInvocation={activeInvocation}
            busy={busy}
            resourceError={draftResourceError}
            onSend={sendMessage}
            onCancel={cancel}
            onReconnect={() => void stream()}
            onRetry={() => void retryInvocation()}
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
          revisions={revisions}
          connections={availableConnections}
          onClose={closeRouteModal}
        />
      ) : null}
      {routeModal === "publish" ? (
        <Modal title="发布 Skill" onClose={closeRouteModal}>
          <p className="kw-muted">发布会固定当前不可变 Revision，后续修改将创建新版本。</p>
          <div className="kw-publish-actions">
            <button type="button" onClick={() => void publish("personal")} disabled={busy === "publish"}>发布到个人</button>
            <button type="button" className="kw-primary-small" onClick={() => void publish("team")} disabled={busy === "publish"}>发布到团队</button>
          </div>
        </Modal>
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
}: {
  connections: ConnectionProfile[];
  selectedIds: string[];
  onSelectedIdsChange: (ids: string[]) => void;
  onCreate: (goal: string, connectionIds: string[], trialTask: string, uploadIds: string[]) => Promise<void>;
  onUpload: (file: File, onProgress: (percent: number) => void) => Promise<UploadResult>;
  onAddConnection: () => void;
  busy: boolean;
  initialGoal?: string;
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
        <span className="kw-eyebrow">KNOWLEDGE WORKSPACE V1</span>
        <h1>让 Agent 帮你解决一个真实问题</h1>
        <p>描述谁会使用它、要解决什么问题，再选择可访问的真实连接。生成后可以继续对话修改。</p>
      </div>
      <form className="kw-create-form" onSubmit={submit}>
        <label>
          谁使用，解决什么问题？
          <textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="例如：让售后工程师排查最近的蓝牙断连并给出处置建议"
            rows={4}
            required
          />
        </label>
        <div className="kw-form-section">
          <div className="kw-form-section-title">
            <span>选择“我的连接”</span>
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
          可选：先试一句真实任务
          <textarea value={trialTask} onChange={(event) => setTrialTask(event.target.value)} placeholder="生成后直接用什么输入试跑？" rows={3} />
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

function WelcomeEntryView({ onCreate }: { onCreate: (goal: string) => void }) {
  const [message, setMessage] = useState("");
  return (
    <section className="kw-welcome-entry">
      <div className="kw-welcome-entry-mark"><MessageSquare size={22} /></div>
      <span className="kw-eyebrow">KNOWLEDGE WORKSPACE V1</span>
      <h1>从一个真实问题开始</h1>
      <p>告诉 Agent 谁会使用、希望解决什么问题。下一步会让你选择真实连接，再生成并试用 Skill。</p>
      <div className="kw-welcome-composer">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="例如：让支持工程师排查线上告警并给出处理建议"
          rows={3}
          aria-label="描述你的问题"
        />
        <div className="kw-welcome-composer-footer">
          <span>不会在浏览器中保存凭据或运行结果。</span>
          <button type="button" className="kw-primary-small" onClick={() => onCreate(message)}>
            <Send size={14} /> 开始创建
          </button>
        </div>
      </div>
      <button type="button" className="kw-link-button kw-welcome-create-link" onClick={() => onCreate(message)}>
        或直接打开 Skill 创建表单 <ChevronRight size={14} />
      </button>
    </section>
  );
}

function CreationRail({ connectionCount }: { connectionCount: number }) {
  return (
    <aside className="kw-creation-rail" aria-label="创建流程">
      <div className="kw-creation-rail-heading">
        <MessageSquare size={16} />
        <strong>创建助手</strong>
      </div>
      <p>先描述真实问题，再授权可访问的连接。生成后可以在右侧对话中继续修改。</p>
      <ol>
        <li className="is-active"><span>1</span><div><strong>描述目标</strong><small>说明谁使用、要解决什么问题</small></div></li>
        <li><span>2</span><div><strong>选择连接</strong><small>{connectionCount} 个连接由当前 BFF 返回</small></div></li>
        <li><span>3</span><div><strong>生成并试用</strong><small>运行状态和结果来自真实服务</small></div></li>
      </ol>
      <div className="kw-creation-rail-note">不会在浏览器中保存凭据或生成结果。</div>
    </aside>
  );
}

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
  elapsedMs,
  activeInvocation,
  busy,
  resourceError,
  onSend,
  onCancel,
  onReconnect,
  onRetry,
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
  elapsedMs: number;
  activeInvocation: Invocation | null;
  busy: string;
  resourceError: { code: string; message: string } | null;
  onSend: (message: string, intent: "update" | "run") => Promise<void>;
  onCancel: () => Promise<void>;
  onReconnect: () => void;
  onRetry: () => void;
  onRetryLoad: () => void;
}) {
  const [message, setMessage] = useState("");
  const timelineEnd = useRef<HTMLDivElement>(null);
  useEffect(() => timelineEnd.current?.scrollIntoView({ block: "nearest" }), [events, assistantText]);
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
  const seconds = (elapsedMs / 1000).toFixed(1);
  const failedEvent = [...events].reverse().find((event) => event.type === "run.failed");
  return (
    <section className="kw-draft-layout">
      <div className="kw-draft-center">
        <div className="kw-draft-title">
          <div>
            <span className="kw-eyebrow">SKILL DRAFT</span>
            <h1>{draft.goal}</h1>
            <p>{revisions.length ? `当前 v${revisions.at(-1)?.number} · ${draft.lifecycle}` : draft.lifecycle}</p>
          </div>
          <div className="kw-invocation-state">
            {activeInvocation ? <span>{streamState === "connected" ? "实时运行中" : streamState === "disconnected" ? "连接已断开" : streamState === "done" ? "已结束" : "等待中"} · {seconds}s</span> : null}
          </div>
        </div>
        {draft.lifecycle === "failed" ? (
          <div className="kw-state-card is-failed" role="status">
            <strong>上一次试跑失败</strong>
            <span>可以查看失败原因并重试，不会创建重复 invocation。</span>
            {activeInvocation ? <button type="button" onClick={onRetry}>重试本次运行</button> : null}
          </div>
        ) : null}
        {resourceError ? (
          <div className="kw-state-card is-failed" role="alert">
            <strong>
              {resourceError.code === "FORBIDDEN"
                ? "当前账号没有访问该资源的权限"
                : resourceError.code === "CONNECTION_NOT_READY"
                  ? "连接暂不可用"
                  : resourceError.code === "PUBLISH_GATE_FAILED"
                    ? "当前资源尚未通过发布门禁"
                    : "无法加载当前资源"}
            </strong>
            <span>{resourceError.message}</span>
            <button type="button" onClick={onRetryLoad}>重新加载资源</button>
          </div>
        ) : null}
        <ArtifactViewer artifact={artifact} />
        <div className="kw-draft-placeholder">
          <FileText size={22} />
          <span>{artifact ? "Artifact 已关联到本次运行" : "生成后，真实运行结果会显示在这里"}</span>
        </div>
      </div>
      <aside className="kw-chat">
        <div className="kw-chat-heading">
          <div className="kw-chat-title"><PanelRight size={16} /> 对话修改 <span>{activeInvocation ? "· 实时" : ""}</span></div>
          {activeInvocation && streamState === "connected" ? <button type="button" onClick={() => void onCancel()}><Square size={13} /> 取消</button> : null}
          {activeInvocation && streamState === "disconnected" ? <button type="button" onClick={onReconnect}><RefreshCw size={13} /> 从 {events.at(-1)?.id || "起点"} 重连</button> : null}
        </div>
        <div className="kw-timeline" aria-live="polite">
          {!events.length && !assistantText ? <div className="kw-chat-empty">告诉 Agent 你想如何修改或试跑当前 Skill。</div> : null}
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
}: {
  draft: Draft | null;
  revision: Revision | null;
  onBack: () => void;
}) {
  if (!draft || !revision) return <div className="kw-empty-page">正在从 BFF 恢复已发布版本…</div>;
  return (
    <section className="kw-published">
      <span className="kw-eyebrow">PUBLISHED SKILL</span>
      <h1>{revision.skill_name}</h1>
      <p>{draft.goal}</p>
      <div className="kw-published-card">
        <strong>已发布不可变版本 v{revision.number}</strong>
        <code>sha256:{revision.sha256}</code>
        <span>发布状态和可见范围由 BFF 返回。</span>
      </div>
      <button type="button" className="kw-primary-small" onClick={onBack}>返回工作台</button>
    </section>
  );
}

function WorkspaceStateModal({
  kind,
  revisions,
  connections,
  onClose,
}: {
  kind: string;
  revisions: Revision[];
  connections: ConnectionProfile[];
  onClose: () => void;
}) {
  const content: Record<string, { title: string; body: string }> = {
    advanced: { title: "高级设置", body: "高级运行参数由当前 BFF 资源策略返回，前端不保存服务端业务状态。" },
    test_records: { title: "试跑记录", body: "试跑记录由 invocation 与 revision 服务返回。" },
    tools: { title: "工具与能力", body: `${connections.length} 个连接已由 BFF 返回，可用能力在运行时按权限决定。` },
    agent: { title: "Agent 授权", body: "发布后的 Agent 授权范围由 publication 返回。" },
    share_run: { title: "共享试跑", body: "共享试跑会使用已发布 Revision，并由服务端重新校验连接权限。" },
    instructions: { title: "调用说明", body: "调用说明对应当前不可变 Revision，版本摘要由 BFF 返回。" },
    versions: { title: "版本历史", body: revisions.length ? `当前共有 ${revisions.length} 个不可变版本。` : "暂无已固化版本。" },
  };
  const selected = content[kind] || { title: "工作区状态", body: "该状态由 BFF 资源与权限返回。" };
  return (
    <Modal title={selected.title} onClose={onClose}>
      <p className="kw-muted">{selected.body}</p>
      {kind === "versions" && revisions.map((revision) => (
        <div className="kw-version-row" key={revision.revision_id}>
          <span>v{revision.number} · {revision.skill_name}</span>
          <code>{revision.sha256.slice(0, 16)}…</code>
        </div>
      ))}
    </Modal>
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
