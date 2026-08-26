import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  FileText,
  Loader2,
  LockKeyhole,
  Play,
  Settings2,
  ShieldAlert,
  Upload,
} from "lucide-react";
import {
  createRequestContext,
  KnowledgeAdapterError,
  type KnowledgeCommandResult,
} from "../../../production/ports";
import {
  bootstrapWorkspace,
  getWorkspaceAdapter,
  useStore,
  resourceStore,
} from "../../../production/store";
import BuildDetailsDrawer from "../Layout/BuildDetailsDrawer";
import { readModelRetryable } from "../Layout/BuildDetailsDrawer";
import { scenarioForRoute, trackShellEvent, trackShellEventOnce } from "../Layout/shellTelemetry";

type StageId = "prepare" | "debug" | "publish";
type ServerReadModel = Record<string, unknown>;
type CommandName = "skill-draft.run" | "skill-draft.retry" | "evaluation.run" | "publication.publish" | "invocation.start";

const stringField = (value: unknown, key: string): string | undefined => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const field = (value as Record<string, unknown>)[key];
  return typeof field === "string" && field ? field : undefined;
};

const DEFAULT_JOURNEY = {
  title: "Skill",
  description: "服务端返回 SkillDraft、BuildPlan、operation 和 ViewRevision 后，页面按真实状态展示。",
};

const STAGES: Array<{ id: StageId; label: string; description: string }> = [
  { id: "prepare", label: "准备素材", description: "确认数据、知识和权限边界。" },
  { id: "debug", label: "调试能力", description: "运行草稿并查看受控 Artifact。" },
  { id: "publish", label: "发布给 Agent", description: "通过评测门禁后提交发布。" },
];

const statusOf = (model: ServerReadModel | null): string | null => {
  if (!model) return null;
  for (const key of ["stage", "currentStage", "viewState", "status", "executionState"]) {
    if (typeof model[key] === "string") return model[key] as string;
  }
  return null;
};

function stageFromReadModel(model: ServerReadModel | null): StageId | null {
  if (!model) return null;
  const gate = model.policyGateResult ?? model.policy_gate_result ?? model.gate;
  if (gate && typeof gate === "object") {
    const decision = String((gate as ServerReadModel).decision ?? "").toLowerCase();
    if (["publishable", "passed", "blocked", "not_publishable", "failed"].includes(decision)) {
      return "publish";
    }
  }
  const evaluation = model.evaluationRun ?? model.evaluation_run ?? model.evaluation;
  if (evaluation && typeof evaluation === "object") {
    const evaluationStatus = String((evaluation as ServerReadModel).status ?? "").toLowerCase();
    if (["succeeded", "failed", "blocked", "publishable", "passed"].includes(evaluationStatus)) {
      return "publish";
    }
    if (evaluationStatus) return "debug";
  }
  const candidates = [
    model.stage,
    model.currentStage,
    model.viewState,
    model.status,
    model.evaluationStatus,
    model.evaluation_status,
    model.policyGateResult && typeof model.policyGateResult === "object"
      ? (model.policyGateResult as ServerReadModel).decision
      : undefined,
    model.gate && typeof model.gate === "object"
      ? (model.gate as ServerReadModel).decision
      : undefined,
    model.executionState,
  ].filter((value): value is string => typeof value === "string");
  for (const candidate of candidates) {
    if (/publish|published|publishable/i.test(candidate)) return "publish";
    if (/debug|evaluat|running|partially_succeeded|ready_for_evaluation/i.test(candidate)) return "debug";
    if (/prepare|material|planning|awaiting_input|draft|received|context_resolved/i.test(candidate)) return "prepare";
  }
  return null;
}

function resultModel(result: KnowledgeCommandResult | null): ServerReadModel | null {
  if (!result?.result || typeof result.result !== "object") return null;
  return result.result as ServerReadModel;
}

function errorFromResult(result: KnowledgeCommandResult | null): ServerReadModel | null {
  const model = resultModel(result);
  return model?.error && typeof model.error === "object" ? model.error as ServerReadModel : null;
}

function textFromUnknown(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) return value;
  if (!value || typeof value !== "object") return undefined;
  const record = value as ServerReadModel;
  for (const key of ["message", "detail", "reason", "description"]) {
    if (typeof record[key] === "string" && (record[key] as string).trim()) {
      return record[key] as string;
    }
  }
  return undefined;
}

function authErrorFromReadModel(model: ServerReadModel | null): string | null {
  if (!model) return null;
  const error = model.error && typeof model.error === "object"
    ? model.error as ServerReadModel
    : null;
  const code = String(error?.code ?? model.errorCode ?? model.executionState ?? "").toLowerCase();
  if (!["unauthenticated", "forbidden", "credential_expired", "credential_blocked", "permission_denied"].includes(code)) {
    return null;
  }
  return textFromUnknown(error) ?? textFromUnknown(model.error) ?? "凭证或访问权限需要修复。";
}

function isAuthError(error: unknown, result: KnowledgeCommandResult | null): boolean {
  const code = (error instanceof KnowledgeAdapterError
    ? error.issue.code
    : errorFromResult(result)?.code);
  const normalized = typeof code === "string" ? code.toLowerCase() : "";
  return normalized === "unauthenticated" || normalized === "forbidden" ||
    normalized === "credential_expired" || normalized === "credential_blocked" ||
    normalized === "permission_denied";
}

function messageFor(error: unknown, result: KnowledgeCommandResult | null): string {
  if (error instanceof KnowledgeAdapterError) return error.issue.message;
  const model = errorFromResult(result);
  return typeof model?.message === "string" ? model.message : "服务端未确认此操作。";
}

function publishedVersionFromModel(model: ServerReadModel | null): ServerReadModel | null {
  const value = model?.publishedVersion ?? model?.published_version ?? model?.publishedSkillVersion ??
    model?.published_skill_version;
  return value && typeof value === "object" ? value as ServerReadModel : null;
}

function evaluationModelFromModel(model: ServerReadModel | null): ServerReadModel | null {
  const value = model?.evaluationRun ?? model?.evaluation_run ?? model?.evaluation;
  return value && typeof value === "object" ? value as ServerReadModel : null;
}

function gateModelFromModel(model: ServerReadModel | null): ServerReadModel | null {
  const value = model?.policyGateResult ?? model?.policy_gate_result ?? model?.gate;
  return value && typeof value === "object" ? value as ServerReadModel : null;
}

class ArtifactBoundary extends React.Component<
  { children: React.ReactNode; onError: (message: string) => void },
  { error: string | null }
> {
  state = { error: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error.message : "Artifact 渲染失败。" };
  }

  componentDidCatch(error: unknown) {
    this.props.onError(error instanceof Error ? error.message : "Artifact 渲染失败。");
  }

  render() {
    if (this.state.error) {
      return (
        <div role="status" aria-label="Artifact 渲染错误" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-800">
          <div className="font-medium">Artifact 暂时无法渲染</div>
          <div>{this.state.error}</div>
        </div>
      );
    }
    return this.props.children;
  }
}

function ControlledArtifact({
  model,
  serverError,
  onError,
}: {
  model: ServerReadModel;
  serverError?: string | null;
  onError: (message: string) => void;
}) {
  if (serverError) {
    return (
      <div role="status" aria-label="Artifact 渲染错误" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-800">
        <div className="font-medium">Artifact 暂时无法渲染</div>
        <div>{serverError}</div>
      </div>
    );
  }
  return (
    <ArtifactBoundary onError={onError}>
      <pre className="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-200">
        {JSON.stringify(model, null, 2)}
      </pre>
    </ArtifactBoundary>
  );
}

export default function JourneyDetailView({
  fileId,
  errorState,
  telemetryEnabled = true,
  searchParams,
  setSearchParams,
}: any) {
  const resources = useStore(resourceStore);
  const fallbackTitle = fileId.startsWith("journey_")
    ? "Skill Builder"
    : "Skill";
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<KnowledgeCommandResult | null>(null);
  const [lastError, setLastError] = useState<unknown>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [invocationResult, setInvocationResult] = useState<ServerReadModel | null>(null);
  const [simulationInput, setSimulationInput] = useState("请返回当前 Skill 的结果。");
  const telemetryViewRef = useRef<{ fileId: string; draft: boolean; debug: boolean; eval: boolean; published: boolean }>({
    fileId,
    draft: false,
    debug: false,
    eval: false,
    published: false,
  });
  const telemetryErrorRef = useRef<string | null>(null);

  const draftId = searchParams.get("draft_id") || searchParams.get("skillId") || undefined;
  const resource = (
    draftId
      ? resources.find((item: any) => item.id === draftId || item.resourceId === draftId)
      : fileId.startsWith("journey_")
        ? resources.find((item: any) => item.resourceKind === "skill_draft")
        : resources.find((item: any) => item.id === fileId || item.resourceId === fileId)
  ) as ServerReadModel | undefined;
  const serverModel = useMemo<ServerReadModel | null>(() => {
    if (!resource) return resultModel(lastResult);
    const nested = resource.readModel ?? resource.skillDraftReadModel ?? resource.viewModel;
    return nested && typeof nested === "object"
      ? { ...resource, ...(nested as ServerReadModel) }
      : resource;
  }, [resource, lastResult]);
  const operation = resultModel(lastResult);
  const effectiveModel = operation ?? serverModel;
  const journey = {
    title: stringField(effectiveModel ?? serverModel, "title") ??
      stringField(effectiveModel ?? serverModel, "name") ??
      stringField(resource, "displayName") ??
      stringField(resource, "name") ??
      fallbackTitle,
    description: stringField(effectiveModel ?? serverModel, "description") ??
      stringField(resource, "description") ??
      DEFAULT_JOURNEY.description,
  };
  const currentStage = stageFromReadModel(operation) ?? stageFromReadModel(serverModel);
  const currentIndex = STAGES.findIndex((stage) => stage.id === currentStage);
  const retryable = readModelRetryable(effectiveModel);
  const modelAuthError = authErrorFromReadModel(effectiveModel);
  const serverArtifactError = textFromUnknown(effectiveModel?.renderError);
  const evaluationModel = evaluationModelFromModel(effectiveModel);
  const gateModel = gateModelFromModel(effectiveModel);
  const publishedVersion = publishedVersionFromModel(effectiveModel);
  const publishedStatus = String(
    effectiveModel?.status ?? effectiveModel?.publicationStatus ?? effectiveModel?.publication_status ?? "",
  ).toLowerCase();
  const isPublished = publishedStatus === "published" ||
    String(publishedVersion?.status ?? "").toLowerCase() === "published" ||
    Boolean(effectiveModel?.published === true);
  const evaluationStatus = String(
    gateModel?.decision ?? effectiveModel?.evaluationStatus ?? effectiveModel?.evaluation_status ?? "",
  ).toLowerCase();
  const evaluationPassed = evaluationStatus === "publishable" ||
    evaluationStatus === "passed" ||
    String(evaluationModel?.status ?? "").toLowerCase() === "succeeded";
  const readyForEvaluation = String(
    effectiveModel?.status ?? serverModel?.status ?? "",
  ).toLowerCase() === "ready_for_evaluation";
  const currentStageConfig = STAGES.find((stage) => stage.id === currentStage) ?? {
    id: "prepare" as StageId,
    label: "等待服务端确认",
    description: "服务端尚未返回当前草稿的生命周期阶段。",
  };
  const routeAuthError = errorState === "auth_failed"
    ? "连接器凭证已失效或当前账号无权访问该素材。"
    : null;
  const routeArtifactError = errorState === "render_error"
    ? "服务端返回的 Artifact 暂时无法渲染。"
    : null;
  const displayedRouteAuthError = authError ?? modelAuthError ?? routeAuthError;
  const displayedRouteArtifactError = serverArtifactError ?? artifactError ?? routeArtifactError;

  useEffect(() => {
    if (!telemetryEnabled) return;
    if (telemetryViewRef.current.fileId !== fileId) {
      telemetryViewRef.current = { fileId, draft: false, debug: false, eval: false, published: false };
      telemetryErrorRef.current = null;
    }
    const view = telemetryViewRef.current;
    if (!view.draft) {
      trackShellEventOnce("skill_draft_view", fileId, { scenario: scenarioForRoute(fileId) });
      view.draft = true;
    }
    if (currentStage === "debug" && !view.debug) {
      trackShellEventOnce("skill_debug_view", fileId);
      view.debug = true;
    }
    if (currentStage === "publish" && !isPublished && !view.eval) {
      trackShellEventOnce("skill_eval_view", fileId, {
        status: evaluationPassed ? "passed" : "failed",
      });
      view.eval = true;
    }
    if (isPublished && !view.published) {
      trackShellEventOnce("skill_published_view", fileId, {
        skill_id: String(publishedVersion?.skillId ?? publishedVersion?.id ?? effectiveModel?.skillId ?? fileId),
      });
      view.published = true;
    }
  }, [currentStage, fileId, isPublished, evaluationPassed, publishedVersion, effectiveModel, telemetryEnabled]);

  useEffect(() => {
    if (!telemetryEnabled) return;
    const errorKey = routeAuthError
      ? `auth:${fileId}:${routeAuthError}`
      : modelAuthError
        ? `auth:${fileId}:${modelAuthError}`
        : routeArtifactError
          ? `artifact:${fileId}:${routeArtifactError}`
          : serverArtifactError
            ? `artifact:${fileId}:${serverArtifactError}`
            : effectiveModel?.executionState === "schema_drift"
              ? `schema:${fileId}:${String(effectiveModel?.missingField ?? effectiveModel?.missing_field ?? "")}`
              : null;
    if (errorKey && telemetryErrorRef.current === errorKey) return;
    telemetryErrorRef.current = errorKey;
    const executionState = effectiveModel?.executionState;
    if (executionState === "schema_drift") {
      trackShellEventOnce("skill_schema_drift_warning_shown", fileId, {
        missing_field: String(effectiveModel?.missingField ?? effectiveModel?.missing_field ?? ""),
      });
    }
    if (serverArtifactError || routeArtifactError) {
      trackShellEventOnce("skill_debug_render_error_shown", fileId, {
        error_type: String(effectiveModel?.renderErrorType ?? "route_render_error"),
      });
      if (serverArtifactError) setArtifactError(serverArtifactError);
    }
    if (modelAuthError || routeAuthError) {
      trackShellEventOnce("skill_auth_error_shown", fileId, {
        error_source: String(resource?.sourceName ?? resource?.connectorKey ?? scenarioForRoute(fileId)),
      });
    }
  }, [effectiveModel, modelAuthError, routeAuthError, routeArtifactError, serverArtifactError, fileId, resource, telemetryEnabled]);

  const updateRoute = (file: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("file", file);
    params.delete("error_state");
    setSearchParams(params);
  };

  const runCommand = async (
    command: CommandName,
    trackPrimary = true,
  ) => {
    if (busy) return;
    setBusy(true);
    setLastError(null);
    setAuthError(null);
    setArtifactError(null);
    if (command === "publication.publish") {
      trackShellEvent("skill_publish_submit", {
        current_step: currentIndex + 1,
      });
    }
    if (trackPrimary) {
      trackShellEvent("skill_primary_cta_click", {
        cta_name: command,
        current_step: currentIndex + 1,
      });
    }
    try {
      const currentDraftId = draftId || (typeof resource?.id === "string" ? resource.id : "");
      if (!currentDraftId) {
        updateRoute("skill_builder");
        return;
      }
      const revision = Number(resource?.revision ?? effectiveModel?.revision ?? 1);
      const requestContext = createRequestContext();
      const result = command === "skill-draft.run"
        ? await getWorkspaceAdapter().command(
          {
            command: "skill-draft.run",
            payload: { draftId: currentDraftId, revision, traceId: `shell-${Date.now()}`, maxSteps: 10, budget: 10_000 },
          },
          requestContext,
        )
        : command === "skill-draft.retry"
          ? await getWorkspaceAdapter().command(
            {
              command: "skill-draft.retry",
              payload: {
                draftId: currentDraftId,
                revision,
                traceId: `shell-${Date.now()}`,
                maxSteps: 10,
                budget: 10_000,
                retryOfOperationId: String(effectiveModel?.operationId ?? lastResult?.operationId ?? ""),
              },
            },
            requestContext,
          )
          : command === "evaluation.run"
            ? await getWorkspaceAdapter().command(
              {
                command: "evaluation.run",
                payload: { targetId: currentDraftId, suiteId: "default-step3", environment: "test", caseIds: [] },
              },
              requestContext,
            )
            : command === "invocation.start"
              ? await getWorkspaceAdapter().command(
                {
                  command: "invocation.start",
                  payload: {
                    skillVersionId: String(publishedVersion?.id ?? effectiveModel?.skillVersionId ?? currentDraftId),
                    skillViewRevisionId: String(
                      effectiveModel?.skillViewRevisionId ??
                      stringField(effectiveModel?.skillViewRevision, "id") ??
                      "server-selected",
                    ),
                    inputRef: {
                      uri: "inline://knowledge-workspace/simulation",
                      kind: "inline",
                      sha256: "0".repeat(64),
                      mediaType: "application/json",
                      bytes: new TextEncoder().encode(simulationInput).byteLength,
                    },
                    callerId: "knowledge-workspace-simulation",
                  },
                },
                requestContext,
              )
              : await getWorkspaceAdapter().command(
              {
                command: "publication.publish",
                payload: { draftId: currentDraftId, revision, semver: "0.1.0", visibility: "team" },
              },
              requestContext,
            );
      setLastResult(result);
      if (command === "invocation.start") {
        setInvocationResult(resultModel(result));
      }
      if (!result.accepted || errorFromResult(result)) {
        if (isAuthError(null, result)) {
          const message = messageFor(null, result);
          setAuthError(message);
          trackShellEvent("skill_auth_error_shown", {
            error_source: String(resource?.sourceName ?? resource?.connectorKey ?? scenarioForRoute(fileId)),
          });
        } else {
          setLastError(messageFor(null, result));
        }
        return;
      }
      if (command === "publication.publish") {
        const publicationStatus = resultModel(result)?.status;
        if (publicationStatus === "succeeded" || publicationStatus === "published") {
          trackShellEvent("skill_published_view", { skill_id: currentDraftId });
        }
      }
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
    } catch (error) {
      setLastError(error);
      if (isAuthError(error, null)) {
        setAuthError(messageFor(error, null));
        trackShellEvent("skill_auth_error_shown", {
          error_source: String(resource?.sourceName ?? resource?.connectorKey ?? scenarioForRoute(fileId)),
        });
      }
    } finally {
      setBusy(false);
    }
  };

  const displayedAuthError = displayedRouteAuthError;
  const invocationTraceId = String(
    invocationResult?.invocation && typeof invocationResult.invocation === "object"
      ? (invocationResult.invocation as ServerReadModel).traceId ?? ""
      : invocationResult?.traceId ?? effectiveModel?.traceId ?? "",
  );
  const startInvocation = () => {
    trackShellEvent("skill_simulate_call_click", { trace_id: invocationTraceId });
    void runCommand("invocation.start", false);
  };
  const artifactViewModel = effectiveModel?.skillViewRevision &&
    typeof effectiveModel.skillViewRevision === "object"
    ? effectiveModel.skillViewRevision as ServerReadModel
    : null;
  const retry = () => {
    if (!retryable && !displayedAuthError) return;
    if (currentStage === "prepare" || currentStage === "debug") {
      const operationId = effectiveModel?.operationId ?? lastResult?.operationId;
      void runCommand(operationId ? "skill-draft.retry" : "skill-draft.run");
    } else if (currentStage === "publish") {
      void runCommand("publication.publish");
    } else if (draftId || resource?.id) {
      void runCommand("skill-draft.run");
    }
  };

  const primaryAction = isPublished
    ? { label: "在 Agent 中使用", icon: Play, action: () => void runCommand("invocation.start") }
    : currentStage === "prepare"
    ? { label: "准备素材", icon: Upload, action: () => {
      trackShellEvent("skill_primary_cta_click", { cta_name: "准备素材", current_step: 1 });
      updateRoute("add_data");
    } }
    : currentStage === "debug" && readyForEvaluation
      ? { label: "检查并发布", icon: CheckCircle2, action: () => void runCommand("evaluation.run") }
    : currentStage === "debug"
      ? { label: "运行 Skill 草稿", icon: Play, action: () => void runCommand("skill-draft.run") }
      : currentStage === "publish"
        ? { label: "提交发布", icon: ChevronRight, action: () => void runCommand("publication.publish") }
        : { label: "等待服务端确认", icon: Loader2, action: () => undefined };
  const PrimaryIcon = primaryAction.icon;
  const isBlocked = !currentStage || Boolean(displayedRouteAuthError) ||
    (currentStage === "publish" && !isPublished && !evaluationPassed);

  return (
    <div className="min-h-full bg-slate-50/70 px-4 py-5 md:px-8 md:py-8">
      <div className="mx-auto w-full max-w-5xl">
        <button type="button" className="mb-5 inline-flex items-center text-sm text-slate-500 hover:text-slate-900" onClick={() => updateRoute("welcome")}>
          <ArrowLeft size={15} className="mr-1.5" /> 返回工作区
        </button>
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <header className="flex items-start gap-4 border-b border-slate-100 p-6 md:p-8">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600"><FileText size={22} /></div>
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">Skill draft</p>
              <h1 className="mt-1 text-xl font-semibold text-slate-900">{journey.title} Skill</h1>
              <p className="mt-1 text-sm text-slate-500">{journey.description}</p>
            </div>
            <button
              type="button"
              aria-label="打开构建详情"
              title="构建详情"
              onClick={() => {
                setDrawerOpen(true);
                trackShellEvent("skill_build_detail_drawer_open", { current_main_stage: currentIndex + 1 });
              }}
              className="ml-auto rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-800"
            >
              <Settings2 size={18} />
            </button>
          </header>

          <div className="grid grid-cols-1 gap-2 border-b border-slate-100 p-4 md:grid-cols-3 md:p-6">
            {STAGES.map((stage, index) => {
              const completed = index < currentIndex;
              const active = index === currentIndex;
              return (
                <div key={stage.id} className={`rounded-xl border p-4 ${active ? "border-blue-300 bg-blue-50/60" : completed ? "border-emerald-200 bg-emerald-50/50" : "border-slate-200 bg-slate-50"}`}>
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                    {completed ? <CheckCircle2 size={14} className="text-emerald-600" /> : <span>0{index + 1}</span>}
                    {active ? "当前阶段" : completed ? "已完成" : "等待中"}
                  </div>
                  <div className="mt-2 text-sm font-semibold text-slate-800">{stage.label}</div>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{stage.description}</p>
                </div>
              );
            })}
          </div>

          <div className="p-6 md:p-8">
            {displayedRouteAuthError ? (
              <div role="alert" className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
                <LockKeyhole size={19} className="mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <div className="font-medium">需要修复访问权限</div>
                  <p className="mt-1 text-sm">{displayedRouteAuthError}</p>
                  <div className="mt-3 flex gap-2">
                    <button type="button" onClick={() => updateRoute("add_data")} className="rounded-lg bg-amber-700 px-3 py-2 text-xs font-medium text-white hover:bg-amber-800">修复凭证</button>
                    <button type="button" onClick={retry} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-medium text-amber-800 hover:bg-amber-100">重试</button>
                  </div>
                </div>
              </div>
            ) : null}

            {effectiveModel?.executionState === "schema_drift" ? (
              <div role="status" className="mb-4 flex gap-3 rounded-xl border border-orange-200 bg-orange-50 p-4 text-orange-900">
                <ShieldAlert size={19} className="mt-0.5 shrink-0" />
                <div><div className="font-medium">Schema 漂移告警</div><p className="mt-1 text-sm">缺少字段：{String(effectiveModel?.missingField ?? effectiveModel?.missing_field ?? "服务端未提供")}。请重新确认字段映射后再运行 Skill。</p></div>
              </div>
            ) : null}

            {lastError ? (
              <div role="alert" className="mb-4 flex gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-red-900">
                <AlertTriangle size={19} className="mt-0.5 shrink-0" />
                <div><div className="font-medium">操作未完成</div><p className="mt-1 text-sm">{messageFor(lastError, null)}</p></div>
              </div>
            ) : null}

            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">{currentStageConfig.label}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
                  {currentStage ? "当前状态由服务端 read model 确认。" : "服务端尚未返回完整草稿状态，操作入口已锁定。"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={busy || isBlocked}
                  onClick={primaryAction.action}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <PrimaryIcon size={16} />}
                  {busy ? "服务端处理中…" : primaryAction.label}
                </button>
              </div>
            </div>

            <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                {statusOf(effectiveModel) ? <CheckCircle2 size={16} className="text-emerald-600" /> : <Loader2 size={16} className="text-slate-400" />}
                服务端状态：{statusOf(effectiveModel) ?? "等待 read model"}
              </div>
              <p className="mt-1 text-xs text-slate-500">浏览器不会把点击、计时器或本地存储当作构建完成。</p>
            </div>

            {(currentStage === "debug" || routeArtifactError) && (artifactViewModel || displayedRouteArtifactError) ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-800">Artifact</h3>
                  <button type="button" className="text-xs text-blue-600 hover:underline" onClick={startInvocation}>模拟调用</button>
                </div>
                <ControlledArtifact
                  model={artifactViewModel ?? {}}
                  serverError={displayedRouteArtifactError}
                  onError={(message) => {
                    setArtifactError(message);
                    trackShellEvent("skill_debug_render_error_shown", {
                      error_type: "artifact_boundary",
                    });
                  }}
                />
              </div>
            ) : null}

            {currentStage === "publish" && isBlocked ? (
              <p className="mt-4 text-xs text-slate-500">质量检查尚未由服务端确认通过，发布 CTA 已阻断。</p>
            ) : null}
            {currentStage === "publish" && evaluationModel ? (
              <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                <h3 className="font-semibold text-emerald-900">{evaluationPassed ? "质量检查通过" : "质量检查未通过"}</h3>
                <div className="mt-2 grid gap-2 text-xs text-emerald-800 md:grid-cols-3">
                  {["数据正确性", "指标口径对齐", "安全扫描 (PII)"].map((label) => (
                    <span key={label}>{evaluationPassed ? "✓" : "!"} {label}</span>
                  ))}
                </div>
              </div>
            ) : null}
            {isPublished ? (
              <div className="mt-4 rounded-xl border border-emerald-200 bg-white p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
                  <CheckCircle2 size={16} /> 已发布
                </div>
                <div className="mt-3 grid gap-3 text-xs text-slate-600 md:grid-cols-3">
                  <span>发布版本：{String(publishedVersion?.semver ?? effectiveModel?.version ?? "—")}</span>
                  <span>调用次数：{String(effectiveModel?.invocationCount ?? "—")}</span>
                  <span>质量分：{String(effectiveModel?.qualityScore ?? evaluationModel?.score ?? "—")}</span>
                </div>
                <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <div className="text-sm font-medium text-slate-800">Simulation</div>
                  <textarea
                    aria-label="模拟调用输入"
                    value={simulationInput}
                    onChange={(event) => setSimulationInput(event.target.value)}
                    className="mt-2 min-h-20 w-full resize-y rounded-lg border border-slate-200 bg-white p-2 text-xs text-slate-700 outline-none focus:border-blue-400"
                  />
                  <button
                    type="button"
                    disabled={busy}
                    onClick={startInvocation}
                    className="mt-2 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    执行调用
                  </button>
                </div>
                {invocationResult ? (
                  <div className="mt-3">
                    <div className="mb-1 text-xs text-slate-500">调用结果 · traceId: {invocationTraceId || "服务端未返回"}</div>
                    <pre className="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-200">
                      {JSON.stringify(invocationResult, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </section>
      </div>
      {drawerOpen ? (
        <BuildDetailsDrawer
          readModel={effectiveModel}
          onRetry={retry}
          onClose={() => setDrawerOpen(false)}
        />
      ) : null}
    </div>
  );
}
